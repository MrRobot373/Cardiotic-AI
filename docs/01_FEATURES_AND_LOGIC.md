# Cardiotic AI — Features, Working and Logic

What the product does, how each part works, and the rules behind it. Numbers quoted here are measured and
live in `ml/reports/RESULTS.md` (raw data: `ml/reports/*.json`). Where something is **not** tested on real
clinical data, it says so.

> **Status of the product:** research-grade software. It has not been through regulatory clearance or a clinical
> validation study. It supports a cardiologist; it never signs a report by itself. See `03_MANAGEMENT_ACTIONS.md`.

---

## 1. What it is

An on-premise system that reads ECGs (12-lead resting ECGs and long Holter recordings), proposes findings and
measurements, sorts the worklist by urgency, and lets a cardiologist review, edit and sign a report that is
sent to the hospital information system (HIS). Nothing leaves the hospital network.

Two users matter most:

| Person | What they do |
|---|---|
| Technician | Uploads or receives ECGs (files, folder drop, DICOM push), checks the patient match |
| Cardiologist | Reviews the AI draft, edits findings, signs the report |
| Administrator | Manages users, HIS connections, feeds, security settings, backups |

---

## 2. Feature list

### 2.1 Getting ECGs in
| Feature | How it works |
|---|---|
| File upload (browser) | Drag-and-drop or choose files; format is detected from content, not file name |
| Supported formats | DICOM waveform, HL7 aECG (XML), GE MUSE (XML), Philips (XLI/XML), SCP-ECG (incl. Huffman-coded), EDF, CSV |
| PDF / image digitiser | A scanned or photographed printout is turned back into signal (see 3.6) |
| Watched folder feed | A hot folder is polled; each new file is ingested once (duplicates detected by content) |
| DICOM listener | Devices push waveforms over DICOM (C-STORE) |
| HIS orders / admissions | HL7 ADT and ORM messages create/update patients and expected studies |
| Duplicate detection | Same signal content is not stored twice |
| Long recordings | Holter files are analysed in chunks so memory stays flat |

### 2.2 AI analysis
| Output | Source |
|---|---|
| Signal quality (good / noisy / unusable), per lead window | `quality_net` |
| Beat detection and class (normal / supraventricular / ventricular / fusion) | Pan-Tompkins + `beat_net` |
| Rhythm in 30 s windows (incl. atrial fibrillation) | `rhythm_net` |
| 71 diagnostic statements + 5 superclasses (76 labels) with probabilities | `ecg12_net` |
| Printout variant for digitised ECGs | `ecg12_net_print` |
| Measurements: heart rate, PR, QRS, QT, QTc, axis | Rules on a median beat (see 3.3) |
| Triage level: critical / urgent / routine / normal | Rules over statements + measurements (see 3.2) |

Every statement has a probability and a per-site threshold. The AI proposes; it does not decide.

### 2.3 Review and sign
- Worklist sorted by triage, then age; filters for status and level.
- 12-lead viewer with calipers, gain/speed, lead layouts, and beat-by-beat overlays.
- Findings list: accept, reject, or add a finding; free-text conclusion; measurement edits.
- **Review version counter:** every save increments the review's version number (used to detect two people editing at once); the audit log records each change, but earlier versions of the review are not kept as separate copies (listed in `02_REMAINING_DEVELOPMENT.md`).
- **Sign:** only a cardiologist can sign. A signed report is immutable; changes need an amendment (new version).
- PDF report (generated on the server) and a signed copy attached to the record.

### 2.4 Holter
- Long recording summary: heart-rate trend, pauses, bradycardia/tachycardia, ventricular and supraventricular
  ectopy, AF burden, ST/QT trends where available.
- Event strips for the worst episodes; the cardiologist reviews and signs a Holter report.

### 2.5 Live Assist (bedside monitoring)
Advisory flags on a stream of ECG from monitors. Off by default; the site starts in **silent mode**.
Rules and constants are in 3.8. It is advisory only and is not an alarm system.

