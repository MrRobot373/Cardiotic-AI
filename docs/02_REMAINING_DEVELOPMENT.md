# Cardiotic AI — Remaining Development

An audit of the whole project (code, tests, deployment, dependencies). Everything below is **engineering work
that is still open**. Work that needs a hospital, a regulator or a decision by management is in
`03_MANAGEMENT_ACTIONS.md`.

**Overall:** the product works end to end and its tests pass. It is not yet "ship to a hospital" complete:
P0 items below should be done before any pilot, P1 before general release.

Audit evidence: tests ml 32, engine 48, server 53, frontend 8 unit + 2 static flows + 5 server flows; Docker
acceptance (10 checks, 18 screenshots) passed; typecheck and lint clean; `npm audit` 0 vulnerabilities;
`pip-audit` shows only setuptools/wheel advisories in the base image; coverage server 85%, engine 83%.

---

## P0 — before any pilot at a hospital

| # | Item | Why | Rough size |
|---|---|---|---|
| 1 | **Access logging for record views** | The audit log records changes, not who *looked at* a patient. Hospitals and privacy law expect read access to be traceable | 1–2 days |
| 2 | **Re-authentication at signing** | A signature should prove the cardiologist is present now (password or second factor at sign time) | 1–2 days |
| 3 | **First-login password change, expiry, history** | Default/admin-set passwords must not live on | 2 days |
| 4 | **Brute-force protection by IP** | Lockout exists per account only; add per-IP rate limits | 1 day |
| 5 | **Allow-lists and TLS for DICOM and MLLP** | Today any host that can reach the port may push. Add permitted AE titles / source IPs and optional TLS | 2–3 days |
| 6 | **Critical-result notification** | Critical ECGs wait in the worklist; there is no push/e-mail/pager/HL7 alert | 3–4 days |
| 7 | **Engine manifest `intended_use` text** | It says "Research use only. Not a medical device." That is true today; it must be changed deliberately, and only with management's regulatory decision | 0.5 day (after decision) |
| 8 | **`LICENSE` and `THIRD_PARTY_NOTICES.md`** | No licence file or third-party notices ship. `ldap3` is LGPL-3; the others are permissive (MIT/BSD/Apache/HPND). The notices file must list every dependency | 1 day |
| 9 | **CinC 2017 data licence check** | The quality and rhythm models used this data; its terms must be confirmed for commercial use before shipping those weights | management + 0.5 day |

## P1 — before general release

| # | Item | Detail |
|---|---|---|
| 10 | Holter report | The Holter review exists but has no PDF report and no HIS/FHIR export; beat relabelling (mark a beat N/V/S) is not in the UI |
| 11 | Pagination and server-side search | The catalog endpoint returns everything in one response. Fine for thousands of ECGs, not for hundreds of thousands |
| 12 | Retention, deletion and export tooling | Per-patient export and policy-based deletion for privacy requests; today only whole-database backup exists |
| 13 | Time zones | Timestamps are stored in UTC; display and Holter clock times need a per-site zone setting |
| 14 | Audit chain anchoring | The hash chain detects edits, but someone with the database file could rebuild all of it. Add a keyed HMAC and/or periodic external anchor (printed or e-mailed head hash) |
| 15 | Site-configuration management in Settings | Operating-point files are loaded from disk (`CARDIOTIC_SITE_CONFIG`). Add upload, view, version history and approval trail in the UI |
| 16 | Python lock files, SBOM and vulnerability scan in CI | Pin all Python dependencies with hashes, generate an SBOM, scan on every build |
| 17 | Base image refresh | `setuptools`/`wheel` advisories in the Python base image; rebuild on a newer base and pin by digest |
| 18 | CI pipeline | Tests run by script; there is no hosted CI definition that runs everything on each commit |
| 19 | Accessibility audit | Basic labelling is in place; a full WCAG 2.1 AA review has not been done |
| 20 | Hindi localisation (India) and a language framework | UI strings are English only |
| 21 | Coverage gaps | `__main__` CLI, the simulator and the engine's `server.py` are lightly tested |
| 22 | Real-photo digitiser tests | Tested on rendered printouts; no phone photos with shadow, curl or rotation, no scans from real device models |
| 23 | Operational runbook | Monitoring/health alerts, log shipping, upgrade and rollback steps, restore drill. `INSTALL.md` covers install and backup only |
| 24 | Load and soak test | No test of concurrent users or sustained upload rate at hospital scale |
| 26 | Review history | Reviews keep a version counter, not full copies of each earlier version; add a review-history table so an amendment can show exactly what changed |
| 25 | SQLite → PostgreSQL option | SQLite (WAL) is correct for a single-server site. Multi-site or high availability needs a server database |

## P2 — improvements

- Training-set expansion once a partner supplies labelled local ECGs (Indian population).
- More vendor readers as real files arrive (Schiller, Mortara, Nihon Kohden, BPL).
- Dedicated PR/QRS/QT evaluation on a locally annotated set.
- Pediatric ECG support (models are trained on adults).
- Mobile/tablet layout polish for the reading view.
- Reproducible model training in a container with a data manifest.

---

## What is explicitly NOT a gap

- Models rejected by the pre-declared rules (quality v0.4/0.5/0.6, women's-MI v0.4, flutter detector) are
  documented in `ml/reports/RESULTS.md`, not shipped.
- The sex gap for MI (§7.6) is documented, and must be shown to clinicians and in the labelling.

---

## What I (the engineering side) can still build

All of P0 items 1–6, 8 and all of P1 items 10–13, 15–18, 21 are pure software and can be built and tested
here without outside help. Items 7, 9, 14 (anchor destination), 19 (external audit), 20 (translation review)
and 22 (real files) need a decision or an input from you. Once P0 and P1 software items are built, the
remaining blockers to a hospital go-live are the items in `03_MANAGEMENT_ACTIONS.md`.

Suggested order: 1 → 2 → 3 → 4 → 5 → 6 → 8 → 10 → 11 → 12 → 15 → 16–18 → 14 → 13 → 21 → 23–24.
