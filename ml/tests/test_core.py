"""Fast tests — no PhysioNet download required."""

import neurokit2 as nk
import numpy as np
import torch

from cardiotic_ml import dsp, qrs
from cardiotic_ml.beats import dataset as beat_data
from cardiotic_ml.beats.model import BeatNet
from cardiotic_ml.data import mitdb
from cardiotic_ml.quality import dataset as q_data
from cardiotic_ml.quality.model import QualityNet
from cardiotic_ml.train_utils import class_report


def test_inter_patient_split_is_disjoint_and_excludes_paced():
    assert not set(mitdb.DS1) & set(mitdb.DS2)
    assert not (set(mitdb.DS1) | set(mitdb.DS2)) & mitdb.PACED
    assert len(mitdb.DS1) == len(mitdb.DS2) == 22
    assert set(beat_data.VAL_PATIENTS) <= set(mitdb.DS1)


def test_aami_mapping():
    assert [mitdb.aami_class(s) for s in "NLRAVEF/"] == ["N", "N", "N", "S", "V", "V", "F", "Q"]
    assert mitdb.aami_class("+") is None  # rhythm-change marks are not beats


def test_match_beats_tolerance_and_one_to_one():
    fs = 360
    ref = np.array([1000, 2000, 3000, 4000]) + 300 * fs
    det = np.array([1030, 2054, 2060, 3200, 5000]) + 300 * fs  # 54 samples = 150 ms boundary
    m = qrs.match_beats(ref, det, fs)
    assert (m.tp, m.fn, m.fp) == (2, 2, 3)


def test_match_ignores_learning_period():
    fs = 360
    m = qrs.match_beats(np.array([10, 20]), np.array([10, 500]), fs)
    assert (m.tp, m.fn, m.fp) == (0, 0, 0)


def test_detector_on_simulated_ecg():
    fs = 360
    x = nk.ecg_simulate(duration=60, sampling_rate=fs, heart_rate=72, random_state=1).astype(np.float32)
    det = qrs.detect_qrs(x, fs)
    assert 66 <= len(det) <= 78


def test_rr_features_shapes_and_prematurity():
    peaks = np.array([0, 360, 720, 900, 1440, 1800])  # 4th beat is premature
    f = beat_data.rr_features(peaks, 360)
    assert f.shape == (6, beat_data.N_RR)
    assert f[3, 3] < 0.8  # pre-RR / local-RR well below 1 for the premature beat


def test_quality_generators_cover_all_labels():
    rng = np.random.default_rng(0)
    clean = nk.ecg_simulate(duration=2.5, sampling_rate=360, random_state=2)[: q_data.WIN].astype(np.float32)
    pool = {k: rng.normal(0, 0.2, (2, 20000)).astype(np.float32) for k in q_data.NOISY_KINDS}
    seen = {q_data.make_example(clean, pool, rng)[1] for _ in range(300)}
    assert seen == {0, 1, 2}


def test_add_noise_hits_requested_snr():
    rng = np.random.default_rng(0)
    clean = np.sin(np.linspace(0, 20, 900)).astype(np.float32)
    seg = rng.normal(0, 1, 900).astype(np.float32)
    noisy = q_data._add_noise(clean, seg, 6.0)
    snr = 10 * np.log10(np.mean(clean ** 2) / np.mean((noisy - clean) ** 2))
    assert abs(snr - 6.0) < 0.01


def test_models_forward_shapes():
    assert QualityNet()(torch.zeros(4, q_data.WIN)).shape == (4, 3)
    assert BeatNet()(torch.zeros(5, beat_data.PRE + beat_data.POST), torch.ones(5, beat_data.N_RR)).shape == (5, 4)


def test_class_report_per_class_metrics():
    rep = class_report(np.array([0, 0, 1, 1, 2]), np.array([0, 1, 1, 1, 0]), ["a", "b", "c"])
    assert rep["per_class"]["a"]["sensitivity"] == 0.5
    assert rep["per_class"]["b"]["ppv"] == 2 / 3
    assert rep["per_class"]["c"]["sensitivity"] == 0.0


