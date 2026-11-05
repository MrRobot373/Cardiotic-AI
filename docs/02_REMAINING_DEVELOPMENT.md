# Development status — what is done and what is left

This replaces the first audit list. Everything that could be built and verified without a hospital, a regulator, outside data or a person's decision is **done**.
What is left is in two groups: engineering that needs an input, and engineering waiting on a decision. The owner-facing list, in order, is `05_OWNER_TODO.md`.

## Done since the first audit (all tested; see `01_FEATURES_AND_LOGIC.md` for how each works)

| First-audit item | Status | Where |
|---|---|---|
| 1 Access logging for record views | done | `security.ViewLog`, `test_security.py` |
| 2 Re-authentication at signing | done | `auth.reauthenticate`, sign dialog, browser flow |
| 3 First-login password change, expiry, history | done | `auth.py`, `ChangePassword.tsx` |
| 4 Brute-force protection by address | done | `security.LoginLimiter` |
| 5 DICOM / MLLP allow-lists and TLS | done (both directions) | `feeds.py`, `hl7in.py`, `export.send_mllp`, `security.py` |
| 6 Critical-result notification | done (banner, sound, optional e-mail without patient data) | `notify.py`, `CriticalBanner.tsx` |
| 7 Engine manifest `intended_use` text | **left unchanged on purpose** — it is true today and changes only with the owner's decision | `05_OWNER_TODO.md` §1 |
| 8 `LICENSE` and `THIRD_PARTY_NOTICES.md` | done (LICENSE is a placeholder for the legal entity) | repository root, `deploy/make_notices.py` |
| 9 CinC 2017 licence | **owner** — cannot be settled by software | `05_OWNER_TODO.md` §5 |
| 10 Holter report, export, beat relabelling | done | `holter_report.py`, `BeatDialog.tsx` |
| 11 Pagination / server-side search | done (search + windowed worklist above 5,000 recordings) | `records.search`, `store.catalog` |
| 12 Retention, deletion, export tooling | done | `records.py`, `PatientRecords.tsx` |
| 13 Time zones | done (site time zone; machine wall-clock times no longer shifted by the browser) | `lib/utils.ts` |
| 14 Keyed / anchored audit chain | done | `db.py`, `audit-anchor` |
| 15 Site-config management in Settings | done (upload, history, switch on, roll back; engine switches at run time) | `siteconfigs.py`, `Engine.apply_site_config` |
| 16 Python lock files, SBOM, vulnerability scanning | done (hashed lock, CycloneDX SBOMs, pip-audit + npm audit clean) | `deploy/requirements.lock`, `deploy/sbom/` |
| 17 Base image refresh | done (Python 3.13, pinned by digest, pip/setuptools/wheel upgraded) | `Dockerfile` |
| 18 CI pipeline | **written, not yet run on a hosted runner** | `.github/workflows/ci.yml` |
| 19 Accessibility audit | **left**: needs an expert (E2) | |
| 20 Hindi localisation | **left**: needs a clinician-reviewed translation (E1) | |
| 21 Coverage gaps (CLI, simulator, engine service) | done | `test_ops.py`, `test_engine_service.py` |
| 22 Real-photo digitiser tests | **left**: needs real photos (E7) | |
| 23 Operational runbook | done | `OPERATIONS_RUNBOOK.md`, `restore_drill.sh` |
| 24 Load and soak test | done on this machine (4 cores); to repeat on the pilot hardware | `deploy/loadtest.py` |
| 25 PostgreSQL / high availability | **left**: not needed at the tested scale (E11) | |
| 26 Review history | done | `review_versions` |
| AI: AF over-call | operating points built; *screening* shipped as an option, *fewer false alarms* mode not offered (failed its rule) | RESULTS §12 |
| Security finding during this work | XML from machines is now parsed with `defusedxml` (entity-expansion and external-entity files are refused, tested) | `engine/ingest` |

Two defects were found and fixed *while building*, both by tests, and are worth knowing about: when a stored site-threshold file no longer fitted the model at start-up the old thresholds stayed
in memory (now the engine falls back to the model's own and the audit log says so); and backup verification at another path could not find the audit key (the scripts and the CLI now handle it, with a plain error and exit code 6).
One mistake of mine is on record in RESULTS §12 (a threshold direction in a pre-declared rule), reported together with the first result.

## Left — needs an input (the owner's side supplies it)

| # | Item | Needs |
|---|---|---|
| E1 | Hindi and other languages | clinician-reviewed translation |
| E2 | WCAG 2.1 AA accessibility audit | accessibility expert |
| E3 | Browsers other than Chromium | a pass on the hospital's real workstations |
| E4 | CI run on a hosted runner | repository on a company account with Actions enabled |
| E5 | Better weak statements (anterior MI, long QT, flutter, AV block) and S/F beats | labelled data (Indian/US ECGs, verified flutter, INCART/LTAFDB after licence check) |
| E7 | Digitiser on real phone photos and each cart's printout style | real printouts |
| E9 | Failed-delivery alerts, SMS/paging for critical results | the hospital's gateways |

## Left — waiting for a decision

| # | Item | Decision |
|---|---|---|
| E8 | Second patient-identity check (barcode / order match) | clinical lead, after usability test |
| E10 | Cryptographic signing of threshold files and releases; build provenance | company key-management |
| E11 | Encryption at rest; PostgreSQL/HA | when a customer needs it |
| E12 | Paediatric support | extend the intended use? |
| E13 | Version numbers and release notes (all components are 0.1.0) | numbering scheme from the quality lead |

## Known limits of what was verified
Browser flows ran in Chromium only; the container acceptance and load test ran on one machine (4 cores); no real HIS, ECG cart or hospital network was involved; no external security test; the draft regulatory pack is unreviewed.
