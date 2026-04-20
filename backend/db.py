"""
creates and manages a lightweight database that stores time-stamped
multichannel neural samples. provides ordered retrieval for visualization
and analysis.
"""

import sqlite3
import json
from config import DB_PATH, NUM_CHANNELS


def _connect():
    # timeout helps if multiple threads hit sqlite
    conn = sqlite3.connect(DB_PATH, timeout=10)
    return conn


def init_db():
    conn = _connect()
    cursor = conn.cursor()

    # build dynamic SQL for channel columns
    channel_cols = ", ".join([f"ch{i} REAL" for i in range(NUM_CHANNELS)])

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS neural_data (
            timestamp REAL,
            {channel_cols}
        )
    """)

    # IMPORTANT: allow open incidents (end_ts + duration_s can be NULL)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_ts REAL NOT NULL,
            end_ts REAL,
            duration_s REAL,
            channel INTEGER NOT NULL,
            status TEXT NOT NULL,
            reasons TEXT NOT NULL,
            diagnosis TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            predicted_class TEXT NOT NULL,
            confidence REAL NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def insert_sample(timestamp, values):
    conn = _connect()
    cursor = conn.cursor()

    placeholders = ",".join(["?"] * (NUM_CHANNELS + 1))
    cursor.execute(
        f"INSERT INTO neural_data VALUES ({placeholders})",
        [timestamp] + values
    )

    conn.commit()
    conn.close()


def get_latest_samples(limit=500):
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM neural_data ORDER BY timestamp DESC LIMIT ?",
        (int(limit),)
    )

    rows = cursor.fetchall()
    conn.close()
    return rows[::-1]  # oldest -> newest


# ---------------------------
# EVENT LOGGING
# ---------------------------

def insert_event(start_ts, end_ts, duration_s, channel, status, reasons, diagnosis):
    """
    Insert event (can be OPEN: end_ts=None, duration_s=None)
    reasons should be JSON string or list[str]
    """
    conn = _connect()
    cursor = conn.cursor()

    if isinstance(reasons, list):
        reasons = json.dumps(reasons)

    cursor.execute("""
        INSERT INTO events (start_ts, end_ts, duration_s, channel, status, reasons, diagnosis)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        float(start_ts),
        None if end_ts is None else float(end_ts),
        None if duration_s is None else float(duration_s),
        int(channel),
        str(status),
        str(reasons),
        str(diagnosis),
    ))

    conn.commit()
    conn.close()


def close_open_event(channel, end_ts):
    """
    Close the most recent OPEN event for a channel.
    """
    conn = _connect()
    cursor = conn.cursor()

    # find most recent open event
    cursor.execute("""
        SELECT id, start_ts
        FROM events
        WHERE channel = ? AND end_ts IS NULL
        ORDER BY id DESC
        LIMIT 1
    """, (int(channel),))

    row = cursor.fetchone()
    if row is None:
        conn.close()
        return False

    event_id, start_ts = row
    duration_s = max(0.0, float(end_ts) - float(start_ts))

    cursor.execute("""
        UPDATE events
        SET end_ts = ?, duration_s = ?
        WHERE id = ?
    """, (float(end_ts), float(duration_s), int(event_id)))

    conn.commit()
    conn.close()
    return True


def get_events(limit=200):
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, start_ts, end_ts, duration_s, channel, status, reasons, diagnosis
        FROM events
        ORDER BY id DESC
        LIMIT ?
    """, (int(limit),))

    rows = cursor.fetchall()
    conn.close()

    events = []
    for r in rows:
        events.append({
            "id": r[0],
            "start_ts": r[1],
            "end_ts": r[2],
            "duration_s": r[3],
            "channel": r[4],
            "status": r[5],
            "reasons": json.loads(r[6]) if r[6] else [],
            "diagnosis": r[7],
        })
    return events


def clear_events():
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM events")
    conn.commit()
    conn.close()


def insert_prediction(timestamp, predicted_class, confidence):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO predictions (timestamp, predicted_class, confidence)
        VALUES (?, ?, ?)
    """, (
        float(timestamp),
        str(predicted_class),
        float(confidence),
    ))
    conn.commit()
    conn.close()


def get_latest_prediction():
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, timestamp, predicted_class, confidence
        FROM predictions
        ORDER BY id DESC
        LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    return {
        "id": row[0],
        "timestamp": row[1],
        "predicted_class": row[2],
        "confidence": row[3],
    }
