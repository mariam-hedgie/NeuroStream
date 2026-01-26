from flask import Flask, jsonify, request, send_from_directory, Response
from quality import compute_quality
# jsonify returns Python dicts/lists as proper JSON responses

import time
import threading
import json
import csv
import io

import db
from db import init_db, get_latest_samples
from simulator import NeuralDataSimulator
from config import BUFFER_SIZE, NUM_CHANNELS, SAMPLE_RATE_HERTZ

app = Flask(__name__)

# make one simulator instance for the app 
sim = NeuralDataSimulator()

# quality monitoring and event tracking
_monitor_thread = None
_monitor_stop = threading.Event()

# track active incidents per channel
_active_incidents = {}

def _rows_to_samples(rows):
    """Convert DB rows [(ts, ch0, ch1..)] into compute_quality format."""
    samples = []
    for row in rows:
        samples.append({"timestamp": row[0], "channels": list(row[1:])})
    return samples


def _diagnose(reasons):
    """
    Turn quality reasons into a human-readable diagnosis.
    Keep it simple + explainable.
    """
    if not reasons:
        return "signal_ok"

    # priority order for diagnosis
    if "dropout_high" in reasons:
        return "channel_dropout_severe (possible lead off / packet loss / disconnection)"
    if "dropout_moderate" in reasons:
        return "channel_dropout_intermit (possible poor contact / intermittent stream)"
    if "flatline_rms_low" in reasons:
        return "flatline (possible disconnected electrode / muted input)"
    if "line_noise_high" in reasons:
        return "mains_interference_severe (60Hz contamination dominates)"
    if "line_noise_moderate" in reasons:
        return "mains_interference_mild (possible grounding/shielding issue)"
    if "clipping_peak_to_peak_high" in reasons:
        return "clipping/saturation (gain too high or motion artifact spikes)"

    return "signal_issue_unspecified"


@app.route("/health", methods=["GET"])
def health():
    """
    Simple health check endpoint.
    Useful for debugging and for monitoring in real systems.
    Confirms server is running.
    """
    return jsonify({"status": "ok"})


@app.route("/latest", methods=["GET"])
def latest():
    """
    Returns the latest BUFFER_SIZE samples as JSON.
    Each row is: [timestamp, ch0, ch1, ..., chN]
    """
    rows = get_latest_samples(limit=BUFFER_SIZE)

    # converts tuples to JSON format
    data = [] # list of tuples
    for row in rows: 
        timestamp = row[0]
        channels = list(row[1:])
        data.append({"timestamp": timestamp, "channels": channels})

    return jsonify({
        "num_channels": NUM_CHANNELS,
        "num_samples": len(data),
        "data": data
    })


@app.route("/stats", methods=["GET"])
def stats():
    """
    Basic summary statistics over the most recent samples.
    Computes mean per channel.
    Live analytics.
    """
    rows = get_latest_samples(limit=BUFFER_SIZE)
    if not rows:
        return jsonify({"error": "no data yet"}), 400

    # rows are (timestamp, ch0, ch1, ...)
    sums = [0.0] * NUM_CHANNELS
    n = 0

    for row in rows:
        vals = row[1:]  # channel values
        for i in range(NUM_CHANNELS):
            sums[i] += vals[i]
        n += 1

    means = [s / n for s in sums] # compute mean for each channel

    return jsonify({
        "num_samples": n,
        "mean_per_channel": means
    })

@app.route("/control", methods=["POST"])
def control():
    payload = request.get_json(silent=True) or {}
    action = payload.get("action", "").lower()

    if action == "start":
        sim.start()

        # start monitor if not running
        global _monitor_thread
        if _monitor_thread is None or not _monitor_thread.is_alive():
            _monitor_stop.clear()
            _monitor_thread = threading.Thread(target=_quality_monitor_loop, daemon=True)
            _monitor_thread.start()

        return jsonify({"status": "started"})

    elif action == "stop":
        sim.stop()
        return jsonify({"status": "stopped"})

    else:
        return jsonify({"error": "action must be 'start' or 'stop'"}), 400
    
@app.route("/")
def home():
    return send_from_directory("../frontend", "index.html")

@app.route("/main.js")
def main_js():
    return send_from_directory("../frontend", "main.js")

