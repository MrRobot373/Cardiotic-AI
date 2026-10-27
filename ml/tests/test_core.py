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
