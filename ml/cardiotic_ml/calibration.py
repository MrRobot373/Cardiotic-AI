"""Confidence calibration (model M5): temperature scaling + expected calibration error.

A calibrated model's "90% sure" is right about 90% of the time. The temperature is fitted on
validation data only, then checked on test data.
"""

from __future__ import annotations

import numpy as np
import torch


def fit_temperature(logits: np.ndarray, y: np.ndarray, iters: int = 300) -> float:
    lt = torch.from_numpy(logits.astype(np.float32))
    yt = torch.from_numpy(y.astype(np.int64))
    log_t = torch.zeros(1, requires_grad=True)
    opt = torch.optim.LBFGS([log_t], lr=0.1, max_iter=iters)

    def closure():
        opt.zero_grad()
        loss = torch.nn.functional.cross_entropy(lt / log_t.exp(), yt)
        loss.backward()
        return loss

    opt.step(closure)
    return float(log_t.detach().exp())


def softmax(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    z = logits / temperature
    z = z - z.max(1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(1, keepdims=True)


def ece(probs: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    conf, pred = probs.max(1), probs.argmax(1)
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            total += m.mean() * abs((pred[m] == y[m]).mean() - conf[m].mean())
    return float(total)


CONFIDENCE_BINS = (("high", 0.9), ("moderate", 0.7), ("low", 0.0))


def confidence_level(p: float) -> str:
    for name, lo in CONFIDENCE_BINS:
        if p >= lo:
            return name
    return "low"


def bin_accuracy(probs: np.ndarray, y: np.ndarray) -> dict:
    """Observed accuracy inside each UI confidence level — what 'high' actually means."""
    conf, pred = probs.max(1), probs.argmax(1)
    out = {}
    for name in ("high", "moderate", "low"):
        m = np.array([confidence_level(c) == name for c in conf])
        out[name] = {"share": float(m.mean()), "accuracy": float((pred[m] == y[m]).mean()) if m.any() else float("nan")}
    return out
