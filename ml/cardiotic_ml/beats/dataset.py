"""Beat classification data: AAMI classes N / S / V / F from MIT-BIH, inter-patient split.

Train: DS1 minus the validation patients. Validation (epoch selection only): VAL_PATIENTS,
also from DS1. Test: DS2 — patients never seen in training or model selection.
Q (unclassifiable / paced) beats are excluded, as is standard for this benchmark.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from cardiotic_ml import dsp

CLASSES = ["N", "S", "V", "F"]
FS = 360  # MIT-BIH sampling rate; the model's input rate
PRE, POST = 90, 144          # 250 ms before, 400 ms after the R peak (234 samples)
VAL_PATIENTS = [106, 118, 207, 220]
N_RR = 7


@dataclass
class BeatSet:
    x: np.ndarray        # (n, PRE+POST) beat waveform, record-scaled
    rr: np.ndarray       # (n, N_RR) RR-interval features
    y: np.ndarray        # (n,) class index into CLASSES (-1 if unknown, e.g. at inference)
    record: np.ndarray   # (n,) record id
    sample: np.ndarray   # (n,) R-peak sample


def rr_features(peaks: np.ndarray, fs: int) -> np.ndarray:
    """Per-beat timing features. Beats at the edges reuse their neighbour's interval."""
    rr = np.diff(peaks) / fs
    pre = np.concatenate([[rr[0]], rr]) if len(rr) else np.ones(len(peaks))
    post = np.concatenate([rr, [rr[-1]]]) if len(rr) else np.ones(len(peaks))
    local = np.array([pre[max(0, i - 10):i + 1].mean() for i in range(len(pre))])
    overall = np.median(pre)
    feats = np.stack([pre, post, local, pre / local, post / local, pre / post, pre / overall], axis=1)
    return np.clip(feats, 0, 5).astype(np.float32)


def beat_windows(filtered: np.ndarray, peaks: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (windows, mask of peaks that had a full window)."""
    ok = (peaks - PRE >= 0) & (peaks + POST <= len(filtered))
    amp = np.median(np.abs(filtered[peaks[ok]])) + 1e-3  # record-level amplitude scale
    wins = np.stack([filtered[p - PRE:p + POST] for p in peaks[ok]]) / amp if ok.any() else np.zeros((0, PRE + POST))
    return wins.astype(np.float32), ok


def from_signal(signal: np.ndarray, peaks: np.ndarray, fs: int = FS) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Features for arbitrary detected peaks (used at inference)."""
    filt = dsp.bandpass(signal, fs, "monitoring")
    feats = rr_features(peaks, fs)
    wins, ok = beat_windows(filt, peaks)
    return wins, feats[ok], ok


def build(record_ids: list[int]) -> BeatSet:
    from cardiotic_ml.data import mitdb

    xs, rrs, ys, recs, samples = [], [], [], [], []
    for rid in record_ids:
        if rid in mitdb.PACED:
            continue
        rec = mitdb.load_record(rid)
        qrs_mask = np.isin(rec.ann_symbols, list(mitdb.QRS_SYMBOLS))
        peaks, syms = rec.ann_samples[qrs_mask], rec.ann_symbols[qrs_mask]
        wins, feats, ok = from_signal(rec.signal, peaks)
        labels = np.array([CLASSES.index(c) if (c := mitdb.aami_class(s)) in CLASSES else -1 for s in syms[ok]])
        keep = labels >= 0
        xs.append(wins[keep]); rrs.append(feats[keep]); ys.append(labels[keep])
        recs.append(np.full(keep.sum(), rid)); samples.append(peaks[ok][keep])
    return BeatSet(np.concatenate(xs), np.concatenate(rrs), np.concatenate(ys).astype(np.int64),
                   np.concatenate(recs), np.concatenate(samples))


def splits() -> tuple[BeatSet, BeatSet, BeatSet]:
    from cardiotic_ml.data import mitdb

    train_ids = [r for r in mitdb.DS1 if r not in VAL_PATIENTS]
    return build(train_ids), build(VAL_PATIENTS), build(mitdb.DS2)
