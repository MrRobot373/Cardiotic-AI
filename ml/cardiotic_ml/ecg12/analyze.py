"""End-to-end analysis of one 10 s 12-lead ECG — what the 12-lead review screen shows.

per-lead signal quality (M1) -> measurements (median beat, calipers) -> statements (M4, calibrated)
Leads the quality model rates unusable are named in the output; measurements and statements are
withheld when more than two leads are unusable (both use all 12 leads, and the statement model was
trained on complete 12-lead ECGs).
"""

from __future__ import annotations

import json

import numpy as np

from cardiotic_ml import __version__, calibration as cal, dsp
from cardiotic_ml.data.ptbxl import LEADS
from cardiotic_ml.ecg12 import measure
from cardiotic_ml.paths import ARTIFACTS_DIR
from cardiotic_ml.quality import dataset as q_data
from cardiotic_ml.runner import TorchRunner, run_batched

ECG12_MODEL = "ecg12_net_v0.3"  # chosen by experiments_ecg12.select_ecg12 on validation data (reports/ecg12_selection.json)
QUALITY_MODEL = "quality_net_v0.3"
FS_MODEL, N_MODEL = 100, 1000
MAX_UNUSABLE_LEADS = 2


class Models12:
    """Statement and quality runners plus their cards. Default: PyTorch weights from ARTIFACTS_DIR
    (research); the engine passes ONNX runners and its manifest entries instead."""

    def __init__(self, directory=ARTIFACTS_DIR, net=None, card=None, quality=None, q_card=None, site=None):
        if net is None:
            import torch

            from cardiotic_ml.ecg12.model import ECG12Net
            from cardiotic_ml.quality.model import QualityNet

            card = json.loads((directory / f"{ECG12_MODEL}.card.json").read_text())
            m = ECG12Net(len(card["labels"]), width=card["recipe"]["width"])
            m.load_state_dict(torch.load(directory / f"{ECG12_MODEL}.pt", weights_only=True))
            q_card = json.loads((directory / f"{QUALITY_MODEL}.card.json").read_text())
            q = QualityNet(len(q_data.LABELS))
            q.load_state_dict(torch.load(directory / f"{QUALITY_MODEL}.pt", weights_only=True))
            net, quality = TorchRunner(m), TorchRunner(q)
        self.net, self.card, self.quality, self.q_card = net, card, quality, q_card
        # per-site operating points (ecg12/site.py): thresholds only, never the model
        from cardiotic_ml.ecg12 import site as site_cfg
        self.site = site_cfg.validate(site, card) if site else None
        self.thresholds = site_cfg.thresholds(self.site, card["thresholds"])


def lead_quality(signal: np.ndarray, fs: float, models: Models12) -> dict[str, str]:
    """Worst-of-majority label per lead from 2.5 s windows (good / noisy / unusable)."""
    out = {}
    for name, lead in zip(LEADS, signal):
        wins = q_data.signal_windows(lead, fs, q_data.lowpass_of(models.q_card))
        lab = run_batched(models.quality, np.clip(wins, -10, 10)).argmax(1)
        out[name] = q_data.LABELS[2] if (lab == 2).mean() > 0.5 else q_data.LABELS[1] if (lab >= 1).mean() > 0.5 else q_data.LABELS[0]
    return out


def probabilities(signal: np.ndarray, fs: float, models: Models12) -> np.ndarray:
    """Calibrated probability of every statement the model has (card["labels"] order), before any threshold."""
    x = dsp.resample(signal, fs, FS_MODEL) if fs != FS_MODEL else signal.astype(np.float32)
    x = x[:, :N_MODEL] if x.shape[1] >= N_MODEL else np.pad(x, ((0, 0), (0, N_MODEL - x.shape[1])))
    x = dsp.bandpass(x, FS_MODEL, "diagnostic")
    c = models.card
    x = (x - np.array(c["lead_mean"])[:, None]) / np.array(c["lead_std"])[:, None]
    z = run_batched(models.net, x[None].astype(np.float32))[0] / c["temperature"]
    return 1 / (1 + np.exp(-z))


def statements(signal: np.ndarray, fs: float, models: Models12) -> list[dict]:
    c = models.card
    p = probabilities(signal, fs, models)
    th = models.thresholds
    out = [{"statement": name, "probability": float(pi), "threshold": th[name],
            "confidence": cal.confidence_level(float(pi))}  # how sure the finding is present
           for name, pi in zip(c["labels"], p) if pi >= th[name]]
    if models.site:
        site = models.site["statements"]
        for d in out:
            d["threshold_source"] = "site" if d["statement"] in site else "model"
    return sorted(out, key=lambda d: -d["probability"])


