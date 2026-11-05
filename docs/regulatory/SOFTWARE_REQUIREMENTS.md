# Software requirements and traceability (DRAFT)

IEC 62304-style requirements written **after** the software, from what it does and what the tests verify. They are a starting point for the quality
system's design inputs: the regulatory lead decides wording, numbering, and which become formal requirements ([OWNER]). "Verified by" names the test files
(`server/tests`, `engine/tests`, `ml/tests`, `frontend/tests`, `frontend/e2e*`); the test count at the time of writing is 116 server, 55 engine, 35 research,
28 web unit, 2 static and 10 server browser flows, plus the container acceptance test (10 checks). **Not yet verified by any test or review: usability
(IEC 62366), performance on real hospital equipment, and clinical accuracy.**

**Software safety class (proposal): B.** Reason: wrong output could contribute to a hazard (a missed urgent finding), but a qualified person reviews every
statement and signs; nothing reaches the hospital system unsigned. If the owner chooses Option C (embedded, no human review in the loop) the class must be
reassessed.

## 1. Data in
| ID | Requirement | Implemented in | Verified by |
|---|---|---|---|
| SRS-IN-01 | Read DICOM, HL7 aECG, GE MUSE, Philips XLI, SCP-ECG (incl. Huffman), EDF and CSV waveforms; format detected from content; unreadable input refused with a reason | `engine/ingest/*` | `test_ingest.py` |
| SRS-IN-02 | Convert PDF/image printouts to signal; mark results as printout-derived | `engine/ingest/digitise.py`, `ecg12_print` | `test_ingest.py`, `printout.spec.ts`, `digitiser_eval.json` |
| SRS-IN-03 | Refuse implausible signal (NaN, amplitude, too short, missing leads) | `engine/api.py` | `test_engine.py` (input contract) |
| SRS-IN-04 | Detect a recording already stored (same samples) and refuse a duplicate | `store.add_file` | `test_server.py` |
| SRS-IN-05 | Receive recordings from watched folders and DICOM C-STORE; restrict by address and AE title; optional TLS | `feeds.py`, `security.py` | `test_feeds.py`, `test_security.py` |
| SRS-IN-06 | Receive patients (ADT A01/A04/A05/A08/A28/A31/A40) and orders (ORM O01/OMG O19) over MLLP; acknowledge each message; restrict by address; optional TLS | `hl7in.py` | `test_hl7in.py`, `test_security.py` |
| SRS-IN-07 | A recording without a patient identifier is kept as unmatched and can only be assigned by a technician or cardiologist; a signed report cannot be moved | `store.py` | `test_server.py` |
| SRS-IN-08 | Long recordings are analysed in sections with the same result as a single pass | `ml/pipeline.analyze_long` | `holter_chunking.py`, `test_server.py` (long Holter) |

## 2. Analysis
| ID | Requirement | Implemented in | Verified by |
|---|---|---|---|
| SRS-AN-01 | Model files are verified by SHA-256 at start-up; a changed file stops the service | `engine/registry.py` | `test_engine.py`, container acceptance (tamper) |
| SRS-AN-02 | The analysis is deterministic: same input and models give the same output | engine | `test_engine.py` (deterministic, golden outputs) |
| SRS-AN-03 | The engine's output equals the research pipeline's on real data | `engine/validation/equivalence.py` | equivalence report (800 ECGs, 49,438 beats) |
| SRS-AN-04 | Produce signal quality, beats, rhythm, 71 statements + 5 superclasses, and measurements (HR, PR, QRS, QT, QTc, axis) | `ml/pipeline.py`, `ml/ecg12/*` | `ml/tests/test_core.py`, `test_engine.py`, RESULTS.md |
| SRS-AN-05 | Per-site thresholds only from a signed file made for the exact model; refused otherwise; versioned, switch on / roll back at run time; re-checked at start-up | `siteconfig.py`, `siteconfigs.py`, `ml/ecg12/site.py` | `test_siteconfig.py`, `test_records.py` |
| SRS-AN-06 | Triage level from statements and measurements by fixed rules; identical in server and web app | `triage.py`, `data/clinical.ts` | `shared/triage-cases.json` run by `test_security.py` and `clinical.test.ts` |
| SRS-AN-07 | AF call mode (balanced / screening) selectable by the site; default unchanged | `engine/api.py`, `pipeline.py` | `test_engine_service.py`, `test_records.py`, `test_afop.py` |