def test_bandpass_and_resample():
    x = np.random.default_rng(0).normal(size=3600).astype(np.float32)
    assert dsp.bandpass(x, 360).shape == x.shape
    assert len(dsp.resample(x, 360, 500)) == 5000


def test_refine_peaks_moves_late_detections_onto_r_peak():
    fs = 360
    x = nk.ecg_simulate(duration=30, sampling_rate=fs, heart_rate=70, random_state=3).astype(np.float32)
    true = qrs.detect_qrs(x, fs, "neurokit")
    late = true + 15  # ~42 ms late, like Pan-Tompkins
    refined = qrs.refine_peaks(x, fs, late)
    assert np.median(np.abs(refined[: len(true)] - true[: len(refined)])) <= 2


def test_temperature_scaling_reduces_overconfidence():
    from cardiotic_ml import calibration as cal

    rng = np.random.default_rng(0)
    y = rng.integers(0, 3, 4000)
    logits = rng.normal(0, 1, (4000, 3))
    logits[np.arange(4000), y] += 1.0
    logits *= 4.0  # artificially overconfident
    t = cal.fit_temperature(logits, y)
    assert t > 2.0
    assert cal.ece(cal.softmax(logits, t), y) < cal.ece(cal.softmax(logits), y)


def test_confidence_levels():
    from cardiotic_ml.calibration import confidence_level

    assert [confidence_level(p) for p in (0.95, 0.8, 0.5)] == ["high", "moderate", "low"]


def test_rr_irregularity_features_separate_af_like_from_regular():
    from cardiotic_ml.rhythm.dataset import rr_window_features

    regular = np.arange(0, 30, 0.8)
    irregular = np.cumsum(np.random.default_rng(1).uniform(0.4, 1.2, 40))
    f_reg, f_irr = rr_window_features(regular, 30), rr_window_features(irregular[irregular < 30], 30)
    assert f_irr[2] > 5 * f_reg[2] + 0.05  # coefficient of variation
    assert rr_window_features(np.array([1.0, 2.0]), 30)[-1] == 1.0  # too-few-beats flag


def test_rhythm_windows_pad_short_and_cover_tail():
    from cardiotic_ml.rhythm import dataset as rd

    short, _, st = rd.windows(np.ones(10 * rd.FS_MODEL, dtype=np.float32), np.arange(0, 10, 1.0))
    assert short.shape == (1, rd.WIN) and list(st) == [0.0]
    long_, _, st = rd.windows(np.ones(50 * rd.FS_MODEL, dtype=np.float32), np.arange(0, 50, 1.0))
    assert st[-1] == 20.0 and long_.shape[1] == rd.WIN


def test_rhythm_model_forward_shape():
    from cardiotic_ml.rhythm.dataset import N_RRF, WIN
    from cardiotic_ml.rhythm.model import RhythmNet

    assert RhythmNet()(torch.zeros(2, WIN), torch.zeros(2, N_RRF)).shape == (2, 4)


def test_detect_beats_ignores_startup_transient():
    fs = 360
    x = nk.ecg_simulate(duration=20, sampling_rate=fs, heart_rate=70, random_state=4).astype(np.float32)
    assert qrs.detect_beats(x, fs).min() >= int(qrs.STARTUP_S * fs)


def test_mitdb_window_label_rules():
    from cardiotic_ml.rhythm.dataset import mitdb_window_label

    N, A, O = 0, 1, 2
    assert mitdb_window_label(["(AFIB"], 5) == A
    assert mitdb_window_label(["(AFIB", "(N"], 0) is None      # straddles an AF boundary
    assert mitdb_window_label(["(B"], 10) == O                 # bigeminy is "other rhythm"
    assert mitdb_window_label(["(N"], 0) == N
    assert mitdb_window_label(["(N"], 4) == O                  # frequent ectopy, not AF
    assert mitdb_window_label(["(N"], 1) is None               # ambiguous for the CinC label set
    assert mitdb_window_label(["(P"], 0) is None               # paced


