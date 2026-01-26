import time
import math
import random
import threading

from config import SAMPLE_RATE_HERTZ, NUM_CHANNELS
from db import insert_sample


class NeuralDataSimulator:
    """
    Simulates a multichannel neural acquisition device.
    Runs continuously in a background thread and writes samples to the database.
    """

    def __init__(self):
        self.running = False # flag
        self.thread = None

        # give each channel slightly different frequency and phase 
        self.freqs = [10 + i * 2 for i in range(NUM_CHANNELS)]   # e.g., 10, 12, 14, 16 Hz
        self.phases = [random.uniform(0, 2 * math.pi) for _ in range(NUM_CHANNELS)] # makes random phase offset

    def _generate_sample(self, t):
        """
        Generate one sample across NUM_CHANNELS at time t.
        Signal = sine wave + random noise (EEG-ish).
        """
        values = []
        for ch in range(NUM_CHANNELS): # one number per channel
            signal = math.sin(2 * math.pi * self.freqs[ch] * t + self.phases[ch])
            noise = random.gauss(0, 0.15)  # adds gaussian noise to make it realistic
            values.append(signal + noise)
        return values # multi channel values

    def _run_loop(self):
        """
        Runs at approximately SAMPLE_RATE_HZ.
        """
        dt = 1.0 / SAMPLE_RATE_HERTZ

        while self.running:
            t_now = time.time()
            sample = self._generate_sample(t_now)

            # store one row of timestamp + channel values 
            insert_sample(t_now, sample)

            # sleep to match sampling rate
            time.sleep(dt) # waits until next sample

    def start(self):
        """
        Start the simulator in a background thread.
        """
        if self.running:
            return  # already running

        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """
        Stop simulator loop.
        """
        self.running = False