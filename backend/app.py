from flask import Flask, jsonify, request, send_from_directory
from quality import compute_quality
# jsonify returns Python dicts/lists as proper JSON responses

import db
from db import init_db, get_latest_samples
from simulator import NeuralDataSimulator
from config import BUFFER_SIZE, NUM_CHANNELS

app = Flask(__name__)

# make one simulator instance for the app 
sim = NeuralDataSimulator()


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
    """
    Optional control endpoint: start/stop the simulator.
    POST JSON: {"action": "start"} or {"action": "stop"}
    """
    payload = request.get_json(silent=True) or {}
    action = payload.get("action", "").lower()

    if action == "start":
        sim.start()
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

    q = compute_quality(samples, fs=256, line_freq=60, window_seconds=2.0)
    return jsonify(q)


if __name__ == "__main__":
    # initialize database schema
    init_db()

    # start acquisition automatically
    sim.start()

    # run the API server
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)