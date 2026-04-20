from __future__ import annotations

import threading
from collections import deque
from typing import Dict, Iterable, List, Optional, Tuple

import mne
import numpy as np
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import db
from config import (
    DATA_SOURCE,
    DECODER_CLASSES,
    DECODER_ENABLED,
    DECODER_STEP_SECONDS,
    DECODER_TMAX_SECONDS,
    DECODER_TMIN_SECONDS,
    DECODER_WINDOW_SECONDS,
)

CLASS_ALIASES = {
    "left_hand": {"left_hand", "left hand", "769", "left"},
    "right_hand": {"right_hand", "right hand", "770", "right"},
}


def _canonical_label(label: str) -> Optional[str]:
    normalized = str(label).strip().lower().replace("-", "_")
    for canonical, aliases in CLASS_ALIASES.items():
        if normalized in aliases:
            return canonical
    return None


def _bandpower(signal: np.ndarray, fs: int, low: float, high: float) -> float:
    sig = np.asarray(signal, dtype=np.float64)
    if sig.size < 4:
        return 0.0

    sig = sig - np.mean(sig)
    spectrum = np.fft.rfft(sig)
    freqs = np.fft.rfftfreq(sig.size, d=1.0 / float(fs))
    power = (np.abs(spectrum) ** 2) / max(sig.size, 1)
    mask = (freqs >= low) & (freqs < high)
    if not np.any(mask):
        return 0.0
    return float(np.mean(power[mask]))


def compute_window_features(window: np.ndarray, fs: int) -> np.ndarray:
    """
    window shape: (samples, channels)
    Features are flattened per channel and kept intentionally simple:
    alpha power, beta power, RMS, variance, and log total power.
    """
    X = np.asarray(window, dtype=np.float64)
    if X.ndim != 2:
        raise ValueError("Expected window with shape (samples, channels).")

    features: List[float] = []
    for channel in range(X.shape[1]):
        sig = X[:, channel]
        alpha = _bandpower(sig, fs=fs, low=8.0, high=12.0)
        beta = _bandpower(sig, fs=fs, low=13.0, high=30.0)
        rms = float(np.sqrt(np.mean(sig ** 2)))
        var = float(np.var(sig))
        total_power = _bandpower(sig, fs=fs, low=1.0, high=min(40.0, fs / 2.0 - 1.0))
        log_power = float(np.log(total_power + 1e-8))
        features.extend([alpha, beta, rms, var, log_power])
    return np.array(features, dtype=np.float64)


def _annotation_mapping(raw: mne.io.BaseRaw) -> Tuple[Dict[str, int], Dict[int, str]]:
    event_id: Dict[str, int] = {}
    label_by_id: Dict[int, str] = {}
    for desc in raw.annotations.description:
        canonical = _canonical_label(desc)
        if canonical in DECODER_CLASSES and desc not in event_id:
            code = len(event_id) + 1
            event_id[str(desc)] = code
            label_by_id[code] = canonical
    return event_id, label_by_id


def _training_examples_from_raw(raw: mne.io.BaseRaw) -> Tuple[np.ndarray, np.ndarray]:
    event_id, label_by_id = _annotation_mapping(raw)
    if len(label_by_id) < 2:
        raise RuntimeError(
            "Decoder training requires at least left/right motor imagery annotations in the replay dataset."
        )

    events, _ = mne.events_from_annotations(raw, event_id=event_id, verbose=False)
    if len(events) == 0:
        raise RuntimeError("No decoder events were found in replay annotations.")

    epochs = mne.Epochs(
        raw,
        events,
        event_id=event_id,
        tmin=DECODER_TMIN_SECONDS,
        tmax=DECODER_TMAX_SECONDS,
        baseline=None,
        preload=True,
        verbose=False,
    )

    X_list: List[np.ndarray] = []
    y_list: List[str] = []
    fs = int(round(float(raw.info["sfreq"])))

    for epoch, event in zip(epochs.get_data(copy=True), epochs.events):
        # epoch shape from MNE is (channels, samples); convert to (samples, channels)
        features = compute_window_features(epoch.T, fs=fs)
        X_list.append(features)
        y_list.append(label_by_id[event[2]])

    return np.vstack(X_list), np.array(y_list)