def test_ectopy_features_remove_pvc_irregularity():
    from cardiotic_ml.rhythm.dataset import N_RRF, N_RRF_ECTOPY, rr_window_features_ectopy

    # sinus at 0.8 s with every 4th beat a PVC (early, then compensatory pause)
    t, beats, ect = 0.0, [], []
    for i in range(36):
        pvc = i % 4 == 3
        t += 0.5 if pvc else (1.1 if i % 4 == 0 and i else 0.8)
        beats.append(t); ect.append(pvc)
    f = rr_window_features_ectopy(np.array(beats), np.array(ect), 30)
    assert f.shape == (N_RRF_ECTOPY,)
    assert f[2] > 0.2                 # all-beat RR CV: looks irregular
    assert f[N_RRF + 1] < 0.05        # CV without PVC-adjacent intervals: regular again
    assert abs(f[N_RRF] - 0.25) < 0.02


def test_ectopy_gate_only_on_validated_leads_and_only_regular_ectopic_windows():
    from cardiotic_ml.rhythm import gate
    from cardiotic_ml.rhythm.dataset import N_RRF, N_RRF_ECTOPY

    g = {"pvc_min": 0.02, "tau": 0.16, "leads": ["MLII", "II"]}
    assert gate.applies(g, "MLII") and gate.applies(g, "ii") and not gate.applies(g, "I") and not gate.applies(g, None)
    probs = np.array([[0.1, 0.8, 0.1, 0.0], [0.1, 0.8, 0.1, 0.0], [0.7, 0.2, 0.1, 0.0]])
    feats = np.zeros((3, N_RRF_ECTOPY))
    feats[:, N_RRF] = [0.2, 0.0, 0.2]       # PVC share
    feats[:, N_RRF + 1] = [0.05, 0.05, 0.05]  # regular once PVCs are removed
    out, gated = gate.apply(probs, feats, g)
    assert gated.tolist() == [True, False, False]  # no PVCs -> untouched; not called AF -> untouched
    assert out[0].argmax() == 2 and abs(out[0].sum() - 1) < 1e-9


