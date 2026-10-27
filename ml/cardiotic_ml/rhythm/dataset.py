"""Rhythm data (model M3): 30 s single-lead windows -> N / A / O / ~ (CinC 2017 label set).

Waveform: monitoring band-pass, resampled to 150 Hz (AF information — RR irregularity, absent P
waves, f-waves at 4–9 Hz — survives easily), then amplitude-normalised per window.
RR features: computed from the detected beats inside each window. Irregularity of RR intervals is
the single strongest AF marker, so it is given to the model explicitly as well.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from cardiotic_ml import dsp, qrs

FS_MODEL = 150
WIN_S = 30
WIN = FS_MODEL * WIN_S       # 4500 samples
STRIDE_S = 15
N_RRF = 10
N_RRF_ECTOPY = N_RRF + 6   # v0.2+: ectopy-aware features appended


@dataclass
class RhythmSet:
    x: np.ndarray        # (n, WIN) float32
    rr: np.ndarray       # (n, N_RRF) float32
    y: np.ndarray        # (n,) int64 (-1 when unknown)
    group: np.ndarray    # (n,) record id the window came from (for record-level aggregation)


def rr_window_features(peaks_s: np.ndarray, duration_s: float) -> np.ndarray:
    f = np.zeros(N_RRF, dtype=np.float32)
    if len(peaks_s) < 4:
        f[-1] = 1.0  # "too few beats" flag
        return f
    rr = np.diff(peaks_s)
    d = np.abs(np.diff(rr))
    mean, med = rr.mean(), np.median(rr)
    f[:9] = [
        len(peaks_s) / duration_s,                     # beats per second
        mean, rr.std() / mean,                         # mean RR, coefficient of variation
        np.sqrt(np.mean(np.diff(rr) ** 2)) / mean,     # normalised RMSSD
        np.mean(d > 0.05),                             # pNN50
        np.median(d) / med,                            # median successive change
        (np.percentile(rr, 75) - np.percentile(rr, 25)) / med,
        np.mean(d / rr[:-1] > 0.15),                   # share of >15 % beat-to-beat changes
        rr.min() / med,
    ]
    return np.clip(f, 0, 10)


def rr_window_features_ectopy(peaks_s: np.ndarray, ectopic: np.ndarray, duration_s: float) -> np.ndarray:
    """Base features plus the same irregularity measured only on intervals that do not touch a
    ventricular (or fusion) beat, and the share of such beats. Frequent PVCs make RR irregular
    without AF; AF stays irregular after they are removed."""
    ext = np.zeros(6, dtype=np.float32)
    if len(peaks_s) >= 4:
        ext[0] = float(np.mean(ectopic))
        rr = np.diff(peaks_s)
        r = rr[~(ectopic[1:] | ectopic[:-1])]
        if len(r) >= 3:
            d = np.abs(np.diff(r))
            m = r.mean()
            ext[1:5] = [r.std() / m, np.sqrt(np.mean(np.diff(r) ** 2)) / m, np.mean(d > 0.05), np.mean(d / r[:-1] > 0.15)]
        else:
            ext[5] = 1.0  # too few intervals free of ectopic beats
    return np.concatenate([rr_window_features(peaks_s, duration_s), np.clip(ext, 0, 10)])


def ectopic_beats(signal: np.ndarray, fs: float, peaks: np.ndarray, beat_model) -> np.ndarray:
    """True for beats the beat classifier (M2) calls ventricular or fusion."""
    import torch

    from cardiotic_ml.beats import dataset as beat_data

    x360 = dsp.resample(np.asarray(signal, dtype=np.float32), fs, beat_data.FS)
    p360 = np.clip(np.round(peaks * beat_data.FS / fs).astype(np.int64), 0, len(x360) - 1)
    out = np.zeros(len(peaks), dtype=bool)
    if len(peaks) < 3:
        return out
    wins, rr, ok = beat_data.from_signal(x360, p360, beat_data.FS)
    if ok.any():
        with torch.no_grad():
            cls = beat_model(torch.from_numpy(wins), torch.from_numpy(rr)).argmax(1).numpy()
        out[np.flatnonzero(ok)] = np.isin(cls, [beat_data.CLASSES.index("V"), beat_data.CLASSES.index("F")])
    return out


def prepare(signal: np.ndarray, fs: float, beat_model=None) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Band-passed 150 Hz signal, beat times (s) and — when a beat model is given — which beats
    are ventricular/fusion, for one recording."""
    peaks = qrs.detect_beats(signal, int(fs))
    x = dsp.resample(dsp.bandpass(signal, fs, "monitoring"), fs, FS_MODEL)
    ect = ectopic_beats(signal, fs, peaks, beat_model) if beat_model is not None else None
    return x, peaks / fs, ect


