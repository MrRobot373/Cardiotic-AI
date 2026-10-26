# Cardiotic AI — AI/ML Roadmap

Cardiotic AI is an **AI product first**. The screens, worklist and reports exist so clinicians can
use, check and sign what the AI produces. This document lists every model, what it learns from,
how it is measured, and the order we build them. Measured results live in
[`ml/reports/RESULTS.md`](../ml/reports/RESULTS.md).

## 1. The AI pipeline

```text
 ECG signal ──▶ [M1 Quality] ──▶ [Beat detection] ──▶ [Measurements] ──▶ [M2 Beats] ──▶ [M3 Rhythm] ──▶ [M5 Calibration / "not sure"] ──▶ doctor review
                  │  unusable segments stop here                                         [M4 12-lead statements]
                  ▼                                                                         [M6 Multi-signal OT/ICU] (ECG + ABP + SpO₂)
            "Not analysable" — no findings are produced
```

| # | Model | Question it answers | Type | Status |
|---|---|---|---|---|
| M1 | **Signal quality** | "Can this 2.5 s of signal be trusted?" good / noisy / unusable | 1D-CNN + amplitude statistics | **v0.1 trained** (MIT-BIH + NSTDB) |
| — | **Beat detection** | "Where is every heartbeat?" | Classical DSP (NeuroKit2 / Pan-Tompkins), benchmarked EC57-style | **Benchmarked** on all 48 MIT-BIH records |
| M2 | **Beat classifier** | "Is this beat normal, supraventricular (S), ventricular (V) or fusion (F)?" | 1D-CNN on beat shape + MLP on RR timing | **v0.1 trained** (inter-patient MIT-BIH) |
| M3 | **Rhythm classifier** | "What rhythm is this stretch?" sinus, AF, flutter, blocks, VT… | 1D ResNet over 10–30 s, then compare with an ECG foundation model | Next: PTB-XL, CinC 2017/2021, MIT-BIH AF |
| M4 | **12-lead statements + measurements** | PR, QRS, QT/QTc, axis; MI, LVH, bundle-branch blocks… | Multi-label 1D ResNet + delineation | After M3: PTB-XL, CODE-15%, MIMIC-IV-ECG |
| M5 | **Calibration and "not sure"** | "How sure am I, and is this input unlike anything I trained on?" | Temperature scaling + out-of-distribution detection | With M3 |
| M6 | **Multi-signal (OT/ICU)** | "Is this monitor alarm real, given the pulse and BP?" "What changed together?" | Multi-input model over ECG + ABP/PPG | Product B/C: CinC 2015, VitalDB |
| M7 | **ECG image digitiser** | "Turn a photo or scan of a paper ECG into a signal" | Segmentation + trace extraction | Later; PhysioNet Challenge 2024 as benchmark |

## 2. How each model is trained and tested

- **Patients never cross splits.** Every test patient is unseen during training and during model
  selection (MIT-BIH: de Chazal DS1 → DS2; PTB-XL: official folds).
- **Standard scoring.** Beats and rhythms are scored with EC57-style sensitivity (Se) and
  positive predictivity (+P) per class, not a single "accuracy" figure that normal beats dominate.
- **Reproducible.** Fixed seeds, versioned code, dataset IDs and licences in each model card, and
  a SHA-256 hash of every model file.
- **Licence-clean.** Only datasets allowed for commercial training reach product weights (see the
  licence table in [PRODUCT_PLAN.md §7](PRODUCT_PLAN.md)). Icentia11k (non-commercial) is research only.
- **Hospital data before claims.** Public data builds the models. Our partner hospitals'
  cardiologist-labelled ECGs, on their own machines, decide whether a model is good enough.

## 3. Build order

| Step | Deliverable | Data | Done when |
|---|---|---|---|
| 1 | M1 quality + beat detection + M2 beats, end-to-end research pipeline | MIT-BIH, NSTDB | **Done (v0.1)**: numbers in RESULTS.md |
| 2 | Improve M2 on S/F beats (augmentation, patient-adaptive features, more data from INCART / LTAF) | + INCART, LTAF | S-beat Se and +P both improve on DS2 |
| 3 | M3 rhythm classifier (AF first) | MIT-BIH AF, CinC 2017, PTB-XL | AF Se/+P reported per dataset, including on a dataset not used in training |
| 4 | M5 calibration; confidence levels in the pipeline output | Held-out calibration sets | Reliability plots and expected calibration error reported |
| 5 | M4 12-lead statements and interval measurements | PTB-XL (+PTB-XL+), CODE-15% | AUROC per statement on official test fold; interval error vs reference |
| 6 | Export to ONNX; deterministic `ecg-engine` service with model registry | — | Same outputs from ONNX and PyTorch; engine API used by the app |
| 7 | Partner-hospital retrospective validation | Partner ECGs, ≥2 cardiologists per label | Pre-agreed acceptance targets met |
| 8 | M6 multi-signal false-alarm model (silent mode) | CinC 2015, VitalDB, partner OT data | Zero missed true alarms at the chosen operating point |

## 4. What "AI" is not used for

- **No LLM in the measurement or classification path.** Every number and finding comes from the
  signal-processing and ML models above, and is traceable to sample positions in the recording.
- **No self-updating models in hospitals.** Clinician corrections are collected as labelled data.
  Retraining happens offline, and a new version ships only after passing the same tests.