### 2.6 Integration
| Interface | Detail |
|---|---|
| HL7 v2.5.1 ORU^R01 over MLLP | Signed reports pushed to the HIS from a persistent outbox with retry/backoff |
| FHIR R4 | Bundle export of a signed report |
| ADT / ORM inbound | Patient and order synchronisation |
| Folder & DICOM feeds | See 2.1 |
| Standalone engine API (`/v1`) | For equipment makers: send a file/signal, get the analysis JSON |

### 2.7 Security and administration
- Accounts with scrypt password hashing, lockout after repeated failures, idle and absolute session timeouts.
- Roles: cardiologist, technician, admin (see 3.9).
- Optional second factor (TOTP), LDAP, and OIDC (PKCE, RS256) single sign-on.
- Cookie sessions: `HttpOnly`, `SameSite=Strict`, CSRF header required on writes.
- Hash-chained audit log; CLI check `verify-audit` detects edits or deletions.
- Backups (`backup` CLI / `deploy/backup.sh`), restore procedure in `deploy/INSTALL.md`.

### 2.8 Frontend
React app, light and dark themes, keyboard-friendly, English only for now. Runs in two modes: against the
server (detected from `/api/health`) or as a static sample for demonstrations.

---

## 3. The logic

### 3.1 Pipeline
```
file -> reader (11 formats) -> normalise (500 Hz, mV, 12 lead order)
     -> quality net (per lead window)     -> unusable leads masked
     -> beat detection -> beat classes
     -> median beat per lead -> measurements (HR, PR, QRS, QT, QTc, axis)
     -> ecg12_net -> 76 probabilities -> per-site thresholds -> statements
     -> triage rules -> record + AI draft
```
The engine is deterministic: same input and same models give the same output. Model files are verified
against SHA-256 values in `manifest.json` at start-up; a mismatch refuses to start.

### 3.2 Triage (exact rules)
Evaluated top to bottom; the first match wins.

1. `3AVB` present -> **critical** ("Complete heart block suggested")
2. AF or flutter and heart rate >= 120 -> **critical**
3. QTc >= 500 ms and QRS narrow (QRS < 120 ms and no paced rhythm) -> **critical**
4. Heart rate >= 150 or (0 < heart rate < 40) -> **critical**
5. Any MI statement -> **urgent**
6. Any of AFIB, AFLT, 2AVB, LNGQT, SVTAC, PSVT, WPW, CLBBB -> **urgent**
7. Any other abnormal statement, or not NORM -> **routine**
8. Otherwise -> **normal**

The wide-QRS exception in rule 3 exists because QTc is overstated when the QRS is wide.

### 3.3 Measurements
- A **median beat** per lead is built from clean beats, which suppresses noise.
- Onsets and offsets use a spatial velocity signal across all leads, so a flat lead does not move the fiducial.
- QTc is reported by both Bazett and Fridericia; the method is shown with the value.
- The cardiologist can override any measurement; the override is stored with who and when.
- Accuracy is in `RESULTS.md` §7.2.

### 3.4 Statement model and thresholds
- `ecg12_net` outputs probabilities. A threshold turns a probability into a yes/no.
- Thresholds learned on one hospital's data do not transfer. The model ranks well across hospitals but the
  yes/no point shifts (for example atrial flutter: AUC 0.90, yet 9% sensitivity at the original threshold).
- Therefore each site gets a **site configuration**: a signed file of per-statement thresholds chosen on that
  site's own cardiologist-labelled ECGs (`ml/cardiotic_ml/ecg12/site.py`).
  - Policies: `max_f1`, or `sensitivity` (smallest set of calls that reaches a target sensitivity).
  - A statement with fewer than 20 site positives keeps the model's own threshold.
  - The file is refused unless it belongs to this exact model version and is signed off (site, version,
    approver, date).
- The configuration changes only thresholds, never weights.