def analyze_12lead(signal: np.ndarray, fs: float, models: Models12) -> dict:
    """signal: (12, n) in mV, LEADS order, ideally 10 s."""
    signal = np.asarray(signal, dtype=np.float32)
    quality = lead_quality(signal, fs, models)
    unusable = [l for l, q in quality.items() if q == "unusable"]
    notes = []
    if unusable:
        notes.append(f"Unusable lead(s): {', '.join(unusable)} — check electrodes")
    stm = []
    if len(unusable) > MAX_UNUSABLE_LEADS:
        notes.append("Measurements and statements withheld: more than two leads unusable")
        meas = {"ok": False, "reason": "more than two leads unusable"}
    else:
        meas = measure.measure(signal, fs)
        stm = statements(signal, fs, models)
    if meas.get("ok") and meas.get("rr_irregular"):
        notes.append("Irregular rhythm: PR interval not reported")
    return {"engine": {"name": "cardiotic-ml research pipeline (12-lead)", "version": __version__, "use": "research use only",
                       "models": {ECG12_MODEL: {"sha256": models.card["sha256"][:12], "temperature": models.card["temperature"]},
                                  QUALITY_MODEL: {"sha256": models.q_card["sha256"][:12]}}},
            "lead_quality": quality, "measurements": meas, "statements": stm, "notes": notes,
            **({"operating_points": {"site_id": models.site["site_id"], "config_version": models.site["config_version"],
                                     "statements_set_by_site": len(models.site["statements"])}} if models.site else {})}


def plot_12lead(signal: np.ndarray, fs: float, result: dict, path, title: str = "") -> None:
    """12 median beats (3 x 4 layout, ECG-paper grid) with the global calipers: P on, QRS on/off, T end."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mb = measure.median_beat(np.asarray(signal, dtype=np.float32), fs)
    m = result["measurements"]
    fig, axes = plt.subplots(3, 4, figsize=(14, 7.5), dpi=110, sharex=True)
    t = (np.arange(mb.beat.shape[1]) - mb.r) / fs * 1000 if mb else None
    f = m.get("fiducials", {}) if m.get("ok") else {}
    calipers = [("p_on", "#246BFD", "P"), ("qrs_on", "#16A34A", "QRS"), ("qrs_off", "#16A34A", ""), ("t_end", "#DC2626", "T end")]
    for ax, li in zip(axes.T.ravel(), range(12)):  # columns: I II III | aVR aVL aVF | V1 V2 V3 | V4 V5 V6
        ax.grid(True, color="#F3C9C9", lw=0.5)
        if mb is not None:
            ax.plot(t, mb.beat[li], color="#1A2440", lw=1.1)
            for key, colour, _ in calipers:
                if f.get(key) is not None:
                    ax.axvline((f[key] - mb.r) / fs * 1000, color=colour, ls="--", lw=0.8)
        q = result["lead_quality"].get(LEADS[li], "")
        ax.set_title(f"{LEADS[li].replace('AV', 'aV')}" + ("" if q == "good" else f"  ({q})"), fontsize=9,
                     color="#DC2626" if q == "unusable" else "#1A2440")
    for ax in axes[-1]:
        ax.set_xlabel("ms from R peak", fontsize=8)
    fmt = lambda k, u: "—" if m.get(k) is None else f"{m[k]:.0f} {u}"  # noqa: E731
    head = (f"HR {fmt('heart_rate_bpm', 'bpm')}   PR {fmt('pr_ms', 'ms')}   QRS {fmt('qrs_ms', 'ms')}   QT {fmt('qt_ms', 'ms')}   "
            f"QTc {fmt('qtc_bazett_ms', 'ms')}   QRS axis {fmt('qrs_axis_deg', '°')}") if m.get("ok") else "Measurements withheld"
    stm = ", ".join(f"{s['statement'].replace('SUPER_', '')} {100 * s['probability']:.0f}%" for s in result["statements"][:6]) or "none above threshold"
    fig.suptitle(f"Cardiotic AI research pipeline — 12-lead median beats {title}\n{head}\nAI statements: {stm}", fontsize=10)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
