'''
creates and manages a lightweight database that stores time-stamped 
multichannel neural samples. provides ordered retreival for visualization
and analysis.
'''

import sqlite3
import json
from config import DB_PATH, NUM_CHANNELS

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor() # create cursor object

    # build dynamic SQL for channel columns
    channel_cols = ", ".join([f"ch{i} REAL" for i in range(NUM_CHANNELS)])

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS neural_data (
            timestamp REAL,
            {channel_cols}
        )
    """)

    # events table: stroes detected signal-quality incidents
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_ts REAL NOT NULL,
            end_ts REAL,                -- NULL while event is open
            duration_s REAL,            -- NULL while event is open
            channel INTEGER NOT NULL,
            status TEXT NOT NULL,       -- degraded/bad
            reasons TEXT NOT NULL,      -- JSON list
            diagnosis TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()

# takes a sample and saves it into the database
# simulates logging continuous neural aquistition into persistent storage
def insert_sample(timestamp, values):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    placeholders = ",".join(["?"] * (NUM_CHANNELS + 1))
    cursor.execute(
        f"INSERT INTO neural_data VALUES ({placeholders})",
        [timestamp] + values
    )

    conn.commit()
    conn.close()

# fetches most recent data for visualization/analysis
# returns ordered time series data
def get_latest_samples(limit=500): # 500 samples
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM neural_data ORDER BY timestamp DESC LIMIT ?",
        (limit,)
    )

    rows = cursor.fetchall()
    conn.close()

    return rows[::-1]  # reverse so oldest to newest

# event logging of incidents
def insert_event(start_ts, end_ts, duration_s, channel, status, reasons, diagnosis):
    """
    Insert an event.
    For open events: end_ts=None, duration_s=None
    reasons is expected to already be a JSON string OR a list[str].
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # normalize reasons into JSON text
    if isinstance(reasons, str):
        reasons_json = reasons
    else:
        reasons_json = json.dumps(list(reasons))

    cursor.execute("""
        INSERT INTO events (start_ts, end_ts, duration_s, channel, status, reasons, diagnosis)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        float(start_ts),
        None if end_ts is None else float(end_ts),
        None if duration_s is None else float(duration_s),
        int(channel),
        str(status),
        reasons_json,
        str(diagnosis),
    ))

    conn.commit()
    conn.close()

def close_open_event(channel, end_ts):
    """
    Close the most recent open event for a channel (end_ts is NULL).
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # find most recent open event for this channel
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
        return

    event_id, start_ts = row
    duration_s = max(0.0, float(end_ts) - float(start_ts))

    cursor.execute("""
        UPDATE events
        SET end_ts = ?, duration_s = ?
        WHERE id = ?
    """, (float(end_ts), float(duration_s), int(event_id)))

    conn.commit()
    conn.close()


def get_events(limit=200):
    """
    Return latest events (most recent first).
    """
    conn = sqlite3.connect(DB_PATH)
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
    """
    Clear all logged events.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM events")
    conn.commit()
    conn.close()