### 3.5 Calibration
Temperature scaling per model so a "0.8" means roughly 80% in validation. Calibration is checked per
subgroup; the sex gap for MI is documented in `RESULTS.md` 7.6 (an attempted fix was rejected by the
pre-declared rule and not shipped).

### 3.6 Digitiser (printouts)
1. Detect the grid and its spacing by fitting over the whole grid (avoids drift from rounding).
2. Find trace rows; reject text rows.
3. Layouts supported: 3x4 plus rhythm strip, 6x2, 12x1.
4. Track each trace with continuity constraints, convert pixels to mV and seconds, split the rows into leads.
5. Run the printout model, which was trained on digitised data.
Measured results are in `RESULTS.md` §9. It has been tested on rendered printouts; **real photographs
and scans from several device makers still need testing** (see `02_REMAINING_DEVELOPMENT.md`).

### 3.7 Review and sign rules
- Only a cardiologist signs, through a dedicated sign action (a plain edit cannot set "signed").
- Technicians may send an ECG for reading or request a repeat; they cannot make decisions. Administrators cannot change reviews at all.
- A signed report is locked. A cardiologist must re-open it as an amendment; this clears the signature, moves it back to "in review", raises the version number and writes an audit entry. It must then be signed again.
- Signing builds the report and queues the HL7 message in the outbox in the same database transaction (all or nothing).
- The outbox retries with backoff and shows delivery state; failures are visible to admins.

### 3.8 Live Assist rules
Constants: pause >= 3.0 s; slow < 40 bpm; fast > 150 bpm; ventricular run >= 3 beats; AF needs 2 consecutive
windows with probability >= 0.8. Buffer 300 s, window 60 s, update every 5 s, a bed is offline after 10 s of
silence. Flags are advisory, acknowledged by a named user, and each acknowledgement is audited.

### 3.9 Roles
| Action | Technician | Cardiologist | Admin |
|---|---|---|---|
| Upload ECGs, match patients | yes | yes | yes |
| View records | yes | yes | yes |
| Send for reading / request repeat | yes | yes | no |
| Edit AI draft, accept / reject findings | no | yes | no |
| Sign and amend | no | yes | no |
| Acknowledge Live Assist flags | yes | yes | no |
| Users, feeds, HIS, authentication, audit view | no | no | yes |

### 3.10 Audit
Every login, failed login, upload, edit, sign, export, setting change and user change is written to an
append-only table; each row stores the hash of the previous row. `verify-audit` recomputes the chain.

---

## 4. Measured performance (summary)

See `ml/reports/RESULTS.md` for the full tables, confidence intervals and the models that were rejected.

| Area | Result | Data |
|---|---|---|
| 12-lead statements | per-statement AUC in RESULTS §7 | PTB-XL (internal), Chapman (external) |
| Signal quality | RESULTS §2 | PTB-XL technician notes + noise-augmented |
| Rhythm / AF | RESULTS §4 | CinC 2017 and others |
| Beat classification | RESULTS §3 | MIT-BIH |
| Digitiser | RESULTS §9 | rendered printouts |
| Holter chunking | identical output to whole-file analysis | `engine/validation/holter_chunking.py` |
| Engine equals research code | identical on real data | `engine/validation/equivalence.py` |

Rejected by the pre-declared rules and **not** shipped: quality v0.4/0.5/0.6, women's-MI v0.4, flutter detector.

## 5. What is and is not proven

| Proven by tests | Not proven |
|---|---|
| Software behaviour: 32 ml, 48 engine, 53 server, 8 frontend unit + 2 static flows, 5 browser flows against the server; Docker image acceptance test (10 checks, 18 screenshots) | Clinical accuracy at *your* hospital |
| Engine output equals research output | Behaviour on real vendor files from every device model |
| Concurrency (signing while others poll) | Load at hospital scale |
| Audit chain, auth, CSRF, session timeouts | Independent penetration test |
