SAMPLE_RATE_HERTZ = 256 # samples/sec our "neural device" produces
NUM_CHANNELS = 4 # num of simualted EEG channels
DB_PATH = "neurostream.db" # path to SQLite database file
BUFFER_SIZE = 500 # how many recent samples returned by API for visualization

ARTIFACT_CHANGE_PER_SEC = 0.35
ARTIFACT_MIN_SEC = 0.4
ARTIFACT_MAX_SEC = 1.8

# probabilities for artifact types
P_DROPOUT = 0.4
P_SPIKE = 0.3
P_LINE_NOISE = 0.2
P_SATURATION = 0.1 # optional
