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
| M1 | **Signal quality** | "Can this 2.5 s of signal be trusted?" good / noisy / unusable | 1D-CNN + amplitude statistics | **v0.3**: unusable caught 98.4% (val); clean expert-labelled ECGs rated unusable ≤0.1%; 80% of expert "too noisy" windows flagged |
| — | **Beat detection** | "Where is every heartbeat?" | Pan-Tompkins + R-peak refinement (4 detectors benchmarked EC57-style) | **Se 99.5%, +P 99.3%** on all 48 MIT-BIH records |
| M2 | **Beat classifier** | "Is this beat normal, supraventricular (S), ventricular (V) or fusion (F)?" | 1D-CNN on beat shape + MLP on RR timing | **v0.1**: end to end V Se 87.0% / +P 95.7%; S and F weak (inter-patient MIT-BIH) |
| M3 | **Rhythm classifier** | "What rhythm is this stretch?" normal / AF / other / too noisy (later: flutter, blocks, VT…) | 1D ResNet over 30 s + RR-irregularity features | **v0.1**: CinC 2017 challenge F1 83.1%; fresh AF Database patients: AF Se 97.4%, PPV 95.5%; ectopy-rich MIT-BIH: PPV ~60% |
| M4 | **12-lead statements + measurements** | PR, QRS, QT/QTc, axis; MI, LVH, bundle-branch blocks… | Multi-label 1D ResNet + delineation | After M3: PTB-XL, CODE-15%, MIMIC-IV-ECG |
| M5 | **Calibration and "not sure"** | "How sure am I, and is this input unlike anything I trained on?" | Temperature scaling (done) + out-of-distribution detection (next) | **Rhythm**: ECE 3.1% → 1.6%. **Beats**: does not transfer across patients yet |
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

**Priorities after the 27 Oct 2026 decisions** (hospitals + equipment manufacturers, India + USA,
on-premise):
1. **M4 — 12-lead measurements and statements.** Both buyers need it: hospital ECG reading rooms read
   12-lead ECGs, and ECG-cart makers embed 12-lead interpretation. It is also what the UI concept shows.
2. **Engine packaging (step 6 below) moves up:** manufacturers integrate an engine, not an app, so the
   exported, deterministic, versioned engine with its own test reports is needed early.
3. **AF operating point (3d)** and the open AF / beat issues continue alongside.
4. Multi-signal OT/ICU (M6) and image digitisation (M7) stay later.


| Step | Deliverable | Data | Done when |
|---|---|---|---|
| 1 | M1 quality + beat detection + M2 beats, end-to-end research pipeline | MIT-BIH, NSTDB | **Done (v0.1)**: end-to-end 91.7% beat accuracy on 22 unseen patients; numbers and known issues in RESULTS.md |
| 1b | Fix the quality gate over-rejecting low-amplitude arrhythmic recordings (record 222) | + CinC 2017 | **Done (quality v0.3)**: beats hidden in unusable segments 1,839 → 248 across the 22 test patients |
| 2 | Improve M2 on S/F beats (augmentation, patient-adaptive features, more data from INCART / LTAF) | + INCART, LTAF | S-beat Se and +P both improve on DS2 |
| 3 | M3 rhythm classifier (AF first) | CinC 2017; tested on MIT-BIH | **Done (v0.1)**: reported on CinC test and cross-dataset on MIT-BIH |
| 3b | Stop AF being over-called in ectopy-rich recordings | CinC 2017, MIT-BIH | **Tried twice, not adopted**: ectopy-aware model (v0.2) and ectopy gate (v0.3) both cut false AF but lost real AF on unseen patients (RESULTS.md §4). |
| 3c | AF validation set with many AF patients + fresh external test set; retry 3b | + MIT-BIH AF Database (23 patients: 8 train / 8 val / 7 test) | **Done, nothing adopted**: v0.4 halved validation false AF but lost AF in one patient (−16 points); the pre-declared rule caught it on validation. v0.1 on fresh AFDB test: AF Se 97.4%, PPV 95.5% |
| 3d | Next AF options: AF-probability operating point per use case (chosen on validation); Long-Term AF Database (84 patients); beat labels inside AF | + LTAFDB | Same rule as 3c |
| 4 | M5 calibration; confidence levels in the pipeline output | Held-out calibration sets | **Done for rhythm**; beats need a larger, more varied calibration set |
| 5 | M4 12-lead statements and interval measurements | PTB-XL (+PTB-XL+), CODE-15% | AUROC per statement on official test fold; interval error vs reference |
| 6 | Export to ONNX; deterministic `ecg-engine` service with model registry | — | Same outputs from ONNX and PyTorch; engine API used by the app |
| 7 | Partner-hospital retrospective validation | Partner ECGs, ≥2 cardiologists per label | Pre-agreed acceptance targets met |
| 8 | M6 multi-signal false-alarm model (silent mode) | CinC 2015, VitalDB, partner OT data | Zero missed true alarms at the chosen operating point |

## 4. What "AI" is not used for

- **No LLM in the measurement or classification path.** Every number and finding comes from the
  signal-processing and ML models above, and is traceable to sample positions in the recording.
- **No self-updating models in hospitals.** Clinician corrections are collected as labelled data.
  Retraining happens offline, and a new version ships only after passing the same tests.
