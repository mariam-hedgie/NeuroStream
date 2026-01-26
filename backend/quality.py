from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Optional

import numpy as np


@dataclass
class ChannelQuality:
    rms: float
    peak_to_peak: float
    dropout_frac: float
    line_noise_ratio: float
    status: str
    reasons: List[str]


def _safe_array(x: List[float]) -> np.ndarray:
    arr = np.array(x, dtype=np.float64)
    return arr


def _line_noise_ratio(signal: np.ndarray, fs: int, line_freq: int = 60, bandwidth_hz: float = 1.0) -> float:
    """
    Ratio of power around line frequency (e.g., 60Hz ± 1Hz) to total power.
    Uses rFFT for speed.
    """
    n = signal.size
    if n < 8:
        return 0.0

    # Remove DC to avoid total power being dominated by mean offset
    sig = signal - np.mean(signal)

    # rFFT frequencies
    fft_vals = np.fft.rfft(sig)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    power = (np.abs(fft_vals) ** 2)

    total_power = float(np.sum(power)) + 1e-12  # avoid divide-by-zero

    low = line_freq - bandwidth_hz
    high = line_freq + bandwidth_hz
    mask = (freqs >= low) & (freqs <= high)

    line_power = float(np.sum(power[mask]))
    return float(line_power / total_power)


def compute_quality(
    samples: List[Dict[str, Any]],
    fs: int = 256,
    line_freq: int = 60,
    window_seconds: float = 2.0,
) -> Dict[str, Any]:
    """
    samples: list of {"timestamp": float, "channels": [c0, c1, ...]}
    Returns a JSON-serializable dict: metrics + status per channel.
    """
    if not samples:
        return {
            "fs": fs,
            "window_seconds": window_seconds,
            "num_channels": 0,
            "num_samples": 0,
            "channels": [],
            "overall": {"status": "bad", "summary": "no data"},
        }

    num_channels = len(samples[0]["channels"])
    needed = int(fs * window_seconds)
    window = samples[-needed:] if len(samples) >= needed else samples

    # Build matrix: shape (T, C)
    X = np.zeros((len(window), num_channels), dtype=np.float64)
    dropout_mask = np.zeros((len(window), num_channels), dtype=bool)

    for i, row in enumerate(window):
        ch = row.get("channels", [])
        for c in range(num_channels):
            v = ch[c] if c < len(ch) else None
            if v is None or (isinstance(v, float) and np.isnan(v)):
                dropout_mask[i, c] = True
                X[i, c] = 0.0
            else:
                # Treat exact zeros as dropout only if you want to.
                # Here we count exact zeros as potential dropout because real signals rarely sit at exact 0.
                if v == 0.0:
                    dropout_mask[i, c] = True
                X[i, c] = float(v)

    results: List[Dict[str, Any]] = []
    statuses = []

    # Thresholds (tuneable — keep them simple + explainable)
    # These assume your sim produces values roughly around ~[-1, 1] range.
    RMS_FLATLINE = 0.03        # too small => likely disconnected / flat
    P2P_CLIP = 4.0             # too large => likely clipping/out-of-range
    DROPOUT_BAD = 0.20         # >20% missing/zeros is bad
    DROPOUT_DEGRADED = 0.05    # >5% degraded
    LINE_BAD = 0.25            # line noise dominates
    LINE_DEGRADED = 0.10

    for c in range(num_channels):
        sig = X[:, c]
        rms = float(np.sqrt(np.mean(sig ** 2)))
        p2p = float(np.max(sig) - np.min(sig))
        dropout_frac = float(np.mean(dropout_mask[:, c]))
        lnr = _line_noise_ratio(sig, fs=fs, line_freq=line_freq, bandwidth_hz=1.0)

        reasons: List[str] = []
        status = "good"

        # Rules: escalate status if conditions worsen
        if rms < RMS_FLATLINE:
            status = "bad"
            reasons.append("flatline_rms_low")

        if p2p > P2P_CLIP:
            status = "bad"
            reasons.append("clipping_peak_to_peak_high")

        if dropout_frac > DROPOUT_BAD:
            status = "bad"
            reasons.append("dropout_high")
        elif dropout_frac > DROPOUT_DEGRADED and status != "bad":
            status = "degraded"
            reasons.append("dropout_moderate")

        if lnr > LINE_BAD:
            status = "bad"
            reasons.append("line_noise_high")
        elif lnr > LINE_DEGRADED and status != "bad":
            status = "degraded"
            reasons.append("line_noise_moderate")

        results.append({
            "channel": c,
            "rms": rms,
            "peak_to_peak": p2p,
            "dropout_frac": dropout_frac,
            "line_noise_ratio": lnr,
            "status": status,
            "reasons": reasons,
        })
        statuses.append(status)

    # Overall summary
    if "bad" in statuses:
        overall = "bad"
    elif "degraded" in statuses:
        overall = "degraded"
    else:
        overall = "good"

    return {
        "fs": fs,
        "window_seconds": window_seconds,
        "num_channels": num_channels,
        "num_samples": len(window),
        "channels": results,
        "overall": {
            "status": overall,
            "summary": f"{statuses.count('bad')} bad, {statuses.count('degraded')} degraded, {statuses.count('good')} good",
        },
    }