# Risk management — hazard analysis draft (ISO 14971 style)

**DRAFT. Engineering listed the hazards it could identify and the controls that exist in the software. Severity and probability are PROPOSALS for the clinical
lead and the regulatory lead to rate ([OWNER]); residual risk and risk-benefit acceptability are theirs to decide.** Scale used for the proposal:
severity S1 negligible … S5 death; probability P1 very rare … P5 frequent, *before* controls.

Method note: hazards were found by walking the data flow (input → analysis → review → report → HIS → storage) and the security model; it is not a
substitute for a structured FMEA/HAZOP workshop with clinicians ([OWNER]).

| ID | Hazard → hazardous situation → harm | S | P | Controls in the software (where) | Control gaps / information for safety |
|---|---|:-:|:-:|---|---|
| R01 | AI misses a critical finding (e.g. anterior MI, high-grade AV block, long QT) and the ECG is read late or as routine → delayed treatment | 5 | 3 | Every ECG is still read by a cardiologist before any report exists; triage is described as a reading order, not a result (`01_FEATURES` §3.2); model limits stated (`MODEL_CARDS.md`); site thresholds raise sensitivity per site; critical-result banner | **Measured sensitivity is low for some critical statements (AMI 8.6%, LNGQT 18%; 3AVB/2AVB have 1–2 test cases).** Do not present triage as a safety net; site validation must collect these cases; consider labelling "may not detect…" |
| R02 | AI over-calls (false positives) → alarm fatigue, wasted reads, ignored banners | 3 | 4 | Banner needs an acknowledgement and shows the reason; levels configurable; e-mail optional; per-site thresholds; screening AF mode is opt-in with its cost shown | Measure false-alert rate in the silent-mode study; define the hospital's own escalation procedure |
| R03 | ECG attached to the wrong patient (missing/incorrect MRN, duplicates, merge errors) → report to the wrong chart | 5 | 3 | Unmatched recordings are labelled `UNMATCHED-…` and need a person to assign; assignment audited; signed report cannot be moved; HIS is the authority for demographics (ADT); ADT merge handled; header MRN fills only missing IDs | Reader must confirm identity on screen — usability to be tested; no barcode/wristband check; no second-patient-ID cross-check against the order |
| R04 | Wrong or stale site thresholds applied → unexpected call behaviour | 4 | 2 | File must be signed off and made for the exact model; refused otherwise; version history, who switched it on, rollback; switched off (and audited) if it no longer fits the model at start-up | Approval is a name in a file: no cryptographic signature of the file ([OWNER] decide whether to add) |
| R05 | Someone else signs (unattended session) or a signature is forged | 5 | 2 | Password/two-factor re-entry at signing; idle timeout 15 min (configurable); lockout; per-address block; named accounts; audit | No hardware token/biometric; shared workstations depend on hospital policy |
| R06 | Report changes after signing without trace | 4 | 1 | Signed state is locked; amendment removes signature and is audited; every state kept with a change summary; HL7/FHIR/PDF built from what was signed | — |
| R07 | Signed report never reaches the HIS and nobody notices | 4 | 3 | Outbox with retries (up to 12), status visible to administrators and cardiologists; runbook | No push alert on delivery failure (only the screen); no end-to-end confirmation from the HIS beyond the HL7 ACK; hospital should monitor the outbox |
| R08 | Data loss or corruption (disk failure, bad upgrade) | 4 | 2 | SQLite WAL with full sync; nightly consistent backup with audit verification; restore drill; upgrade guidance; rollback = restore | Backup storage and encryption are the hospital's; RPO/RTO to be agreed; no replication/high availability |
| R09 | Records or audit log tampered with | 4 | 2 | Keyed hash chain; anchors recorded outside the server; role separation | Key stored beside the database by default (move it); anchors are manual |
| R10 | Unauthorised access to patient data | 4 | 3 | Roles; TLS at the reverse proxy; session security; lockout; read-access audit; export/erase admin-only; data stays on-premise | Penetration test not yet done ([OWNER]); privacy impact assessment not done |
| R11 | Measurement error (QT, PR, axis) changes a clinical decision | 4 | 3 | Cardiologist can override any value; overrides printed "edited"; QTc not used for triage when QRS is wide/paced; agreement figures documented | Compared with another algorithm, not a reference standard; PR agreement within 10 ms only 59% |
| R12 | Digitised paper ECG misread (distortion, rotation, missing lead) | 4 | 3 | Printout results are badged; separate printout model; quality checks; layouts limited to known ones; reader sees the original | Real photographs not tested; do not claim printout accuracy |
| R13 | Model or software update changes behaviour unexpectedly | 4 | 2 | Model files verified by hash; models versioned; site thresholds tied to the model version; deterministic output; engine equals research on real data; automated test suites and acceptance test | Formal change control, regression criteria and a predetermined change plan are missing ([OWNER] quality system) |
| R14 | Systematic bias (e.g. weaker MI detection in women; training data from other countries/devices) | 4 | 3 | Subgroup results published; gap documented; per-site thresholds; adults only stated | No mitigation of the sex gap (attempt rejected); no Indian/US data; labelling and clinician training must state it |
| R15 | Clock/time-zone errors misorder events or signatures | 3 | 2 | Server clock in UTC; hospital time zone setting; machine times shown as recorded | Time synchronisation is the hospital's (checklist) |
| R16 | Critical banner/notification not seen | 4 | 3 | Persistent banner on every screen until acknowledged; optional sound; optional e-mail | Does not replace the hospital's critical-result procedure (said in the UI); no paging/SMS |
| R17 | Live Assist flags taken as alarms (false reassurance or false alarm) | 4 | 3 | Off by default; silent mode by default; advisory wording; acknowledgement audited | Not an alarm system and must not be sold as one; no validation on monitor data |
| R18 | Input outside the validated scope (child, paced, lead reversal, artefact) analysed as if normal | 4 | 3 | Quality model and checks; unusable leads reported; labelling states adults only | No automatic age gate for missing/implausible birth date; lead-reversal detection absent |
| R19 | Software defect (race condition, data corruption in a rare path) | 4 | 2 | 244 automated tests, concurrency test, browser flows against a real server, load test, container acceptance; CI workflow | Coverage not 100%; CI not yet run on a hosted runner |
| R20 | Ransomware/malicious code on the server | 5 | 2 | Non-root container, read-only root, pinned images and hashed dependencies, SBOM and vulnerability scan in CI | Hospital backup isolation and endpoint protection; no code signing of releases |
| R21 | Erasure/export mishandled (privacy breach, destroyed evidence) | 3 | 2 | Admin-only; MRN typed to confirm; retention guard; blocks while an HIS message is pending; audited | Retention period must be set by the hospital's policy; legal hold not implemented |
| R22 | E-mail notification leaks patient data | 3 | 2 | Message carries no name or MRN, only recording number, location, reason | Recording number may be linkable inside the hospital |

## Residual-risk and benefit-risk
Not assessed. Needs the clinical lead's ratings, the risk-acceptability criteria in the hospital/company policy, and the benefit evidence from the site validation.

## Items that most need a human decision
1. R01/R14: whether the triage may be shown at all before the validation proves the sensitivity of the critical statements, and how the limits are worded.
2. R03: whether a second patient identification check (barcode, order match) is required.
3. R05: whether re-entering a password is enough as the legal "signature".
4. R17: whether Live Assist is part of the product at launch.
