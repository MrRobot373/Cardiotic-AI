# Cardiotic AI

AI-assisted ECG analysis and cardiac monitoring for hospitals, ICUs and operation theatres.
For hospitals and medical-equipment manufacturers. On-premise. Markets: India and USA first, then EU.

> **Status: working system, not yet validated or cleared for clinical use.** The AI (signal quality,
> heartbeat detection, beat classification, rhythm, 12-lead measurements and 71 diagnostic statements) is
> measured on public data, on patients the models never saw ([ml/reports/RESULTS.md](ml/reports/RESULTS.md)).
> Around it runs a complete on-premise product: ECG file readers, server with accounts and storage, reading
> and sign-off, audit log, HL7/FHIR export, install and backup tools. What is *not* done is listed in
> [Not done yet](#not-done-yet).

## Start here

| | |
|---|---|
| [docs/AI_ML_ROADMAP.md](docs/AI_ML_ROADMAP.md) | **The AI**: every model, what it learns from, how it is tested, build order |
| [deploy/INSTALL.md](deploy/INSTALL.md) | **Installing at a hospital**: requirements, install, site set-up, HIS, backup, security checklist |
| [server/](server/) | **The server**: accounts, upload and analysis, review and sign-off, audit chain, HL7/FHIR delivery ([API and rules](server/README.md)) |
| [frontend/](frontend/) | **The web app**: worklist, 12-lead review, Holter, reports, settings. One build runs against the server or, without one, on recorded sample data ([how to run](frontend/README.md)) |
| [engine/](engine/) | **The AI engine**: ONNX models with integrity checks, ECG file readers, per-site operating points, HTTP API ([API](engine/README.md)) |
| [ml/](ml/) | AI research code: data loaders, signal processing, models, training, evaluation ([how to run](ml/README.md)) |
| [ml/reports/RESULTS.md](ml/reports/RESULTS.md) | Measured results on patients the models never saw |
| [docs/PRODUCT_PLAN.md](docs/PRODUCT_PLAN.md) | Review of the original research, product definition, regulatory path, data, AI/ML design, architecture, roadmap, team, risks and **open decisions** (section 14) |
| [docs/ui-concept/index.html](docs/ui-concept/index.html) | Earlier static UI concept (superseded by frontend/). Open it in a browser; switch screens with the bar at the top and switch theme with the moon icon |

![ECG review — demo app](frontend/screenshots/review-light.png)

## Product line

| | Product | What it does |
|---|---|---|
| A | **ECG Review** | Recorded 12-lead and long ECGs: signal quality, measurements (rate, PR, QRS, QT/QTc, axis), rhythm findings, clinician review and signed reports. First commercial product |
| B | **Live Assist** | Advisory review flags from live monitor streams, beside (never instead of) the bedside monitor's alarms. Silent-mode study first |
| C | **Periop Insight** | ECG time-aligned with ABP, SpO₂ and other vitals for intra-operative case review |

## Not done yet

| Gap | Why it matters |
|---|---|
| Regulatory clearance (CDSCO / FDA) and a clinical validation on a partner hospital's ECGs | Nothing here may be used for patient care until then |
| Container image never built or run (no container daemon during development) | `deploy/smoke_test.sh` proves the same steps on a clean Python environment; build and test the image before an install |
| ECG readers tested on files built from the specifications, not on real vendor exports; Philips PageWriter XML (XLI), Huffman SCP-ECG, PDF / paper images not read | Each cart model needs a real-export test before it is listed as supported |
| No direct machine feed (watched folder, DICOM storage endpoint); technicians upload files | |
| HIS: text report, no PDF; no ADT feed; tested against our own MLLP listener only | Integration testing with the hospital's interface engine |
| Live Assist (OT/ICU monitoring) and Periop Insight: not built (the board in the sample build replays recordings) | Roadmap phases 3–4 |
| Atrial flutter, long QT weak; women's MI AUC 0.92 vs men's 0.95; 12-lead signal-quality model flags clean limb leads | ml/reports/RESULTS.md §7.6, §2.1, §8 |

## Planned stack

Python (FastAPI, NumPy/SciPy, NeuroKit2, PyTorch for training, ONNX Runtime for inference) ·
React + Vite + Tailwind + Radix · PostgreSQL (+ TimescaleDB) · object storage (MinIO) ·
HL7 v2 / FHIR / DICOM integration · on-prem first (Docker Compose).

## Intended-use caution

Cardiotic AI is intended to support qualified clinicians. It is not a substitute for clinical
judgement or for the bedside monitor's alarms. No version of this software is cleared or
approved as a medical device yet.
