'''
creates and manages a lightweight database that stores time-stamped 
multichannel neural samples. provides ordered retreival for visualization
and analysis.
'''

import sqlite3
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