def test_select_rhythm_rule(tmp_path, monkeypatch):
    import json as _json

    from cardiotic_ml import experiments_rhythm as er

    def put(name, d):
        (tmp_path / f"{name}.json").write_text(_json.dumps(d))

    def afdb(se, fa, pats):
        return {"af_sensitivity": se, "false_af_windows": fa,
                "per_record": [{"record": r, "af_sensitivity": s} for r, s in pats]}

    put("rhythm_afdb_val_v0.1", afdb(0.95, 100, [("a", 0.9), ("b", 1.0)]))
    put("rhythm_mitdb_val_v0.1", {"af_sensitivity": 1.0, "false_af_windows": 38})
    put("rhythm_classification_v0.1", {"val_challenge_f1": 0.84})
    # v0.4: fewer false AF but one patient collapses -> must fail; v0.5: modest but safe -> chosen
    put("rhythm_afdb_val_v0.4", afdb(0.94, 20, [("a", 0.7), ("b", 1.0)]))
    put("rhythm_mitdb_val_v0.4", {"af_sensitivity": 1.0, "false_af_windows": 3})
    put("rhythm_classification_v0.4", {"val_challenge_f1": 0.85})
    put("rhythm_afdb_val_v0.5", afdb(0.94, 60, [("a", 0.88), ("b", 1.0)]))
    put("rhythm_mitdb_val_v0.5", {"af_sensitivity": 0.99, "false_af_windows": 20})
    put("rhythm_classification_v0.5", {"val_challenge_f1": 0.835})
    monkeypatch.setattr(er, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(er, "_write", lambda name, payload: None)
    res = er.select_rhythm()
    assert res["chosen"] == "v0.5"
    assert [c["passes"] for c in res["candidates"]] == [False, True]


def _synthetic_12lead(fs=500, hr=70, qrs_axis=60.0, seconds=10, seed=0):
    """Hann-shaped P, Q, R, S, T waves with known boundaries; limb leads projected from a frontal
    vector so the true QRS axis is `qrs_axis`. Truth: PR 140 ms, QRS 90 ms, QT 380 ms."""
    from cardiotic_ml.data.ptbxl import LEADS

    angles = {"I": 0, "II": 60, "III": 120, "AVR": -150, "AVL": -30, "AVF": 90}
    rng = np.random.default_rng(seed)
    n = int(seconds * fs)
    x = np.zeros((12, n), dtype=np.float32)
    waves = [(-0.18, 0.10, 0.15, 60), (-0.04, 0.02, -0.1, qrs_axis), (-0.02, 0.04, 1.2, qrs_axis),
             (0.02, 0.03, -0.3, qrs_axis), (0.18, 0.16, 0.3, 40)]  # (start s rel. R, width s, amplitude mV, angle)
    for r in np.arange(0.6, seconds - 0.6, 60 / hr):
        for st, w, a, ang in waves:
            i0, m = int((r + st) * fs), int(w * fs)
            bump = a * np.hanning(m + 2)[1:-1]
            for li, lead in enumerate(LEADS):
                gain = np.cos(np.radians(ang - angles[lead])) if lead in angles else 0.6 + 0.1 * li
                x[li, i0:i0 + m] += gain * bump
    return x + rng.normal(0, 0.005, x.shape).astype(np.float32)


def test_ecg12_measurements_on_synthetic_ecg():
    from cardiotic_ml.ecg12 import measure

    m = measure.measure(_synthetic_12lead(), 500)
    assert m["ok"] and abs(m["heart_rate_bpm"] - 70) < 2
    assert abs(m["qrs_ms"] - 90) <= 15
    assert m["pr_ms"] is not None and abs(m["pr_ms"] - 140) <= 20
    assert abs(m["qt_ms"] - 380) <= 20
    assert abs(m["qrs_axis_deg"] - 60) <= 10
    assert abs(measure.measure(_synthetic_12lead(qrs_axis=-45), 500)["qrs_axis_deg"] + 45) <= 10


def test_ecg12_model_and_targets():
    from cardiotic_ml.ecg12.model import ECG12Net
    from cardiotic_ml.experiments_ecg12 import f1_thresholds, macro_auc

    assert ECG12Net(76)(torch.zeros(2, 12, 1000)).shape == (2, 76)
    assert ECG12Net(76)(torch.zeros(2, 12, 900)).shape == (2, 76)  # crops of any length
    y = np.array([[1, 0], [0, 1], [1, 1], [0, 0]])
    p = np.array([[0.9, 0.2], [0.1, 0.8], [0.8, 0.7], [0.2, 0.1]])
    assert macro_auc(y, p) == 1.0
    th = f1_thresholds(y, p)
    assert ((p >= th) == y).all()


def test_resample_and_bandpass_work_along_time_for_12_leads():
    x = np.random.default_rng(0).normal(size=(12, 5000)).astype(np.float32)
    y = dsp.resample(x, 500, 100)
    assert y.shape == (12, 1000)
    assert np.allclose(y[3], dsp.resample(x[3], 500, 100), atol=1e-5)
    assert dsp.bandpass(x, 500, "diagnostic").shape == x.shape


def test_analyze_12lead_end_to_end_with_shipped_models():
    from cardiotic_ml.data.ptbxl import LEADS
    from cardiotic_ml.ecg12.analyze import Models12, analyze_12lead

    out = analyze_12lead(_synthetic_12lead(), 500, Models12())
    assert set(out["lead_quality"]) == set(LEADS)
    assert out["measurements"]["ok"] and abs(out["measurements"]["heart_rate_bpm"] - 70) < 2
    for s in out["statements"]:
        assert s["probability"] >= s["threshold"]
    for junk in (np.zeros((12, 5000), dtype=np.float32), np.random.default_rng(0).normal(0, 1, (12, 5000)).astype(np.float32)):
        o = analyze_12lead(junk, 500, Models12())
        assert not o["measurements"]["ok"] and o["statements"] == []
