import time
import math
import random
import threading

from config import SAMPLE_RATE_HERTZ, NUM_CHANNELS
from config import (
    ARTIFACT_CHANGE_PER_SEC, ARTIFACT_MIN_SEC, ARTIFACT_MAX_SEC,
    P_DROPOUT, P_SPIKE, P_LINE_NOISE, P_SATURATION, P_FLATLINE
)
from db import insert_sample


class NeuralDataSimulator:
    """
    Simulates a multichannel neural acquisition device.
    Runs continuously in a background thread and writes samples to the database.
    """

    def __init__(self):

        self.t0 = None
        self.running = False # flag
        self.thread = None

        # give each channel slightly different frequency and phase 
        self.freqs = [10 + i * 2 for i in range(NUM_CHANNELS)]   # e.g., 10, 12, 14, 16 Hz
        self.phases = [random.uniform(0, 2 * math.pi) for _ in range(NUM_CHANNELS)] # makes random phase offset

        self.artifacts = [None] * NUM_CHANNELS
        self.global_line_noise = None

    def _generate_sample(self, t):
        """
        One sample = one timestamp worth of values for all channels.
        """
        # possibly start an artifact event
        self._maybe_start_artifacts(t)

        values = []
        for ch in range(NUM_CHANNELS):
            # base oscillation per channel + gaussian noise
            signal = math.sin(2 * math.pi * self.freqs[ch] * t + self.phases[ch])
            noise = random.gauss(0, 0.15)
            v = signal + noise

            # apply per-channel artifact if active
            a = self.artifacts[ch]
            if a is not None:
                if a["type"] == "dropout":
                    v = 0.0
                elif a["type"] == "spike":
                    # spike should be brief: only hit occasionally during the window
                    if random.random() < 0.05:  # ~5% of samples during spike window
                        v += a["amp"] * (1.0 if random.random() < 0.5 else -1.0)
                elif a["type"] == "saturation":
                    # clip to rails
                    rail = a["rail"]
                    v = max(-rail, min(rail, v))
                elif a["type"] == "flatline":
                    v = a["level"] + random.gauss(0,0.003)

            values.append(v)

        # apply global line noise if active (affects all channels)
        if self.global_line_noise is not None:
            ln = self.global_line_noise
            hum = ln["amp"] * math.sin(2 * math.pi * 60.0 * t)
            values = [v + hum for v in values]

        # cleanup expired artifacts after generating
        self._cleanup_artifacts(t)

        return values


    def _run_loop(self):
        """
        Runs at approximately SAMPLE_RATE_HZ.
        """
        dt = 1.0 / SAMPLE_RATE_HERTZ

        while self.running:
            t_now = time.time()
            t = t_now - self.t0 # elapsed seconds since start
            sample = self._generate_sample(t) # save real sample in DB

            # store one row of timestamp + channel values 
            insert_sample(t_now, sample)

            # sleep to match sampling rate
            time.sleep(dt) # waits until next sample

    def start(self):
        if self.thread is not None and self.thread.is_alive():
            return  # already running

        self.t0 = time.time()
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        # wait briefly for thread to exit
        if self.thread is not None: 
            self.thread.join(timeout=0.2)

    def _maybe_start_artifacts(self, t):
        """
        Randomly start an artifact event.
        Can affect 1 channel or multiple channels.
        Also can start a global line-noise event.
        """
        # chance per sample derived from per-second chance
        p_per_sample = ARTIFACT_CHANGE_PER_SEC / SAMPLE_RATE_HERTZ
        if random.random() > p_per_sample:
            return

        dur = random.uniform(ARTIFACT_MIN_SEC, ARTIFACT_MAX_SEC)
        end_t = t + dur

        r = random.random()

        p1 = P_DROPOUT
        p2 = p1 + P_SPIKE
        p3 = p2 + P_LINE_NOISE
        p4 = p3 + P_SATURATION
        p5 = p4 + P_FLATLINE  # should end at 1.0

        if r < p1:
            self._start_dropout(end_t)
        elif r < p2:
            self._start_spike(end_t)
        elif r < p3:
            self._start_line_noise(end_t)
        elif r < p4:
            self._start_saturation(end_t)
        elif r < p5:
            self._start_flatline(end_t)


    def _start_dropout(self, end_t):
        """
        Dropout: flatline. Randomly choose 1..N channels.
        """
        # pick how many channels drop out (bias toward 1)
        k = 1 if random.random() < 0.70 else random.randint(2, NUM_CHANNELS)
        chs = random.sample(range(NUM_CHANNELS), k)

        for ch in chs:
            self.artifacts[ch] = {"type": "dropout", "end_t": end_t}


    def _start_spike(self, end_t):
        """
        Spike: sharp transient, usually 1 channel.
        """
        ch = random.randrange(NUM_CHANNELS)
        amp = random.uniform(1.5, 3.5)
        self.artifacts[ch] = {"type": "spike", "end_t": end_t, "amp": amp}


    def _start_line_noise(self, end_t):
        """
        Line noise: typically affects all channels together.
        """
        amp = random.uniform(0.05, 0.25)
        self.global_line_noise = {"end_t": end_t, "amp": amp}


    def _start_saturation(self, end_t):
        """
        Saturation/clipping: 1 channel hits rails.
        """
        ch = random.randrange(NUM_CHANNELS)
        rail = random.uniform(0.6, 1.2)
        self.artifacts[ch] = {"type": "saturation", "end_t": end_t, "rail": rail}

    def _start_flatline(self, end_t):
        """
        Flatline: constant value with tiny jitter.
        Often looks like disconnected electrode but not necessarily zero.
        """
        ch = random.randrange(NUM_CHANNELS)
        level = random.uniform(-0.05, 0.05)
        self.artifacts[ch] = {"type": "flatline", "end_t": end_t, "level": level}


    def _cleanup_artifacts(self, t):
        """
        Remove expired artifacts.
        """
        for ch in range(NUM_CHANNELS):
            a = self.artifacts[ch]
            if a is not None and t >= a["end_t"]:
                self.artifacts[ch] = None

        if self.global_line_noise is not None and t >= self.global_line_noise["end_t"]:
            self.global_line_noise = None