"""The AF operating-point rule picks the right end of each threshold interval and refuses modes that fail their offering test."""

import numpy as np

from cardiotic_ml.experiments_afop import A, choose, score


def _set(seed=0, n_af=600, n_non=600):
    rng = np.random.default_rng(seed)
    pa = np.r_[rng.beta(6, 1.5, n_af), rng.beta(1.2, 7, n_non)]  # AF windows score high, others low, with overlap
    y = np.r_[np.ones(n_af, int), np.zeros(n_non, int)]
    p = np.zeros((len(y), 4))
    p[:, A] = pa
    p[:, 0] = (1 - pa) * 0.7
    p[:, 2] = (1 - pa) * 0.3
    return {"p": p, "y": y, "dataset": np.array(["afdb"] * (n_af // 2) + ["mitdb"] * (n_af // 2) + ["afdb"] * n_non), "record": np.array(["r"] * len(y))}


def test_score_counts():
    d = _set()
    s = score(d, d["p"].argmax(1) == A)
    assert s["af_windows"] == 600 and s["sensitivity"] + s["missed_af_windows"] / 600 == 1.0 and 0 < s["ppv"] <= 1


def test_review_takes_the_highest_threshold_screening_the_highest_too_but_for_sensitivity():
    d = _set()
    corrected, literal = choose(d), choose(d, review_pick="lowest")
    r, rl = corrected["review"], literal["review"]
    assert r["threshold"] is not None and rl["threshold"] is not None and r["threshold"] > rl["threshold"]  # the fixed direction: fewer false alarms
    assert r["val"]["false_af_windows"] <= rl["val"]["false_af_windows"]
    assert r["val"]["ppv"] >= 0.90 and r["val"]["sensitivity"] >= 0.90
    s = corrected["screening"]
    assert s["val"]["sensitivity"] >= 0.99
    higher = [t for t in np.unique(np.round(d["p"][:, A], 4)) if t > s["threshold"]]
    assert all(score(d, d["p"][:, A] >= t)["sensitivity"] < 0.99 for t in higher[:20])  # no higher threshold keeps 99%


def test_a_mode_that_does_not_help_is_not_offered():
    rng = np.random.default_rng(1)
    pa = rng.random(1000)  # no signal at all: nothing can reach the required PPV and sensitivity
    p = np.zeros((1000, 4)); p[:, A] = pa; p[:, 0] = 1 - pa
    d = {"p": p, "y": (rng.random(1000) < 0.5).astype(int), "dataset": np.array(["afdb"] * 1000), "record": np.array(["r"] * 1000)}
    m = choose(d)
    assert m["review"]["offered"] is False and m["screening"]["offered"] is False and m["balanced (argmax)"]["offered"] is True
