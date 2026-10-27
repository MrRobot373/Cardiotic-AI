"""Ectopy gate for AF calls (rhythm v0.3 = rhythm v0.1 + this gate).

Frequent premature beats make RR intervals irregular without AF. When the rhythm model calls a
window AF but the rhythm is regular once intervals touching ventricular/fusion beats are removed,
the irregularity is explained by ectopy and the window is re-labelled "other rhythm".

The gate relies on the beat classifier's V/F labels, which are validated only on monitoring lead
MLII (MIT-BIH). On other leads (e.g. handheld lead I, CinC 2017) those labels were shown to be
unreliable on validation data, so the gate is OFF there and for unknown leads — the more
sensitive base model's answer stands.
"""

from __future__ import annotations

import numpy as np

from cardiotic_ml.rhythm.dataset import N_RRF

LABELS = ["N", "A", "O", "~"]
A, O = LABELS.index("A"), LABELS.index("O")


def applies(gate: dict, lead: str | None) -> bool:
    return lead is not None and lead.upper() in {l.upper() for l in gate["leads"]}


def apply(probs: np.ndarray, ectopy_feats: np.ndarray, gate: dict) -> tuple[np.ndarray, np.ndarray]:
    """Return (probabilities, gated mask). Gated windows have their AF probability moved to 'other'."""
    pvc_share = ectopy_feats[:, N_RRF]
    cv_free = ectopy_feats[:, N_RRF + 1]
    gated = (probs.argmax(1) == A) & (pvc_share >= gate["pvc_min"]) & (cv_free < gate["tau"])
    out = probs.copy()
    out[gated, O] += out[gated, A]
    out[gated, A] = 0.0
    return out, gated
