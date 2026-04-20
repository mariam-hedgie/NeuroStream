DATA_SOURCE = "replay"  # "simulator" | "replay"

SAMPLE_RATE_HERTZ = 256 # samples/sec our "neural device" produces
NUM_CHANNELS = 4 # num of simualted EEG channels
DB_PATH = "neurostream.db" # path to SQLite database file
BUFFER_SIZE = 500 # how many recent samples returned by API for visualization

# Replay source defaults. Keep the dashboard at 4 channels for compatibility.
REPLAY_DATASET = "BNCI2014_001"
REPLAY_SUBJECT = 1
REPLAY_SESSION = 0
REPLAY_RUN = 0
REPLAY_CHANNEL_NAMES = ["C3", "Cz", "C4", "Pz"]
REPLAY_CHUNK_SIZE = 16
REPLAY_LOOP = True
REPLAY_USE_LSL = False
REPLAY_STREAM_NAME = "NeuroStreamReplay"

DECODER_ENABLED = True
DECODER_WINDOW_SECONDS = 1.0
DECODER_STEP_SECONDS = 0.5
DECODER_TMIN_SECONDS = 0.5
DECODER_TMAX_SECONDS = 3.5
DECODER_CLASSES = ["left_hand", "right_hand"]

ARTIFACT_CHANGE_PER_SEC = 0.35
ARTIFACT_MIN_SEC = 0.4
ARTIFACT_MAX_SEC = 1.8

# probabilities for artifact types
P_DROPOUT = 0.35
P_SPIKE = 0.25
P_LINE_NOISE = 0.20
P_SATURATION = 0.10
P_FLATLINE = 0.10
