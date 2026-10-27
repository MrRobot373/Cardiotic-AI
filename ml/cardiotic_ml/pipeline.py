"""End-to-end analysis of one single-lead recording — what the review screen shows.

quality gate -> beat detection -> beat classification -> rhythm (30 s windows) -> measurements -> findings.
Segments the quality model marks *unusable* produce no beats and no findings, and are listed for
manual review rather than silently dropped. Probabilities are temperature-calibrated (M5).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import torch

from cardiotic_ml import __version__, calibration as cal, dsp, qrs
from cardiotic_ml.beats import dataset as beat_data
from cardiotic_ml.beats.model import BeatNet
from cardiotic_ml.paths import ARTIFACTS_DIR
from cardiotic_ml.quality import dataset as q_data
from cardiotic_ml.quality.model import QualityNet
from cardiotic_ml.rhythm import dataset as rd
from cardiotic_ml.rhythm.model import RhythmNet

FS = 360
# Best detector on the MIT-BIH benchmark (reports/qrs_detection.json).
QRS_METHOD = "pantompkins1985"
# Model versions used by the pipeline — each chosen on validation data, never on the test set.
QUALITY_MODEL = "quality_net_v0.3"  # v0.1 over-rejects clean recordings, v0.2 too lenient on real noise (validation)
BEAT_MODEL = "beat_net_v0.1"  # v0.2 (augmentation) scored lower on validation patients
RHYTHM_MODEL = "rhythm_net_v0.1"  # v0.2 passed validation but missed AF with frequent PVCs on test (RESULTS.md)
RHYTHM_LABELS = ["N", "A", "O", "~"]
RHYTHM_NAMES = {"N": "sinus rhythm", "A": "atrial fibrillation", "O": "other rhythm", "~": "too noisy for rhythm"}


@dataclass
class Models:
    quality: QualityNet
    beats: BeatNet
    rhythm: RhythmNet | None
    cards: dict


def load_models(directory=ARTIFACTS_DIR) -> Models:
    cards = {n: json.loads((directory / f"{n}.card.json").read_text()) for n in (QUALITY_MODEL, BEAT_MODEL)}
    q, b = QualityNet(len(q_data.LABELS)), BeatNet(len(beat_data.CLASSES))
    q.load_state_dict(torch.load(directory / f"{QUALITY_MODEL}.pt", weights_only=True))
    b.load_state_dict(torch.load(directory / f"{BEAT_MODEL}.pt", weights_only=True))
    r = None
    if (directory / f"{RHYTHM_MODEL}.pt").exists():
        cards[RHYTHM_MODEL] = json.loads((directory / f"{RHYTHM_MODEL}.card.json").read_text())
        r = RhythmNet(len(RHYTHM_LABELS), n_rrf=cards[RHYTHM_MODEL].get("n_rrf", rd.N_RRF))
        r.load_state_dict(torch.load(directory / f"{RHYTHM_MODEL}.pt", weights_only=True))
        r.eval()
    q.eval(); b.eval()
    return Models(q, b, r, cards)


confidence_level = cal.confidence_level
BATCH = 256  # bounded memory on long (e.g. 24 h Holter) recordings


@torch.no_grad()
def _batched(model, *arrays: np.ndarray) -> np.ndarray:
    """Run a model over arrays in fixed-size chunks; returns raw outputs (logits)."""
    n = len(arrays[0])
    if n == 0:
        return np.zeros((0, model.head[-1].out_features), dtype=np.float32)
    return np.concatenate([model(*(torch.from_numpy(np.ascontiguousarray(a[i:i + BATCH])) for a in arrays)).numpy()
                           for i in range(0, n, BATCH)])


@torch.no_grad()
def _rhythm(signal: np.ndarray, fs: float, usable: np.ndarray, models: Models,
            beat_times_s: np.ndarray, beat_cls: np.ndarray) -> list[dict]:
    if models.rhythm is None or len(signal) < 9 * fs:
        return []
    if models.cards[RHYTHM_MODEL].get("recipe", {}).get("ectopy_features"):
        # reuse the pipeline's own beats and beat classes: ventricular / fusion beats are ectopic
        x = dsp.resample(dsp.bandpass(np.asarray(signal, dtype=np.float32), fs, "monitoring"), fs, rd.FS_MODEL)
        ect = np.isin(beat_cls, [beat_data.CLASSES.index("V"), beat_data.CLASSES.index("F")])
        w, r, starts = rd.windows(x, beat_times_s, ectopic=ect)
    else:
        x, beats, _ = rd.prepare(np.asarray(signal, dtype=np.float32), fs)
        w, r, starts = rd.windows(x, beats)
    logits = _batched(models.rhythm, w, r)
    p = cal.softmax(logits, models.cards[RHYTHM_MODEL].get("temperature", 1.0))
    out = []
    for st, prob in zip(starts, p):
        a, b = int(st * FS), int((st + rd.WIN_S) * FS)
        if usable[a:b].mean() < 0.5:
            continue  # rhythm is not called on mostly unusable signal
        k = int(prob.argmax())
        out.append({"start_s": float(st), "end_s": float(min(st + rd.WIN_S, len(signal) / fs)),
                    "rhythm": RHYTHM_LABELS[k], "probability": float(prob[k]), "confidence": confidence_level(float(prob[k])),
                    "probabilities": {l: float(v) for l, v in zip(RHYTHM_LABELS, prob)}})
    return out


@torch.no_grad()
def analyze(signal: np.ndarray, fs: float, models: Models) -> dict:
    raw = np.asarray(signal, dtype=np.float32)
    x = dsp.resample(raw, fs, FS)
    win = q_data.WIN
    # 1. quality, per 2.5 s window
    starts = np.arange(0, max(len(x) - win, 0) + 1, win)
    wins = np.stack([x[s:s + win] - np.median(x[s:s + win]) for s in starts]) if len(starts) else np.zeros((0, win))
    qp = cal.softmax(_batched(models.quality, np.clip(wins, -10, 10).astype(np.float32)))
    q_label = qp.argmax(1)
    segments = [{"start_s": float(s / FS), "end_s": float((s + win) / FS), "quality": q_data.LABELS[l],
                 "probability": float(qp[i, l])} for i, (s, l) in enumerate(zip(starts, q_label))]
    usable = np.zeros(len(x), dtype=bool)
    for s, l in zip(starts, q_label):
        usable[s:s + win] = l != 2
    review = [f"{int((q_label == 2).sum())} of {len(q_label)} windows not analysable: shown for manual review"] if (q_label == 2).any() else []
    if len(starts) == 0 or usable.mean() < 0.5:
        return _result(segments, [], [], {}, ["Not analysable: less than half the recording has usable signal quality."] + review, models)
    # 2. beats, only inside usable windows
    peaks = qrs.detect_beats(x, FS, QRS_METHOD)
    peaks = peaks[usable[peaks]]
    if len(peaks) < 3:
        return _result(segments, [], [], {}, ["Not analysable: too few beats detected in usable segments."] + review, models)
    # 3. classify beats (calibrated)
    bw, rr, ok = beat_data.from_signal(x, peaks, FS)
    bp = cal.softmax(_batched(models.beats, bw, rr),
                     models.cards[BEAT_MODEL].get("temperature", 1.0))
    beats = [{"time_s": float(p / FS), "class": beat_data.CLASSES[c], "probability": float(bp[i, c]),
              "confidence": confidence_level(float(bp[i, c]))}
             for i, (p, c) in enumerate(zip(peaks[ok], bp.argmax(1)))]
    # 4. rhythm, per 30 s window
    rhythm = _rhythm(raw, fs, usable, models, peaks[ok] / FS, bp.argmax(1))
    # 5. measurements: rate from normal-to-normal intervals only
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
    af_predominant = False
    if rhythm:
        tally = {l: [s for s in rhythm if s["rhythm"] == l] for l in RHYTHM_LABELS}
        if tally["A"]:
            best = max(s["probability"] for s in tally["A"])
            findings.append(f"Possible atrial fibrillation in {len(tally['A'])} of {len(rhythm)} rhythm windows "
                            f"(highest confidence: {confidence_level(best)})")
        main = max(RHYTHM_LABELS, key=lambda l: len(tally[l]))
        findings.append(f"Predominant rhythm: {RHYTHM_NAMES[main]} ({len(tally[main])} of {len(rhythm)} windows)")
        af_predominant = main == "A"
    if counts["V"]:
        findings.append(f"Premature ventricular complexes: {counts['V']} beat(s)")
    if counts["S"] and not af_predominant:  # premature atrial beats are not defined during AF
        findings.append(f"Supraventricular ectopic beats: {counts['S']} beat(s)")
    if counts["F"]:
        findings.append(f"Fusion beats: {counts['F']} beat(s)")
    if (q_label == 1).any():
        findings.append(f"Noisy signal in {int((q_label == 1).sum())} of {len(q_label)} windows: morphology less reliable there")
    meas["beat_counts"] = counts
    return _result(segments, beats, rhythm, meas, findings + review, models)


def _result(segments, beats, rhythm, measurements, findings, models: Models) -> dict:
    return {
        "engine": {"name": "cardiotic-ml research pipeline", "version": __version__, "use": "research use only",
                   "models": {k: {"sha256": v["sha256"][:12], "temperature": v.get("temperature")} for k, v in models.cards.items()}},
        "quality_segments": segments, "beats": beats, "rhythm_segments": rhythm,
        "measurements": measurements, "findings": findings,
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
