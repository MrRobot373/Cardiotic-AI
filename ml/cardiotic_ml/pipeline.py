"""End-to-end analysis of one single-lead recording — what the review screen shows.

quality gate -> beat detection -> beat classification -> measurements -> findings.
Segments the quality model marks *unusable* produce no beats and no findings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import torch

from cardiotic_ml import __version__, dsp, qrs
from cardiotic_ml.beats import dataset as beat_data
from cardiotic_ml.beats.model import BeatNet
from cardiotic_ml.paths import ARTIFACTS_DIR
from cardiotic_ml.quality import dataset as q_data
from cardiotic_ml.quality.model import QualityNet

FS = 360
# Best detector on the MIT-BIH benchmark (reports/qrs_detection.json).
QRS_METHOD = "pantompkins1985"
# Beat model version used by the pipeline — chosen on validation patients, never on the test set.
BEAT_MODEL = "beat_net_v0.1"  # v0.2 (augmentation) scored lower on validation patients


@dataclass
class Models:
    quality: QualityNet
    beats: BeatNet
    cards: dict


def load_models(directory=ARTIFACTS_DIR) -> Models:
    q, b = QualityNet(len(q_data.LABELS)), BeatNet(len(beat_data.CLASSES))
    q.load_state_dict(torch.load(directory / "quality_net.pt", weights_only=True))
    b.load_state_dict(torch.load(directory / f"{BEAT_MODEL}.pt", weights_only=True))
    q.eval(); b.eval()
    cards = {n: json.loads((directory / f"{n}.card.json").read_text()) for n in ("quality_net", BEAT_MODEL)}
    return Models(q, b, cards)


def confidence_level(p: float) -> str:
    # Uncalibrated bins for the research build. Calibration on a locked set comes before any UI use.
    return "high" if p >= 0.9 else "moderate" if p >= 0.7 else "low"


@torch.no_grad()
def analyze(signal: np.ndarray, fs: float, models: Models) -> dict:
    x = dsp.resample(np.asarray(signal, dtype=np.float32), fs, FS)
    win = q_data.WIN
    # 1. quality, per 2.5 s window
    starts = np.arange(0, max(len(x) - win, 0) + 1, win)
    wins = np.stack([x[s:s + win] - np.median(x[s:s + win]) for s in starts]) if len(starts) else np.zeros((0, win))
    qp = torch.softmax(models.quality(torch.from_numpy(np.clip(wins, -10, 10).astype(np.float32))), 1).numpy()
    q_label = qp.argmax(1)
    segments = [{"start_s": float(s / FS), "end_s": float((s + win) / FS), "quality": q_data.LABELS[l],
                 "probability": float(qp[i, l])} for i, (s, l) in enumerate(zip(starts, q_label))]
    usable = np.zeros(len(x), dtype=bool)
    for s, l in zip(starts, q_label):
        usable[s:s + win] = l != 2
    if len(starts) == 0 or usable.mean() < 0.5:
        return _result(segments, [], {}, ["Not analysable: less than half the recording has usable signal quality."], models)
    # 2. beats, only inside usable windows
    peaks = qrs.detect_beats(x, FS, QRS_METHOD)
    peaks = peaks[usable[peaks]]
    if len(peaks) < 3:
        return _result(segments, [], {}, ["Not analysable: too few beats detected in usable segments."], models)
    # 3. classify
    bw, rr, ok = beat_data.from_signal(x, peaks, FS)
    bp = torch.softmax(models.beats(torch.from_numpy(bw), torch.from_numpy(rr)), 1).numpy()
    beats = [{"time_s": float(p / FS), "class": beat_data.CLASSES[c], "probability": float(bp[i, c]),
              "confidence": confidence_level(float(bp[i, c]))}
             for i, (p, c) in enumerate(zip(peaks[ok], bp.argmax(1)))]
    # 4. measurements: rate from normal-to-normal intervals only
    cls = bp.argmax(1)
    t = peaks[ok] / FS
    nn_rr = np.array([t[i + 1] - t[i] for i in range(len(t) - 1) if cls[i] == 0 and cls[i + 1] == 0])
    all_rr = np.diff(t)
    meas = {
        "heart_rate_bpm": float(60 / np.median(nn_rr)) if len(nn_rr) else float(60 / np.median(all_rr)),
        "rr_min_s": float(all_rr.min()), "rr_max_s": float(all_rr.max()),
        "rr_cv": float(all_rr.std() / all_rr.mean()),
        "beats_analysed": int(len(beats)),
        "usable_fraction": float(usable.mean()),
    }
    counts = {c: int((cls == i).sum()) for i, c in enumerate(beat_data.CLASSES)}
    findings = []
    if counts["V"]:
        findings.append(f"Premature ventricular complexes: {counts['V']} beat(s)")
    if counts["S"]:
        findings.append(f"Supraventricular ectopic beats: {counts['S']} beat(s)")
    if counts["F"]:
        findings.append(f"Fusion beats: {counts['F']} beat(s)")
    if (q_label == 1).any():
        findings.append(f"Noisy signal in {int((q_label == 1).sum())} of {len(q_label)} windows: morphology less reliable there")
    meas["beat_counts"] = counts
    return _result(segments, beats, meas, findings, models)


def _result(segments, beats, measurements, findings, models: Models) -> dict:
    return {
        "engine": {"name": "cardiotic-ml research pipeline", "version": __version__, "use": "research use only",
                   "models": {k: {"sha256": v["sha256"][:12]} for k, v in models.cards.items()}},
        "quality_segments": segments, "beats": beats, "measurements": measurements, "findings": findings,
    }


def plot_strip(signal: np.ndarray, fs: float, result: dict, start_s: float, seconds: float, path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = dsp.resample(np.asarray(signal, dtype=np.float32), fs, FS)
    a, b = int(start_s * FS), int((start_s + seconds) * FS)
    t = np.arange(a, b) / FS
    fig, ax = plt.subplots(figsize=(14, 3.2), dpi=120)
    colours = {"good": None, "noisy": "#FDE68A", "unusable": "#E5E7EB"}
    for seg in result["quality_segments"]:
        if colours[seg["quality"]] and seg["end_s"] > start_s and seg["start_s"] < start_s + seconds:
            ax.axvspan(max(seg["start_s"], start_s), min(seg["end_s"], start_s + seconds), color=colours[seg["quality"]], alpha=0.8, lw=0)
    ax.plot(t, x[a:b], color="#1A2440", lw=0.8)
    top = np.percentile(x[a:b], 99.5) + 0.3
    style = {"N": "#246BFD", "S": "#D97706", "V": "#7C3AED", "F": "#DC2626"}
    for beat in result["beats"]:
        if start_s <= beat["time_s"] < start_s + seconds:
            ax.text(beat["time_s"], top, beat["class"], color=style[beat["class"]], ha="center", fontsize=9, fontweight="bold")
    ax.set_ylim(x[a:b].min() - 0.3, top + 0.4)
    ax.set_xlabel("time (s)"); ax.set_ylabel("mV")
    ax.grid(True, color="#F3C9C9", lw=0.4)
    ax.set_title("Cardiotic AI research pipeline — beat labels (N normal, S supraventricular, V ventricular, F fusion); "
                 "amber = noisy, grey = unusable", fontsize=9)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
