"""Per-site operating points for the 12-lead statement model.

The model ranks ECGs well across hospitals, but the yes/no thresholds learned on PTB-XL do not transfer:
hospitals label differently (Chapman writes sinus bradycardia by definition, PTB-XL mostly does not) and
their case mix differs (Chapman atrial flutter: AUC 0.90, but 9% sensitivity at the PTB-XL threshold).
At installation, a site's own cardiologist-labelled ECGs set the thresholds. This module chooses them,
and says where the site's data is too thin to choose, so the model's own threshold is kept.

A site configuration never changes the model: only the per-statement thresholds, versioned and signed
off by the site's cardiology lead (docs/PRODUCT_PLAN.md).
"""

from __future__ import annotations

import numpy as np

POLICIES = ("max_f1", "sensitivity")
MIN_POSITIVES = 20  # fewer site ECGs with the statement than this: keep the model's threshold


def _threshold_for(y: np.ndarray, p: np.ndarray, policy: str, target: float) -> float:
    order = np.argsort(-p)
    ps, ys = p[order], y[order].astype(bool)
    tp = np.cumsum(ys)
    fp = np.cumsum(~ys)
    se = tp / max(ys.sum(), 1)
    ppv = tp / np.maximum(tp + fp, 1)
    last = np.r_[ps[1:] != ps[:-1], True]  # only cut between different probabilities
    if policy == "max_f1":
        f1 = np.where(last, 2 * se * ppv / np.maximum(se + ppv, 1e-9), -1)
        k = int(np.argmax(f1))
    else:  # smallest set of positives calls reaching the target sensitivity
        k = int(np.flatnonzero(last & (se >= target))[0])
    return float(ps[k])


def choose(y: np.ndarray, p: np.ndarray, labels: list[str], model_thresholds: dict[str, float],
           policy: str = "max_f1", target: float = 0.9, min_positives: int = MIN_POSITIVES,
           unknown: np.ndarray | None = None) -> dict[str, dict]:
    """Site thresholds from labelled site ECGs. y, p: (n, labels); unknown: (n, labels) 1 where the site
    label cannot say yes or no (left out). Statements with < min_positives positives keep the model's."""
    if policy not in POLICIES:
        raise ValueError(f"policy must be one of {POLICIES}")
    out = {}
    for j, name in enumerate(labels):
        keep = np.ones(len(y), dtype=bool) if unknown is None else unknown[:, j] == 0
        yj, pj = y[keep, j], p[keep, j]
        n_pos = int(yj.sum())
        if n_pos < min_positives or n_pos == len(yj):
            out[name] = {"threshold": float(model_thresholds[name]), "source": "model", "site_positives": n_pos}
            continue
        th = _threshold_for(yj, pj, policy, target)
        pred = pj >= th
        out[name] = {"threshold": th, "source": "site", "site_positives": n_pos, "policy": policy,
                     "site_sensitivity": float(pred[yj == 1].mean()), "site_ppv": float(pred[yj == 1].sum() / max(pred.sum(), 1)),
                     "model_threshold": float(model_thresholds[name])}
    return out


def thresholds(config: dict | None, model_thresholds: dict[str, float]) -> dict[str, float]:
    """Thresholds the analysis uses: the site's where it set one, the model's otherwise."""
    site = (config or {}).get("statements", {})
    return {k: float(site[k]["threshold"]) if k in site else float(v) for k, v in model_thresholds.items()}


REQUIRED = ("site_id", "config_version", "model", "approved_by", "approved_at", "statements")


def validate(config: dict, card: dict) -> dict:
    """Refuse a site configuration that does not belong to this exact statement model, or is not signed off.
    Returns the configuration unchanged when it is valid."""
    missing = [k for k in REQUIRED if not config.get(k)]
    if missing:
        raise ValueError(f"site configuration is missing {missing}")
    model = f"{card['name']}_{card['version']}"
    if config["model"] != model:
        raise ValueError(f"site configuration is for {config['model']}, the engine runs {model}: re-validate the site's thresholds")
    unknown = sorted(set(config["statements"]) - set(card["thresholds"]))
    if unknown:
        raise ValueError(f"site configuration names statements the model does not have: {unknown}")
    for k, v in config["statements"].items():
        th = v.get("threshold") if isinstance(v, dict) else None
        if not isinstance(th, (int, float)) or not 0 < th < 1:
            raise ValueError(f"site threshold for {k} must be a number between 0 and 1")
    return config


def make_config(chosen: dict[str, dict], card: dict, site_id: str, config_version: str, approved_by: str,
                approved_at: str) -> dict:
    """A site configuration file from `choose` output: only the thresholds the site's data set."""
    return {"site_id": site_id, "config_version": config_version, "model": f"{card['name']}_{card['version']}",
            "approved_by": approved_by, "approved_at": approved_at,
            "statements": {k: v for k, v in chosen.items() if v["source"] == "site"}}