## 3. Review, signing, reporting
| ID | Requirement | Implemented in | Verified by |
|---|---|---|---|
| SRS-RV-01 | Only a cardiologist can accept/reject statements, edit measurements and sign; technicians can send for reading or request a repeat; administrators cannot change reviews | `store.py`, `app.py` | `test_server.py` |
| SRS-RV-02 | Signing requires a decision on every AI finding of a 12-lead ECG | `store.sign` | `test_server.py` |
| SRS-RV-03 | Signing requires the signer's password (or two-factor code) again; wrong answers count toward lockout | `auth.reauthenticate` | `test_security.py`, `server-flow.spec.ts` |
| SRS-RV-04 | A signed report is locked; changes need an amendment that removes the signature and is audited | `store.update_review` | `test_server.py` |
| SRS-RV-05 | Every saved state of a review is kept with what changed | `store._snapshot`, `review_versions` | `test_security.py` |
| SRS-RV-06 | Two people editing the same review: the stale one is refused | `store.update_review` | `test_server.py` |
| SRS-RV-07 | Holter beats can be relabelled by a cardiologist before signing; counts and burdens follow | `store.relabel_beat`, `holter_report.py` | `test_records.py`, `phase-b.spec.ts` |
| SRS-RV-08 | Report PDF, HL7 ORU^R01 and FHIR bundle are built from what was signed (including edits), for 12-lead and Holter | `export.py`, `holter_report.py`, `pdf.py` | `test_server.py`, `test_records.py` |
| SRS-RV-09 | Signing and queueing the HIS message are one transaction; delivery is retried with growing waits and visible; never blocks signing | `export.py` | `test_server.py` (concurrency, outbox) |
| SRS-RV-10 | Critical-result notification created with the recording; shown until acknowledged; optional e-mail without patient identifiers | `notify.py` | `test_security.py`, `password-and-alerts.spec.ts` |

## 4. Security and privacy
| ID | Requirement | Implemented in | Verified by |
|---|---|---|---|
| SRS-SE-01 | Passwords hashed with scrypt; minimum length; user name not in password; account lockout; per-address rate limit | `auth.py`, `security.py` | `test_server.py`, `test_security.py` |
| SRS-SE-02 | Issued/reset passwords must be changed at first sign-in; optional expiry; last 5 not reusable | `auth.py` | `test_security.py`, `password-and-alerts.spec.ts` |
| SRS-SE-03 | Sessions: random token (hash stored), idle and absolute timeout, HttpOnly SameSite=Strict cookie, CSRF header on writes | `auth.py`, `app.py` | `test_server.py` |
| SRS-SE-04 | Optional two-factor (TOTP), LDAP/AD, OIDC (PKCE, RS256 verified) | `sso.py` | `test_sso.py`, `two-factor.spec.ts` |
| SRS-SE-05 | Role-based access on every route | `app.py` | `test_server.py` |
| SRS-SE-06 | Reading patient data is audited (view of ECG, Holter, report, exports) | `security.ViewLog` | `test_security.py` |
| SRS-SE-07 | Audit log is append-only, hash-chained and keyed; anchors prove nothing earlier changed or was removed | `db.py` | `test_server.py`, `test_ops.py` |
| SRS-SE-08 | Patient data export and erasure with retention guard and MRN confirmation; erasure audited | `records.py` | `test_records.py` |
| SRS-SE-09 | Security headers and a content-security policy; request size limits; no internals in errors | `app.py` | `test_server.py` |
| SRS-SE-10 | The container runs as a non-root user with a read-only root file system | `Dockerfile`, `docker-compose.yml` | `container_test.sh` |

## 5. Operation
| ID | Requirement | Implemented in | Verified by |
|---|---|---|---|
| SRS-OP-01 | Consistent online backup; verify copies; restore drill | `backup.sh`, `restore_drill.sh`, `db.backup` | `test_ops.py`, restore drill run, container acceptance |
| SRS-OP-02 | Schema upgrades in place; refuse to start with a keyed log but no key | `db.py` | `test_sso.py` (upgrade), `test_ops.py` |
| SRS-OP-03 | Large archives: the worklist loads open and recent recordings; older are found by search | `store.catalog`, `records.search` | `test_records.py`, `phase-b.spec.ts` |
| SRS-OP-04 | Hospital time zone for moments with a zone; machine wall-clock times shown as recorded | `lib/utils.ts` | `clinical.test.ts` |
| SRS-OP-05 | Response time: worklist refresh 95th percentile ≤ 2 s at 20 readers + continuous uploads on 4 cores | server | `deploy/loadtest.py` (measured: 0.33 s and 1.04 s in two scenarios) |

## 6. Gaps in this list (engineering view)
- No formal software architecture/detailed design document beyond `docs/04_ARCHITECTURE.md`; no SOUP (third-party software) risk analysis beyond the SBOM and `THIRD_PARTY_NOTICES.md`.
- No usability engineering file: user needs, use-related hazards, formative/summative evaluation ([OWNER] with a human-factors consultant).
- No problem-resolution/anomaly procedure, change-control procedure or release procedure ([OWNER] quality system).
- Requirements are unreviewed and unsigned.
