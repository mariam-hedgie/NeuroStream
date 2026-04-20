import threading
import time
from typing import Any, Iterable, Optional

import mne
import numpy as np

from config import (
    NUM_CHANNELS,
    REPLAY_CHANNEL_NAMES,
    REPLAY_CHUNK_SIZE,
    REPLAY_DATASET,
    REPLAY_LOOP,
    REPLAY_RUN,
    REPLAY_SESSION,
    REPLAY_STREAM_NAME,
    REPLAY_SUBJECT,
    REPLAY_USE_LSL,
)
from db import insert_sample

try:
    from moabb.datasets import BNCI2014_001
except ImportError:  # pragma: no cover - dependency guard
    BNCI2014_001 = None

try:
    from mne_lsl.player import PlayerLSL
except ImportError:  # pragma: no cover - optional runtime integration
    PlayerLSL = None


def _pick_nth_key(mapping, index: int):
    keys = list(mapping.keys())
    if not keys:
        raise RuntimeError("Replay dataset did not contain any entries.")
    if index < 0 or index >= len(keys):
        raise RuntimeError(f"Requested index {index} out of range for keys: {keys}")
    return keys[index]


def _find_first_raw(node: Any) -> mne.io.BaseRaw:
    """
    MOABB returns nested subject/session/run dictionaries. Walk the structure
    conservatively so the replay loader stays resilient to small API changes.
    """
    if isinstance(node, mne.io.BaseRaw):
        return node

    if isinstance(node, dict):
        for value in node.values():
            try:
                return _find_first_raw(value)
            except RuntimeError:
                continue

    if isinstance(node, (list, tuple)):
        for value in node:
            try:
                return _find_first_raw(value)
            except RuntimeError:
                continue

    raise RuntimeError("Could not locate an MNE Raw object inside the dataset payload.")


def _load_bnci2014_001_raw(subject: int, session_index: int, run_index: int) -> mne.io.BaseRaw:
    if BNCI2014_001 is None:
        raise RuntimeError(
            "Replay mode requires MOABB. Install dependencies from backend/requirements.txt."
        )

    dataset = BNCI2014_001()
    payload = dataset.get_data(subjects=[subject])

    if subject not in payload:
        raise RuntimeError(f"Subject {subject} not found in replay dataset.")

    subject_payload = payload[subject]
    if not isinstance(subject_payload, dict):
        return _find_first_raw(subject_payload)

    session_key = _pick_nth_key(subject_payload, session_index)
    session_payload = subject_payload[session_key]

    if isinstance(session_payload, dict):
        run_key = _pick_nth_key(session_payload, run_index)
        return _find_first_raw(session_payload[run_key])

    return _find_first_raw(session_payload)


def _select_dashboard_channels(raw: mne.io.BaseRaw, requested_names: Iterable[str]) -> mne.io.BaseRaw:
    eeg_names = [raw.ch_names[i] for i in mne.pick_types(raw.info, eeg=True, exclude="bads")]
    selected = [name for name in requested_names if name in eeg_names]

    if len(selected) < NUM_CHANNELS:
        for name in eeg_names:
            if name not in selected:
                selected.append(name)
            if len(selected) == NUM_CHANNELS:
                break

    if len(selected) < NUM_CHANNELS:
        raise RuntimeError(
            f"Replay dataset only exposed {len(selected)} EEG channels after selection."
        )

    return raw.copy().pick(selected[:NUM_CHANNELS])


def _prepare_replay_raw() -> mne.io.BaseRaw:
    """
    Load one dataset recording and reduce it to the 4 EEG channels used by the
    existing dashboard/DB contract.
    """
    if REPLAY_DATASET != "BNCI2014_001":
        raise RuntimeError(f"Unsupported replay dataset: {REPLAY_DATASET}")

    raw = _load_bnci2014_001_raw(
        subject=REPLAY_SUBJECT,
        session_index=REPLAY_SESSION,
        run_index=REPLAY_RUN,
    )

    # Preload once so timed replay is just slicing arrays, not doing I/O in the loop.
    raw = raw.copy().load_data()
    raw = _select_dashboard_channels(raw, REPLAY_CHANNEL_NAMES)
    raw = _normalize_for_dashboard(raw)
    return raw


def _normalize_for_dashboard(raw: mne.io.BaseRaw) -> mne.io.BaseRaw:
    """
    Replay data arrives in physical EEG units (typically volts), while the
    existing quality heuristics were tuned for the synthetic source's roughly
    unit-scale amplitudes. Apply one conservative global scale factor so the
    legacy monitoring pipeline remains usable without changing DB schema or
    threshold logic in this step.
    """
    data = raw.get_data()
    scale = float(np.percentile(np.abs(data), 95))
    if scale <= 1e-12:
        return raw

    raw._data = raw._data / scale
    return raw


def build_lsl_player_if_enabled(raw: mne.io.BaseRaw):
    """
    Optional MNE-LSL hook for future external consumers.
    The current Flask app still writes replayed samples directly into SQLite.
    """
    if not REPLAY_USE_LSL:
        return None

    if PlayerLSL is None:
        raise RuntimeError(
            "REPLAY_USE_LSL is enabled but mne-lsl is not installed."
        )

    return PlayerLSL(raw, chunk_size=REPLAY_CHUNK_SIZE, n_repeat=0, name=REPLAY_STREAM_NAME)


class ReplayDataSource:
    """
    Near-real-time replay source backed by an MNE Raw object.

    Architecture:
    - MOABB provides a public motor-imagery dataset recording.
    - MNE loads one Raw run and trims it to 4 EEG channels.
    - This class emits timed chunks into the existing SQLite insertion path so
      `/latest`, `/quality`, and incident monitoring keep working unchanged.
    - MNE-LSL support is prepared via `build_lsl_player_if_enabled()`, but the
      first integration keeps the app simple by replaying directly from Raw.
    """

    def __init__(self):
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.raw: Optional[mne.io.BaseRaw] = None
        self.sample_rate_hertz: Optional[int] = None
        self.channel_names = []
        self.lsl_player = None

    def _ensure_loaded(self):
        if self.raw is not None:
            return

        raw = _prepare_replay_raw()
        self.raw = raw
        self.sample_rate_hertz = int(round(float(raw.info["sfreq"])))
        self.channel_names = list(raw.ch_names)
        self.lsl_player = build_lsl_player_if_enabled(raw)

    def _run_loop(self):
        self._ensure_loaded()
        assert self.raw is not None
        assert self.sample_rate_hertz is not None

        data = self.raw.get_data()
        total_samples = data.shape[1]
        chunk_size = max(1, int(REPLAY_CHUNK_SIZE))
        sample_period = 1.0 / float(self.sample_rate_hertz)
        cursor = 0

        while self.running:
            if cursor >= total_samples:
                if REPLAY_LOOP:
                    cursor = 0
                else:
                    break

            stop = min(cursor + chunk_size, total_samples)
            chunk = data[:, cursor:stop].T
            chunk_start = time.time()

            # Preserve the downstream contract: one DB row per timestamped sample.
            for offset, sample in enumerate(chunk):
                insert_sample(chunk_start + (offset * sample_period), sample.tolist())

            cursor = stop
            sleep_for = len(chunk) * sample_period
            time.sleep(max(0.0, sleep_for))

        self.running = False

    def start(self):
        if self.thread is not None and self.thread.is_alive():
            return

        self._ensure_loaded()
        if self.lsl_player is not None and not self.lsl_player.running:
            self.lsl_player.start()

        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=0.5)
        if self.lsl_player is not None and self.lsl_player.running:
            self.lsl_player.stop()
