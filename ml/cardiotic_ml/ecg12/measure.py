"""M4 measurements: heart rate, PR, QRS, QT/QTc and frontal axes from a 12-lead ECG.

Deterministic signal processing, not a learned model, so every number traces back to sample
positions in the recording:

  1. heartbeats are detected on the lead with the steepest QRS (largest slope), so a lead where the
     QRS is small next to the T wave is not used;
  2. dominant beats (regular RR before and after, shape like the others) are averaged into a
     **median beat** per lead;
  3. QRS onset / offset come from the **spatial velocity** (speed of the 12-lead signal), which
     does not depend on baseline or on which lead shows the QRS best;
  4. T end is found on the root-mean-square of the 12 baseline-corrected leads (tangent method or
     return-to-baseline threshold, chosen on training data);
  5. the P wave is searched between the previous T wave and the QRS; PR is reported only when a P
     wave is found;
  6. axes come from net QRS / T areas in leads I and aVF.

Global onsets / offsets span all leads, as in IEC 60601-2-25. Thresholds (`Params`) were tuned on
PTB-XL training folds only (see experiments_ecg12.tune_measurements).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from cardiotic_ml import dsp, qrs
from cardiotic_ml.data.ptbxl import LEADS

PRE_S, POST_S = 0.45, 0.70           # median-beat window around each R peak
IRREGULAR = 0.10                     # median |successive RR change| / median RR above this: irregular rhythm, no PR


@dataclass(frozen=True)
class Params:
    # defaults = measurement v0.2, chosen on training folds (reports/ecg12_measurement_tuning_v0.2.json)
    qrs_on: float = 0.03     # QRS onset where spatial velocity falls below this fraction of its QRS maximum
    qrs_off: float = 0.08
    gap_ms: float = 12.0     # dips below threshold shorter than this stay inside the QRS
    qrs_core: float | None = 0.1  # if set: QRS core at this fraction, then out to qrs_on/off or a velocity minimum
    p_frac: float | None = 0.2  # P onset where the P-wave RMS falls below this fraction of its peak; None = half-height rule
    p_min_mv: float = 0.02   # smallest P-wave RMS accepted as a P wave
    p_search_ms: float = 300.0  # P wave searched at most this long before QRS onset
    t_frac: float | None = 0.03  # T end at floor + t_frac x (peak - floor); None = tangent method
    t_cap_ms: float | None = 30.0  # threshold T end at most this long after the tangent T end


@dataclass
class MedianBeat:
    beat: np.ndarray         # (12, L) median beat, mV
    fs: float
    r: int                   # R-peak index in `beat`
    rr_s: float              # mean RR, seconds
    rr_irr: float            # median |successive RR change| / median RR (robust to one missed beat)
    n_beats: int
    n_used: int
    r_peaks: np.ndarray      # all detected R peaks (samples, recording)
    used: np.ndarray         # bool per R peak: part of the median beat
    detect_lead: str


def median_beat(signal: np.ndarray, fs: float) -> MedianBeat | None:
    """signal: (12, n) mV in LEADS order. None if fewer than 3 heartbeats are found."""
    x = dsp.bandpass(np.asarray(signal, dtype=np.float32), fs, "monitoring")
    slope = np.percentile(np.abs(np.diff(x, axis=1)), 99, axis=1)
    lead = LEADS[int(slope.argmax())]
    peaks = qrs.detect_beats(x[LEADS.index(lead)], int(fs))
    if len(peaks) < 3:
        return None
    rr = np.diff(peaks)
    med = np.median(rr)
    pre, post = int(PRE_S * fs), int(POST_S * fs)
    inside = (peaks - pre >= 0) & (peaks + post <= x.shape[1])
    regular = np.zeros(len(peaks), dtype=bool)
    for i in range(len(peaks)):
        before = rr[i - 1] if i > 0 else None
        after = rr[i] if i < len(rr) else None
        ok = [abs(v - med) <= 0.2 * med for v in (before, after) if v is not None]
        regular[i] = bool(ok) and all(ok)
    used = inside & regular
    if used.sum() < 2:          # irregular rhythm (e.g. AF): average every complete beat instead
        used = inside.copy()
    if used.sum() < 1:
        return None
    stack = np.stack([x[:, p - pre:p + post] for p in peaks[used]])
    beat = np.median(stack, axis=0)
    # drop beats unlike the median (e.g. ventricular ectopics) on the detection lead, then re-average
    li = LEADS.index(lead)
    corr = np.array([np.corrcoef(b[li], beat[li])[0, 1] for b in stack])
    if (corr >= 0.9).sum() >= 2:
        keep = np.flatnonzero(used)[corr >= 0.9]
        used = np.zeros_like(used); used[keep] = True
        beat = np.median(stack[corr >= 0.9], axis=0)
    irr = float(np.median(np.abs(np.diff(rr))) / med) if len(rr) >= 2 else 0.0
    return MedianBeat(beat.astype(np.float32), fs, pre, float(rr.mean() / fs), irr,
                      len(peaks), int(used.sum()), peaks, used, lead)


def _region(mask: np.ndarray, start: int, lo: int, hi: int, gap: int) -> tuple[int, int]:
    """Extend from `start` while a True sample lies within `gap` samples (bounded by lo..hi)."""
    a = start
    while a > lo and mask[max(a - gap, lo):a].any():
        a -= 1
    b = start
    while b < hi and mask[b + 1:min(b + 1 + gap, hi + 1)].any():
        b += 1
    return a, b


def _walk(vel: np.ndarray, i: int, step: int, limit: int, stop: float, m: int) -> int:
    """Move from i in direction `step` until vel <= stop, or vel starts rising again (a minimum)."""
    while i != limit and vel[i] > stop:
        nxt = i + step * m
        if not 0 <= nxt < len(vel) or vel[nxt] > vel[i]:
            break
        i += step
    return i


def _ms(n: float, fs: float) -> float:
    return 1000.0 * n / fs


def delineate(mb: MedianBeat, p: Params = Params()) -> dict:
    fs, beat, r = mb.fs, mb.beat, mb.r
    s = lambda sec: int(round(sec * fs))  # noqa: E731
    # --- QRS from spatial velocity
    vel = np.sqrt((np.gradient(beat, axis=1) ** 2).sum(0))
    k = max(1, s(0.008))
    vel = np.convolve(vel, np.ones(k) / k, mode="same")
    lo, hi = max(r - s(0.12), 1), min(r + s(0.20), beat.shape[1] - 2)
    core = slice(r - s(0.06), r + s(0.06))
    vmax = vel[core].max()
    peak = r - s(0.06) + int(vel[core].argmax())
    gap = max(1, s(p.gap_ms / 1000))
    if p.qrs_core is None:
        on, _ = _region(vel >= p.qrs_on * vmax, peak, lo, hi, gap)
        _, off = _region(vel >= p.qrs_off * vmax, peak, lo, hi, gap)
    else:  # QRS core, then out to the threshold or the first velocity minimum (J point in wide QRS / ST-T)
        a, b = _region(vel >= p.qrs_core * vmax, peak, lo, hi, gap)
        on = _walk(vel, a, -1, lo, p.qrs_on * vmax, max(1, s(0.004)))
        off = _walk(vel, b, 1, hi, p.qrs_off * vmax, max(1, s(0.004)))
    base = beat[:, max(on - s(0.010), 0):on + 1].mean(1, keepdims=True)
    d = beat - base
    rms = np.sqrt((d ** 2).mean(0))
    # --- T wave on the RMS curve. The search stops before the next beat's P wave, and T end is looked
    # for within 200 ms after the T peak. Tangent rule: tangent at the steepest descent, down to the
    # floor. Threshold rule (t_frac set): first sample where the RMS has fallen to floor + t_frac x
    # (T peak - floor), but no later than t_cap_ms after the tangent end (flat T waves drift late).
    t_hi = min(r + s(float(np.clip(mb.rr_s - 0.15, 0.30, 0.65))), beat.shape[1] - 2)
    t_lo = min(off + s(0.08), t_hi - s(0.05))
    t_peak = t_lo + int(rms[t_lo:t_hi].argmax())
    t_stop = min(t_peak + s(0.20), t_hi)
    t_end = None
    if t_stop - t_peak > s(0.02):
        floor = rms[t_peak:t_stop].min()
        slope = np.gradient(rms)
        st = t_peak + int(slope[t_peak:t_stop].argmin())
        tangent = int(np.clip(st + (floor - rms[st]) / slope[st], st, t_stop)) if slope[st] < 0 else None
        if p.t_frac is None:
            t_end = tangent
        else:
            below = np.flatnonzero(rms[t_peak:t_stop] <= floor + p.t_frac * (rms[t_peak] - floor))
            t_end = t_peak + int(below[0]) if len(below) else tangent
            if t_end is not None and tangent is not None and p.t_cap_ms is not None:
                t_end = min(t_end, tangent + s(p.t_cap_ms / 1000))
    # --- P wave between the previous T wave and the QRS
    p_on = None
    if mb.rr_irr < IRREGULAR:
        prev_t_end = (t_end if t_end is not None else r + s(0.35)) - s(mb.rr_s)
        p_lo = max(0, on - s(p.p_search_ms / 1000), prev_t_end + s(0.02))
        p_hi = on - s(0.03)
        if p_hi - p_lo > s(0.04):
            seg = rms[p_lo:p_hi]
            pk = int(seg.argmax())
            floor = seg[:pk + 1].min()
            height = seg[pk] - floor
            if seg[pk] >= p.p_min_mv and height > 0 and 0 < pk < len(seg) - 1:
                if p.p_frac is None:  # half-height point on the rising limb, extrapolated to the start
                    half = np.flatnonzero(seg[:pk + 1] - floor <= 0.5 * height)
                    p_on = p_lo + max(0, 2 * int(half[-1]) - pk) if len(half) else p_lo
                else:
                    below = np.flatnonzero(seg[:pk + 1] - floor <= p.p_frac * height)
                    p_on = p_lo + int(below[-1]) if len(below) else p_lo
    # --- axes from net areas (leads I and aVF)
    i_, f_ = LEADS.index("I"), LEADS.index("AVF")
    qrs_axis = float(np.degrees(np.arctan2(d[f_, on:off + 1].sum(), d[i_, on:off + 1].sum())))
    t_axis = None
    if t_end is not None:
        t_axis = float(np.degrees(np.arctan2(d[f_, off:t_end + 1].sum(), d[i_, off:t_end + 1].sum())))
    rr = mb.rr_s
    qt = _ms(t_end - on, fs) if t_end is not None else None
    return {
        "heart_rate_bpm": 60.0 / rr,
        "rr_ms": 1000 * rr,
        "pr_ms": _ms(on - p_on, fs) if p_on is not None else None,
        "qrs_ms": _ms(off - on, fs),
        "qt_ms": qt,
        "qtc_bazett_ms": qt / np.sqrt(rr) if qt else None,
        "qtc_fridericia_ms": qt / rr ** (1 / 3) if qt else None,
        "qrs_axis_deg": qrs_axis,
        "t_axis_deg": t_axis,
        # fiducials in the median beat (samples) — what the review screen draws as calipers
        "fiducials": {"p_on": p_on, "qrs_on": int(on), "r": int(r), "qrs_off": int(off), "t_peak": int(t_peak),
                      "t_end": t_end, "fs": fs},
    }


def measure(signal: np.ndarray, fs: float, p: Params = Params()) -> dict:
    mb = median_beat(signal, fs)
    if mb is None:
        return {"ok": False, "reason": "fewer than 3 heartbeats detected"}
    out = delineate(mb, p)
    out.update(ok=True, beats_detected=mb.n_beats, beats_in_median=mb.n_used, detection_lead=mb.detect_lead,
               rr_irregular=mb.rr_irr >= IRREGULAR, params=asdict(p))
    return out
