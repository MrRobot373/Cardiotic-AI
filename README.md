# Cardiotic AI

AI-assisted ECG analysis and cardiac monitoring for hospitals, ICUs and operation theatres.
For hospitals and medical-equipment manufacturers. On-premise. Markets: India and USA first, then EU.

> **Status: early AI research.** Signal quality, heartbeat detection, beat classification, rhythm (AF),
> calibration and 12-lead analysis (interval measurements and 71 diagnostic statements) are built and
> measured on public data, on patients the models never saw. See
> [ml/reports/RESULTS.md](ml/reports/RESULTS.md). Nothing is validated for clinical use. Everything in
> the UI concept is synthetic.

## Start here

| | |
|---|---|
| [docs/AI_ML_ROADMAP.md](docs/AI_ML_ROADMAP.md) | **The AI**: every model, what it learns from, how it is tested, build order |
| [engine/](engine/) | **The deployable engine**: ONNX models with integrity checks, HTTP API, on-premise image ([API and deployment](engine/README.md)) |
| [ml/](ml/) | AI research code: data loaders, signal processing, models, training, evaluation ([how to run](ml/README.md)) |
| [ml/reports/RESULTS.md](ml/reports/RESULTS.md) | Measured results on patients the models never saw |
| [docs/PRODUCT_PLAN.md](docs/PRODUCT_PLAN.md) | Review of the original research, product definition, regulatory path, data, AI/ML design, architecture, roadmap, team, risks and **open decisions** (section 14) |
| [docs/ui-concept/index.html](docs/ui-concept/index.html) | Clickable UI concept. Open it in a browser; switch screens with the bar at the top and switch theme with the moon icon |

![ECG review concept](docs/ui-concept/screenshot-review.png)

## Product line

| | Product | What it does |
|---|---|---|
| A | **ECG Review** | Recorded 12-lead and long ECGs: signal quality, measurements (rate, PR, QRS, QT/QTc, axis), rhythm findings, clinician review and signed reports. First commercial product |
| B | **Live Assist** | Advisory review flags from live monitor streams, beside (never instead of) the bedside monitor's alarms. Silent-mode study first |
| C | **Periop Insight** | ECG time-aligned with ABP, SpO₂ and other vitals for intra-operative case review |

## Planned stack

Python (FastAPI, NumPy/SciPy, NeuroKit2, PyTorch for training, ONNX Runtime for inference) ·
React + Vite + Tailwind + Radix · PostgreSQL (+ TimescaleDB) · object storage (MinIO) ·
HL7 v2 / FHIR / DICOM integration · on-prem first (Docker Compose).

## Intended-use caution

Cardiotic AI is intended to support qualified clinicians. It is not a substitute for clinical
judgement or for the bedside monitor's alarms. No version of this software is cleared or
approved as a medical device yet.
