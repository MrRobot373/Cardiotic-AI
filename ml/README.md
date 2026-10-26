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
| `pipeline.py` | End to end: quality gate → beats → classification → measurements → findings (JSON + plot) |
| `experiments.py`, `report.py` | Reproducible experiments → `reports/*.json` → `reports/RESULTS.md` |

## Run it

```bash
python -m venv .venv && .venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch
.venv/bin/pip install -e "ml[dev]"
cd ml
../.venv/bin/python -m cardiotic_ml.cli download        # PhysioNet → data/raw (gitignored)
../.venv/bin/python -m cardiotic_ml.cli eval-qrs        # heartbeat detection benchmark, 48 records
../.venv/bin/python -m cardiotic_ml.cli train-quality   # M1 (CPU, minutes)
../.venv/bin/python -m cardiotic_ml.cli train-beats     # M2 (CPU, minutes)
../.venv/bin/python -m cardiotic_ml.cli report          # writes reports/RESULTS.md
../.venv/bin/python -m cardiotic_ml.cli analyze --record 233 --start 600 --seconds 60 --plot strip.png
../.venv/bin/pytest -q                                   # fast tests, no download needed
```

Trained weights are written to `ml/artifacts/` with a model card (`*.card.json`) listing data,
patients, intended use and the file's SHA-256.

## Data licences

MIT-BIH Arrhythmia and MIT-BIH Noise Stress Test databases: PhysioNet, Open Data Commons
Attribution License v1.0. Cite: Moody GB, Mark RG. *The impact of the MIT-BIH Arrhythmia
Database.* IEEE Eng in Med and Biol 20(3):45-50 (2001), and Goldberger AL et al. *PhysioBank,
PhysioToolkit, and PhysioNet.* Circulation 101(23):e215-e220 (2000).
