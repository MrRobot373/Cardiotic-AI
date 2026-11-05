# Model cards (DRAFT)

All figures are measured on **public research datasets** (PTB-XL, Chapman–Shaoxing–Ningbo, MIT-BIH, AFDB, CinC 2017); none comes from an Indian or
US hospital. They are copied from `ml/reports/RESULTS.md` and the JSON files beside it (the file is named in each card). Selection of every model followed a
rule fixed before the test data was looked at; candidates that failed are listed in RESULTS.md and were not shipped. **Intended use of every model: research
use only until the owner decides otherwise ([OWNER], see `INTENDED_USE_DRAFT.md`).** Each shipped file is identified by its SHA-256 in
`engine/cardiotic_engine/models/manifest.json`; the engine refuses to start if any file differs.

## 1. `ecg12_net` v0.3 — 12-lead statements (71 SCP-ECG statements + 5 superclasses)
| | |
|---|---|
| Input | 10 s, 12 leads, resampled to the model rate; adult resting ECG |
| Output | Probability per statement; a statement is called when it reaches its threshold (model default, or the site's signed threshold file) |
| Training data | PTB-XL (Schiller devices, Germany, 1989–1996), split train 17,418 / validation 2,183 / test 2,198 ECGs by the dataset's own folds, with the Ningbo part of Chapman–Shaoxing–Ningbo (China, 2013–2018) added to training only |
| Calibration | Temperature scaling 1.236; expected calibration error 0.0076 → 0.0038 (`ecg12_statements_v0.3.json`) |

**PTB-XL test, macro AUC:** all 71 statements 0.921; diagnostic (44) 0.935; form (19) 0.865; rhythm (12) 0.951; the 5 superclasses 0.929.

**External test, Chapman–Shaoxing (10,646 ECGs, never used for training or selection):** see `ecg12_external_chapman_v0.3.json`. Atrial fibrillation AUC 0.988, sensitivity 97.2%, PPV 76.4% at the PTB-XL threshold; first-degree AV block AUC 0.984, sensitivity 78.6%.

**Statements that matter for triage, PTB-XL test, at the model's default threshold** (support = ECGs with the statement in the test set):

| Statement | Support | AUC | Sensitivity | PPV | Comment |
|---|---:|---:|---:|---:|---|
| Atrial fibrillation (AFIB) | 152 | 0.984 | 86.2% | 87.9% | adequate |
| Sinus tachycardia (STACH) | 82 | 0.991 | 93.9% | 82.8% | adequate |
| Complete LBBB (CLBBB) | 54 | 0.998 | 92.6% | 76.9% | adequate |
| Inferior MI (IMI) | 267 | 0.923 | 61.4% | 59.0% | moderate |
| Anterior MI (AMI) | 35 | 0.891 | **8.6%** | 18.8% | **poor at this threshold** |
| Long QT (LNGQT) | 11 | 0.851 | **18.2%** | 16.7% | **poor** (22% sensitivity on Chapman) |
| Atrial flutter (AFLT) | 7 | 0.925 | 42.9% | 100% | **too few cases; flutter must not be claimed** (Chapman sensitivity 9% at this threshold; §11 of RESULTS) |
| Complete AV block (3AVB) | **2** | 1.000 | 100% | 50% | **only 2 test cases: not a validation** |
| 2nd-degree AV block (2AVB) | **1** | 0.983 | 0% | 0% | **only 1 test case** |

**Subgroups (superclass macro AUC, PTB-XL test):** women 0.917, men 0.939; age <40 0.936, 40–65 0.918, >65 0.918. The gap is in myocardial infarction (RESULTS §7.6). An attempted fix was rejected by its pre-declared rule.

**Known limits.** Trained on two datasets from two countries and older devices; hospital labelling styles differ, which moves the best threshold (RESULTS §7.3–7.4), hence per-site thresholds (RESULTS §7.7: flutter sensitivity rises to about 67% at about 22% PPV on a simulated installation — still not a claim). Adults only. Paced rhythms and very wide QRS are not handled specially. The AI statements are suggestions; every one is accepted or rejected by a cardiologist before signing.

**Triage dependency.** The worklist order uses statements such as 3AVB, AFIB/AFLT, MI and LNGQT (`docs/01_FEATURES_AND_LOGIC.md` §3.2). Because 3AVB and 2AVB have almost no test cases and AMI/LNGQT have low sensitivity, the triage is a *reading-order aid*, must not be presented as a safety net, and the site validation must collect enough cases of these statements (`CLINICAL_VALIDATION_PROTOCOL_DRAFT.md`).

## 2. `ecg12_net_print` v0.1 — the same statements for digitised printouts
Trained on the same data after rendering ECGs as printouts and reading them back with the digitiser. Adopted by its rule on validation (printout-layout validation AUC 0.929 against 0.857 for the standard model). On unseen test ECGs (196, `printout_end_to_end.json`): statement AUC 0.920 original, 0.913 vector PDF, 0.908 scan. **Limits:** only printouts drawn by this product and one other renderer were tested; real phone photographs with shadows, perspective and curved paper, and each cart's own style, are **not** tested ([OWNER]: obtain real printouts).

## 3. Measurements (rules on a median beat, not a learned model) — `ecg12/measure.py` v0.2
Agreement with the manufacturer's own measurements on 2,198 PTB-XL test ECGs (`ecg12_measurements_test_v0.2.json`): heart rate within 5 bpm 97.4%; QRS within 10 ms 85.7%; QT within 20 ms 90.0%; QTc (Bazett) within 20 ms 85.0%; PR within 10 ms 59.4% (mean difference −6.4 ms). **These are comparisons with another algorithm, not with a reference standard**; IEC 60601-2-25 requires the licensed CSE database ([OWNER]). PR is not measured above 300 ms. A cardiologist can override any measurement; overrides are audited and printed as "edited".

## 4. `quality_net` v0.3 — signal quality (good / noisy / unusable), 2.5 s windows
Trained on MIT-BIH Holter lead II with realistic noise added. Synthetic test (10,000 windows): accuracy 86.5%; unusable windows caught 98.7%. Real-data check: CinC AF windows rated unusable 0.0%; CinC "too noisy" windows rated noisy/unusable 75%. **Limit:** on clean 12-lead PTB-XL ECGs it rates 19% of leads "noisy" (three 12-lead candidates failed their rule, RESULTS §2.1), so the review screen shows noisy as a soft hint only.

## 5. `beat_net` v0.1 — beat classes (N / S / V / F)
Trained on MIT-BIH (DS1). Test (DS2, 49,685 beats, `beat_classification_v0.1.json`): overall accuracy 91.8%; normal sensitivity 95.6%, PPV 95.6%; ventricular sensitivity 84.9%, PPV 96.5%; **supraventricular sensitivity 32.2%, PPV 25.6%; fusion beats essentially not detected (0.5%)**. Calibration does not transfer across patients (RESULTS §8.10): beat confidence must not be shown as calibrated. On handheld lead I the classifier labels some AF beats as ventricular (RESULTS §8.8b).

## 6. `rhythm_net` v0.1 — rhythm in 30 s windows (sinus / AF / other / too noisy)
Trained on CinC 2017 (handheld lead I), AFDB and MIT-BIH. CinC test (1,707 records): window accuracy 85.5%, macro F1 0.786; AF sensitivity 88.8%, PPV 73.8%. AFDB test (3,204 AF windows): AF sensitivity 97.4%, PPV 95.5%. MIT-BIH DS2: AF sensitivity 96.9% but **PPV 59.8%** — AF is over-called in recordings with frequent ectopic beats (four retraining attempts failed their rules). **AF operating points** (RESULTS §12): *balanced* (default) test sensitivity 97.4% / PPV 92.8% (254 false-AF windows); *screening* 99.1% / 84.5% (610 false-AF windows). **Data licence:** CinC 2017 terms for commercial use must be confirmed before shipping this model ([OWNER]).

## 7. What none of the models has been shown to do
Work on an Indian or US population; on pediatric ECGs; on today's ECG carts from every manufacturer; on ICU/OR monitor leads; at the accuracy needed to replace a reading by a cardiologist. These are exactly the questions the site validation has to answer.
