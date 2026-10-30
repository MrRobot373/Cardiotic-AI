# cardiotic-engine

The deployable part of Cardiotic AI: one component that hospitals run on their own server and
ECG-equipment makers embed in their software. It analyses ECGs with the exported, registered AI
models and returns a versioned result.

**Research use only. Not a medical device. Not validated for clinical use.**

## What it does

| Analysis | Input | Output |
|---|---|---|
| `ecg12` | 10 s 12-lead ECG (8–60 s accepted; the first 10 s is analysed), ≥ 200 Hz | Per-lead signal quality, HR, PR, QRS, QT, QTc, axes with caliper positions, diagnostic statements with calibrated probability and confidence, notes |
| `rhythm` | Single-lead strip or Holter, 10 s to 48 h, ≥ 100 Hz | Signal-quality segments, every beat with its class (N/S/V/F), 30 s rhythm windows (sinus / AF / other / too noisy), heart rate, findings |

8-lead input (I, II, V1–V6, as many ECG carts store it) is accepted: III, aVR, aVL and aVF are derived
from I and II, and the result says so. Units: mV or µV.

## How it is built

- **Same analysis code as the research pipeline**: the pipelines in `cardiotic_ml` call models through a
  neutral interface. Research runs them on PyTorch; the engine runs them on ONNX Runtime.
  `validation/equivalence.py` checks both give the same results: 800 real 12-lead ECGs (PTB-XL,
  Chapman–Shaoxing) and all 22 full 30-minute MIT-BIH test records (49,438 beats). It found identical
  findings, beats, rhythms, measurements and statements, with probabilities within 2 × 10⁻⁶
  (`validation/equivalence.json`).
- **Model registry**: `cardiotic_engine/models/manifest.json` lists each ONNX model, its SHA-256, the
  SHA-256 of the weights it was exported from, its labels, calibration and thresholds. At start-up the
  engine checks every file and that each model is the version the analysis code was validated with. If
  anything differs, it refuses to start (`IntegrityError`).
- **Deterministic**: the same input gives byte-identical output. ONNX Runtime is single-threaded by
  default (`CARDIOTIC_ENGINE_THREADS` to change).
- **Light**: NumPy, SciPy, ONNX Runtime. No PyTorch, no NeuroKit2. The Pan-Tompkins beat detector is our
  own implementation, which gives the same beats as NeuroKit2's on 109,802 MIT-BIH beats, 1,800 PTB-XL
  leads, 1 h of AF Holter and 300 handheld ECGs.

## Per-site operating points

The statement model ranks ECGs well across hospitals, but its yes/no thresholds do not transfer: sites
label differently (ml/reports/RESULTS.md §7.3, §7.7). At installation, thresholds are chosen on the site's
own cardiologist-labelled ECGs with `cardiotic_ml.ecg12.site.choose`, signed off by the cardiology lead,
and given to the engine as a file:

```bash
cardiotic-engine serve --site-config /etc/cardiotic/site_config.json   # or CARDIOTIC_SITE_CONFIG=...
```

The file changes thresholds only, never the model. The engine refuses to start if the file is for a
different statement model, names unknown statements, or has no `approved_by` / `approved_at`
(`SiteConfigError`, exit code 4). With a file loaded, `/v1/models` and every result show the site ID,
configuration version and its SHA-256, and each statement says whether its threshold came from the site
or the model. `examples/site_config.example.json` comes from the simulated Chapman–Shaoxing installation
and is for illustration only.

## Run it

```bash
pip install ./ml ./engine           # core signal processing + engine; no research extras
cardiotic-engine verify             # check model files against the manifest
cardiotic-engine serve --port 8710  # HTTP service on 127.0.0.1
cardiotic-engine analyze request.json --kind ecg12
```

On-premise image (offline; build outside the hospital network, then `docker save` / `docker load`):

```bash
docker build -f engine/Dockerfile -t cardiotic-engine:0.1.0 .
docker run -p 8710:8710 cardiotic-engine:0.1.0
```

## HTTP API (v1)

| Method | Path | Body |
|---|---|---|
| GET | `/v1/health` | — |
| GET | `/v1/models` | — (engine version, model versions and SHA-256) |
| POST | `/v1/ecg12` | `{"fs": 500, "units": "mV", "leads": {"I": [...], "II": [...], ..., "V6": [...]}}` |
| POST | `/v1/rhythm` | `{"fs": 360, "units": "mV", "lead": "II", "signal": [...]}` |

Response: `{"analysis", "engine": {version, models_version, model SHA-256s, intended_use}, "input_notes",
"processing_ms", "result"}`. Bad input gives HTTP 400 with `{"error": "<reason>"}`. Examples of rejected
input: missing leads, unequal lengths, sampling rate out of range, duration out of range, more than 5% of
samples missing, or amplitudes above 20 mV (a units or gain error).

## Measured on one CPU core

| Input | Time | Peak memory |
|---|---|---|
| 12-lead ECG (10 s, 500 Hz) | 27 ms median, 32 ms p95 | 170 MB |
| 1 h single-lead Holter (360 Hz) | 3.5 s | 450 MB |
| 24 h single-lead Holter (360 Hz) | 67 s | 2.9 GB |
| Model loading and integrity check | 0.7 s | |

## Security notes for deployment

- The service binds to 127.0.0.1 by default and has **no TLS and no authentication of its own**. Put it
  behind the hospital's reverse proxy or the product backend, which provide TLS, authentication and audit
  logging (IEC 81001-5-1 / FDA 524B plan in docs/PRODUCT_PLAN.md).
- Request bodies (patient signals) are never logged. Errors return a reason, never internals.
- The container runs as an unprivileged user and downloads nothing at run time.

## Known limits (v0.1)

- Long Holter recordings are analysed in one piece; 24 h needs about 3 GB of memory. Chunked processing is next.
- Input is JSON only. DICOM waveform, HL7 aECG and SCP-ECG readers are needed for ECG carts and PACS.
- The Docker image has not been built and tested yet (registry rate limits in the build environment). The
  same install steps were tested in a clean virtual environment.
