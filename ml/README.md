# cardiotic-ml — the AI research code

Signal processing, models, training and evaluation for Cardiotic AI. This is where the AI is
built and measured. The regulated `ecg-engine` will only ever load **exported, registered**
models from here (see [docs/AI_ML_ROADMAP.md](../docs/AI_ML_ROADMAP.md)).

**Research use only.** Nothing here is validated for clinical use.

## What's inside

| Module | What it does |
|---|---|
| `data/mitdb.py`, `data/noise.py` | MIT-BIH Arrhythmia and Noise Stress Test loaders, AAMI beat classes, de Chazal inter-patient split |
| `dsp.py` | Explicit filter modes (monitoring 0.5–40 Hz, diagnostic 0.05–150 Hz), anti-aliased resampling |
| `qrs.py` | Heartbeat detection (NeuroKit2 detectors) and EC57-style beat-by-beat scoring |
| `quality/` | **M1 signal-quality model**: good / noisy / unusable per 2.5 s window |
| `beats/` | **M2 beat classifier**: N / S / V / F from beat shape + RR timing |
| `rhythm/`, `data/cinc2017.py` | **M3 rhythm classifier**: normal / AF / other rhythm / too noisy, per 30 s window (CinC 2017) |
| `data/afdb.py`, `rhythm/gate.py` | MIT-BIH AF Database loader and patient split; ectopy gate (tried, not adopted) |
| `calibration.py` | **M5**: temperature scaling, expected calibration error, confidence levels |
| `data/ptbxl.py` | PTB-XL 12-lead loader (official patient-wise folds), SCP statements, PTB-XL+ reference measurements (GE 12SL, Uni-G) |
| `ecg12/measure.py` | **M4 measurements**: median beat, QRS onset/offset (spatial velocity), T end, P wave → HR, PR, QRS, QT/QTc, axes |
| `ecg12/model.py`, `experiments_ecg12.py` | **M4 statements**: 12-lead 1D ResNet, 71 SCP statements + 5 superclasses; measurement tuning and agreement |
| `data/chapman.py`, `data/ningbo.py` | Chapman–Shaoxing (external test, GE MUSE measurements) and Chapman–Shaoxing–Ningbo loaders; fixed label maps to SCP statements |
| `ecg12/rules.py` | Rate / interval statements from our own measurements (compared with the learned model) |
| `runner.py`, `export.py` | Models as back-end-neutral functions (PyTorch here, ONNX in the engine); ONNX export checked against PyTorch |
| `ecg12/analyze.py` | 12-lead end to end: per-lead quality → measurements → calibrated statements |
| `pipeline.py` | End to end: quality gate → beats → classification → rhythm → measurements → findings (JSON + plot) |
| `experiments_rhythm.py` | Rhythm training, cross-dataset AF test on MIT-BIH, beat calibration |
| `experiments.py`, `report.py` | Reproducible experiments → `reports/*.json` → `reports/RESULTS.md` |

## Run it