@app.route("/quality", methods=["GET"])
def quality():
    rows = get_latest_samples(limit=2000)

    # convert tuples to dict format expected by compute_quality() function
    samples = []
    for row in rows:
        samples.append({
            "timestamp": row[0],
            "channels": list(row[1:])
        })

    q = compute_quality(samples, fs=SAMPLE_RATE_HERTZ, line_freq=60, window_seconds=2.0)
    return jsonify(q)

@app.route("/config", methods=["GET"])
def config():
    return jsonify({
        "num_channels": NUM_CHANNELS,
        "sample_rate_hertz": SAMPLE_RATE_HERTZ,
        "buffer_size": BUFFER_SIZE
    })


@app.route("/events", methods=["GET"])
def events():
    limit = int(request.args.get("limit", 100))
    rows = db.get_events(limit=limit)
    return jsonify({"events": rows})


@app.route("/events/clear", methods=["POST"])
def events_clear():
    db.clear_events()
    return jsonify({"status": "cleared"})


@app.route("/export/events.json", methods=["GET"])
def export_events_json():
    rows = db.get_events(limit=10000)
    payload = json.dumps({"events": rows}, indent=2)
    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=events.json"}
    )


@app.route("/export/events.csv", methods=["GET"])
def export_events_csv():
    rows = db.get_events(limit=10000)

    # Expect rows as list[dict] ideally; if list[tuple], adjust in db.py
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(["id", "start_ts", "end_ts", "duration_s", "channel", "status", "reasons", "diagnosis"])

    for r in rows:
        # If db.get_events returns dicts:
        if isinstance(r, dict):
            writer.writerow([
                r.get("id"),
                r.get("start_ts"),
                r.get("end_ts"),
                r.get("duration_s"),
                r.get("channel"),
                r.get("status"),
                r.get("reasons"),
                r.get("diagnosis"),
            ])
        else:
            # fallback: tuple order
            writer.writerow(list(r))

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=events.csv"}
    )

def _quality_monitor_loop(poll_seconds=0.5, window_seconds=2.0, line_freq=60):
    """
    Runs in a background thread.
    Detects when a channel enters/exits degraded/bad and logs events.
    """
    global _active_incidents

    needed = int(SAMPLE_RATE_HERTZ * window_seconds)
    # overshoot to be safe
    limit = max(needed + 50, 500)

    while not _monitor_stop.is_set():
        try:
            rows = get_latest_samples(limit=limit)
            samples = _rows_to_samples(rows)

            q = compute_quality(
                samples,
                fs=SAMPLE_RATE_HERTZ,
                line_freq=line_freq,
                window_seconds=window_seconds
            )

            now_ts = samples[-1]["timestamp"] if samples else time.time()

            # per-channel transitions
            for chq in q.get("channels", []):
                ch = chq["channel"]
                status = chq["status"]
                reasons = chq.get("reasons", [])

                active = _active_incidents.get(ch)

                # entering degraded/bad
                if status in ("degraded", "bad") and active is None:
                    _active_incidents[ch] = {
                        "status": status,
                        "start_ts": now_ts,
                        "reasons": reasons,
                    }
                    db.insert_event(
                        start_ts=now_ts,
                        end_ts=None,
                        duration_s=None,
                        channel=ch,
                        status=status,
                        reasons=json.dumps(reasons),
                        diagnosis=_diagnose(reasons),
                    )

                # status worsened (degraded -> bad): close old + start new
                elif active is not None and active["status"] == "degraded" and status == "bad":
                    # close existing event
                    db.close_open_event(channel=ch, end_ts=now_ts)

                    # open new event
                    _active_incidents[ch] = {
                        "status": "bad",
                        "start_ts": now_ts,
                        "reasons": reasons,
                    }
                    db.insert_event(
                        start_ts=now_ts,
                        end_ts=None,
                        duration_s=None,
                        channel=ch,
                        status="bad",
                        reasons=json.dumps(reasons),
                        diagnosis=_diagnose(reasons),
                    )

                # recovered to good: close event
                elif status == "good" and active is not None:
                    db.close_open_event(channel=ch, end_ts=now_ts)
                    _active_incidents.pop(ch, None)

        except Exception as e:
            print("monitor error:", e)


        time.sleep(poll_seconds)


if __name__ == "__main__":
    init_db()

    sim.start()

    # start quality monitor
    _monitor_stop.clear()
    _monitor_thread = threading.Thread(target=_quality_monitor_loop, daemon=True)
    _monitor_thread.start()

    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)