def windows(x: np.ndarray, beats_s: np.ndarray, stride_s: float = STRIDE_S,
            ectopic: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(waveforms, rr features, start seconds). Short recordings are zero-padded to 30 s.
    With `ectopic`, the ectopy-aware feature set (N_RRF_ECTOPY) is used."""
    starts = list(range(0, max(len(x) - WIN, 0) + 1, int(stride_s * FS_MODEL))) or [0]
    if len(x) > WIN and (len(x) - WIN) not in starts:
        starts.append(len(x) - WIN)  # cover the tail
    xs, rs = [], []
    for s in starts:
        w = x[s:s + WIN]
        dur = len(w) / FS_MODEL
        w = np.pad(w, (0, WIN - len(w)))
        xs.append(w / (np.std(w[: int(dur * FS_MODEL)]) + 1e-3))
        t0 = s / FS_MODEL
        m = (beats_s >= t0) & (beats_s < t0 + dur)
        rs.append(rr_window_features(beats_s[m] - t0, dur) if ectopic is None
                  else rr_window_features_ectopy(beats_s[m] - t0, ectopic[m], dur))
    return np.asarray(xs, dtype=np.float32), np.asarray(rs, dtype=np.float32), np.asarray(starts) / FS_MODEL


def build(signals: dict[str, np.ndarray], labels: dict[str, int], record_ids: list[str], fs: float,
          beat_model=None) -> RhythmSet:
    xs, rs, ys, gs = [], [], [], []
    for rid in record_ids:
        x, beats, ect = prepare(signals[rid], fs, beat_model)
        w, r, _ = windows(x, beats, ectopic=ect)
        xs.append(w); rs.append(r); ys += [labels[rid]] * len(w); gs += [rid] * len(w)
    return RhythmSet(np.concatenate(xs), np.concatenate(rs), np.asarray(ys, dtype=np.int64), np.asarray(gs))


# ---------------------------------------------------------------- MIT-BIH windows with rhythm labels
NON_AF_RHYTHMS = {"(AB", "(AFL", "(B", "(BII", "(IVR", "(NOD", "(SVTA", "(T", "(VFL", "(VT", "(PREX"}
SINUS = {"(N", "(SBR"}


def mitdb_rhythm_spans(rid: int, n_samples: int) -> list[tuple[int, int, str]]:
    import wfdb

    from cardiotic_ml.paths import MITDB_DIR

    ann = wfdb.rdann(str(MITDB_DIR / str(rid)), "atr")
    marks = [(s, a.strip("\x00")) for s, sym, a in zip(ann.sample, ann.symbol, ann.aux_note) if sym == "+"]
    return [(s, marks[i + 1][0] if i + 1 < len(marks) else n_samples, a) for i, (s, a) in enumerate(marks)]


def mitdb_window_label(rhythms: list[str], n_ectopic: int) -> int | None:
    """CinC-style label for one 30 s MIT-BIH window from the cardiologists' annotations, or None
    when ambiguous. AF only if the whole window is AF. Sinus windows with >= 3 ectopic beats
    (supraventricular, ventricular or fusion) count as 'other rhythm', 0 as normal, 1–2 skipped."""
    labels = ["N", "A", "O", "~"]
    if not rhythms:
        return None
    if rhythms == ["(AFIB"]:
        return labels.index("A")
    if "(AFIB" in rhythms or "(P" in rhythms:
        return None
    if any(r in NON_AF_RHYTHMS for r in rhythms):
        return labels.index("O")
    if all(r in SINUS for r in rhythms):
        return labels.index("N") if n_ectopic == 0 else labels.index("O") if n_ectopic >= 3 else None
    return None


def build_mitdb(record_ids: list[int], beat_model=None, stride_s: float = STRIDE_S) -> RhythmSet:
    from cardiotic_ml.data import mitdb

    xs, rs, ys, gs = [], [], [], []
    for rid in record_ids:
        rec = mitdb.load_record(rid)
        x, beats, ect = prepare(rec.signal, rec.fs, beat_model)
        w, r, starts = windows(x, beats, stride_s=stride_s, ectopic=ect)
        spans = mitdb_rhythm_spans(rid, len(rec.signal))
        ectopic_ref = rec.ann_samples[[mitdb.aami_class(c) in ("S", "V", "F") for c in rec.ann_symbols]]
        for wi, st in enumerate(starts):
            a, b = int(st * rec.fs), int((st + WIN_S) * rec.fs)
            lab = mitdb_window_label([lab for s0, e0, lab in spans if s0 < b and e0 > a],
                                     int(((ectopic_ref >= a) & (ectopic_ref < b)).sum()))
            if lab is not None:
                xs.append(w[wi]); rs.append(r[wi]); ys.append(lab); gs.append(f"mitdb{rid}")
    return RhythmSet(np.asarray(xs, dtype=np.float32), np.asarray(rs, dtype=np.float32),
                     np.asarray(ys, dtype=np.int64), np.asarray(gs))