```bash
python -m venv .venv && .venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch
.venv/bin/pip install -e "ml[research,dev]"
cd ml
../.venv/bin/python -m cardiotic_ml.cli download        # PhysioNet → data/raw (gitignored)
../.venv/bin/python -m cardiotic_ml.cli eval-qrs        # heartbeat detection benchmark, 48 records
# CinC 2017 (for M1 v0.2+ and M3): training2017.zip + REFERENCE-v3.csv from
# https://physionet.org/content/challenge-2017/1.0.0/ into data/raw/cinc2017/
../.venv/bin/python -m cardiotic_ml.cli train-quality --version v0.3   # M1 (CPU, minutes)
../.venv/bin/python -m cardiotic_ml.cli train-beats --version v0.1     # M2 (CPU, minutes)
../.venv/bin/python -m cardiotic_ml.cli train-rhythm                   # M3 (CPU, ~10 min) + calibration
../.venv/bin/python -m cardiotic_ml.cli eval-rhythm-mitdb              # M3 cross-dataset AF test
../.venv/bin/python -m cardiotic_ml.cli calibrate-beats                # M5 for the beat model
../.venv/bin/python -m cardiotic_ml.cli eval-pipeline                  # end to end on 22 unseen patients
# MIT-BIH AF Database (23 *.dat/.hea/.atr from https://physionet.org/content/afdb/1.0.0/ into data/raw/afdb/):
../.venv/bin/python -m cardiotic_ml.cli eval-rhythm-afdb --version v0.1 --split val
../.venv/bin/python -m cardiotic_ml.cli train-rhythm --version v0.4    # or v0.5
../.venv/bin/python -m cardiotic_ml.cli select-rhythm                  # fixed rule, validation data only
# PTB-XL 1.0.3 (https://physionet.org/content/ptb-xl/1.0.3/) unzipped into data/raw/ptbxl/, and PTB-XL+ 1.0.1
# features/{12sl,unig}_features.csv (https://physionet.org/content/ptb-xl-plus/1.0.1/) into data/raw/ptbxl_plus/features/:
../.venv/bin/python -m cardiotic_ml.cli tune-ecg12-measure --version v0.2            # training folds only
../.venv/bin/python -m cardiotic_ml.cli eval-ecg12-measure --version v0.2 --split val
../.venv/bin/python -m cardiotic_ml.cli train-ecg12 --version v0.1                    # CPU, ~2 h
# Chapman–Shaoxing (figshare collection 4560497: ECGData.zip + Diagnostics.xlsx) into data/raw/chapman/:
../.venv/bin/python -m cardiotic_ml.cli eval-ecg12-external --version v0.1           # external test
../.venv/bin/python -m cardiotic_ml.cli eval-ecg12-rules
# Chapman–Shaoxing–Ningbo (https://physionet.org/content/ecg-arrhythmia/1.0.0/) unzipped into data/raw/ningbo/:
../.venv/bin/python -m cardiotic_ml.cli train-ecg12 --version v0.2                    # PTB-XL + Ningbo part
../.venv/bin/python -m cardiotic_ml.cli export-engine   # adopted models -> engine/cardiotic_engine/models (ONNX)
../.venv/bin/python -m cardiotic_ml.cli report          # writes reports/RESULTS.md
../.venv/bin/python -m cardiotic_ml.cli analyze --record 233 --start 600 --seconds 60 --plot strip.png
../.venv/bin/pytest -q                                   # fast tests, no download needed
```

Trained weights are written to `ml/artifacts/` with a model card (`*.card.json`) listing data,
patients, intended use and the file's SHA-256.

## Data licences

MIT-BIH Arrhythmia, MIT-BIH Noise Stress Test, MIT-BIH Atrial Fibrillation and PhysioNet/CinC Challenge 2017 databases:
PhysioNet, Open Data Commons Attribution License v1.0. For CinC 2017 also cite: Clifford GD et al.
*AF Classification from a Short Single Lead ECG Recording: the PhysioNet/Computing in Cardiology
Challenge 2017.* Computing in Cardiology 44 (2017). For the AF Database: Moody GB, Mark RG. *A new method
for detecting atrial fibrillation using R-R intervals.* Computers in Cardiology 10:227-230 (1983).

PTB-XL and PTB-XL+: Creative Commons Attribution 4.0. Cite: Wagner P et al. *PTB-XL, a large publicly
available electrocardiography dataset.* Scientific Data 7:154 (2020), and Strodthoff N et al. *PTB-XL+, a
comprehensive electrocardiographic feature dataset.* Scientific Data 10:279 (2023).

Chapman–Shaoxing (CC0) and Chapman–Shaoxing–Ningbo (CC BY 4.0). Cite: Zheng J et al. *A 12-lead
electrocardiogram database for arrhythmia research covering more than 10,000 patients.* Scientific Data
7:48 (2020), and Zheng J et al. *A large scale 12-lead electrocardiogram database for arrhythmia study.*
PhysioNet (2022).

For all PhysioNet data, cite: Moody GB, Mark RG. *The impact of the MIT-BIH Arrhythmia
Database.* IEEE Eng in Med and Biol 20(3):45-50 (2001), and Goldberger AL et al. *PhysioBank,
PhysioToolkit, and PhysioNet.* Circulation 101(23):e215-e220 (2000).