def train_decoder_from_raw(raw: mne.io.BaseRaw) -> Pipeline:
    X, y = _training_examples_from_raw(raw)
    model = Pipeline(
        [
            ("scale", StandardScaler()),
            ("clf", LinearDiscriminantAnalysis()),
        ]
    )
    model.fit(X, y)
    return model


class RollingWindowDecoder:
    """
    Lightweight streaming decoder.

    Design:
    - Train one baseline left-vs-right classifier offline from the replay raw.
    - Receive live samples through `add_sample()` from the existing stream loop.
    - Maintain a rolling buffer and emit one prediction every configured step.
    - Persist each prediction so `/prediction` and future analysis use the same source of truth.
    """

    def __init__(self):
        self.enabled = DECODER_ENABLED and DATA_SOURCE == "replay"
        self.model: Optional[Pipeline] = None
        self.sample_rate_hertz: Optional[int] = None
        self.window_samples: Optional[int] = None
        self.step_samples: Optional[int] = None
        self.samples = deque()
        self.timestamps = deque()
        self.last_prediction: Optional[Dict[str, float]] = None
        self.total_samples_seen = 0
        self.next_emit_sample = 0
        self.lock = threading.Lock()
        self.training_error: Optional[str] = None
        self.classes = list(DECODER_CLASSES)

    def configure_from_raw(self, raw: mne.io.BaseRaw):
        if not self.enabled:
            return

        fs = int(round(float(raw.info["sfreq"])))
        with self.lock:
            self.model = train_decoder_from_raw(raw)
            self.sample_rate_hertz = fs
            self.window_samples = max(1, int(round(DECODER_WINDOW_SECONDS * fs)))
            self.step_samples = max(1, int(round(DECODER_STEP_SECONDS * fs)))
            self.samples.clear()
            self.timestamps.clear()
            self.total_samples_seen = 0
            self.next_emit_sample = self.window_samples
            self.training_error = None

    def set_unavailable(self, reason: str):
        with self.lock:
            self.training_error = reason
            self.model = None

    def add_sample(self, timestamp: float, values: Iterable[float]):
        if not self.enabled:
            return

        with self.lock:
            if self.model is None or self.window_samples is None or self.step_samples is None:
                return

            sample = np.asarray(list(values), dtype=np.float64)
            self.samples.append(sample)
            self.timestamps.append(float(timestamp))
            self.total_samples_seen += 1

            while len(self.samples) > self.window_samples:
                self.samples.popleft()
                self.timestamps.popleft()

            if self.total_samples_seen < self.next_emit_sample or len(self.samples) < self.window_samples:
                return

            window = np.vstack(self.samples)
            features = compute_window_features(window, fs=self.sample_rate_hertz)
            probabilities = self.model.predict_proba(features.reshape(1, -1))[0]
            classes = list(self.model.classes_)
            best_idx = int(np.argmax(probabilities))
            prediction = {
                "timestamp": self.timestamps[-1],
                "predicted_class": str(classes[best_idx]),
                "confidence": float(probabilities[best_idx]),
            }
            self.last_prediction = prediction
            self.next_emit_sample += self.step_samples

        db.insert_prediction(
            timestamp=prediction["timestamp"],
            predicted_class=prediction["predicted_class"],
            confidence=prediction["confidence"],
        )

    def get_latest_prediction(self) -> Dict[str, object]:
        with self.lock:
            if not self.enabled:
                return {
                    "available": False,
                    "reason": "decoder disabled for current data source",
                }

            if self.training_error is not None:
                return {
                    "available": False,
                    "reason": self.training_error,
                }

            if self.last_prediction is None:
                return {
                    "available": False,
                    "reason": "no prediction yet",
                }

            return {
                "available": True,
                "prediction": dict(self.last_prediction),
            }
