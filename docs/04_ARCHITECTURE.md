# Cardiotic AI — Architecture and Technical Reference

## 1. Overview

Four layers, deployed as **one container** on a hospital server. Patient data never leaves the hospital network.

```
                          hospital network
 ECG carts ──DICOM──┐                                    ┌── HIS (HL7 ORU out, ADT/ORM in)
 watched folder ────┤                                    │
 browser ──HTTPS──► nginx (TLS) ──► Cardiotic server ────┤
 bedside gateway ───┘            (HTTP API + static UI)  └── LDAP / OIDC identity provider
                                     │         │
                                     │         └── SQLite (WAL) in /data
                                     ▼
                           Cardiotic engine (in-process library)
                           readers → pipeline → ONNX models
```

| Layer | Directory | Role |
|---|---|---|
| Research | `ml/cardiotic_ml/` | Data, training, evaluation, export of models. **Not shipped to hospitals** |
| Engine | `engine/cardiotic_engine/` | Deterministic inference library + standalone `/v1` API. Reads files, runs ONNX models |
| Server | `server/cardiotic_server/` | Accounts, storage, review/sign, audit, integrations, PDF, live board |
| Frontend | `frontend/` | React single-page app, served by the server |

Language/runtime: Python 3.13 (standard-library HTTP server, SQLite), NumPy/SciPy, ONNX Runtime for inference,
PyTorch only in the research layer, React 18 + TypeScript + Vite + Tailwind + Radix + react-query + recharts.

## 2. Engine

- `api.py`: `Engine` with `analyze_file`, `analyze_parsed`, `analyze_ecg12`, `analyze_rhythm`; `SiteConfigError`.
- `registry.py`: loads `models/manifest.json`, **verifies SHA-256** of each `.onnx`, assigns roles
  (`quality`, `beats`, `rhythm`, `ecg12`, optional `ecg12_print`). Mismatch ⇒ refuses to start.
- `ingest/`: 11 readers (DICOM, HL7 aECG, GE MUSE, Philips XLI, SCP-ECG incl. Huffman, EDF, CSV, …) plus
  `digitise.py` (PDF/image to signal). Format is sniffed from content.
- `siteconfig.py`: loads and validates the signed per-site thresholds (`CARDIOTIC_SITE_CONFIG`).
- `server.py`: standalone API for equipment makers: `GET /v1/health`, `GET /v1/models`, `POST /v1/ecg12`,
  `POST /v1/file`. Limits via `CARDIOTIC_ENGINE_MAX_BODY`, `CARDIOTIC_ENGINE_THREADS`.
- Long recordings are processed in chunks; result is identical to whole-file analysis (tested).
- Equality with research code is tested on real data (`engine/validation/equivalence.py`).

### Models (engine/cardiotic_engine/models)
| Role | File | Task |
|---|---|---|
| quality | `quality_net_v0.3.onnx` | single-lead 2.5 s windows: good / noisy / unusable |
| beats | `beat_net_v0.1.onnx` | beat class N / S / V / F |
| rhythm | `rhythm_net_v0.1.onnx` | 30 s rhythm windows |
| ecg12 | `ecg12_net_v0.3.onnx` | 71 SCP statements + 5 superclasses (76 labels) |
| ecg12_print | `ecg12_net_print-v0.1.onnx` | same task, trained for digitised printouts |

Each manifest entry holds: hash, source-weights hash, input shapes, labels, temperature, thresholds, intended
use, export check (ONNX vs PyTorch max difference ≤ 1e-4), and training recipe. Models are released only if
they pass pre-declared selection rules measured on validation data.

## 3. Server

Single process, `ThreadingHTTPServer`, JSON over HTTP under `/api`. Background threads: HL7 outbox worker,
folder feed, DICOM listener, ADT/ORM listener, live hub.

### 3.1 Modules
| Module | Responsibility |
|---|---|
| `app.py` | Routing, request limits, CSP/headers, CSRF check, static files, error mapping |
| `auth.py` | scrypt hashes, lockout, sessions (idle + absolute timeout), TOTP, roles |
| `sso.py` | LDAP bind/group map; OIDC authorization-code + PKCE, RS256 ID-token check |
| `db.py` | Schema v2, migrations, transactions, hash-chained `audit()` |
| `store.py` | Patients, recordings, versioned reviews, sign/amend rules, catalog |
| `export.py` | HL7 v2.5.1 ORU^R01 build, FHIR R4 bundle, outbox worker with retry |
| `pdf.py` | Report PDF |
| `feeds.py` | Folder watcher and DICOM C-STORE receiver |
| `hl7in.py` | MLLP listener for ADT (A01/A04/A08/A40) and ORM |
| `live.py` | Bed buffers, rolling analysis, advisory flags, acknowledgement |
| `simulator.py` | Bedside gateway simulator for testing |
| `statements.json` | Statement code → name table |
| `security.py` | Per-address sign-in limiter, read-access (view) log, address allow-lists, TLS contexts for the DICOM / HL7 ports and the HIS link |
| `notify.py` | Critical-result notifications and the optional e-mail sender (retries; no patient data in the message) |
| `triage.py` | Server-side triage (same rules as the web app; shared test cases in `shared/triage-cases.json`) |
| `records.py` | Search, patient export (ZIP), erasure with retention guard, retention listing |
| `holter_report.py` | Holter report content, PDF, HL7 ORU^R01, FHIR, beat-count adjustment for relabelled beats |
| `siteconfigs.py` | Site threshold files: upload, history, switch on / roll back, restore at start-up |
| `__main__.py` | CLI: `serve`, `init`, `create-user`, `set-password`, `backup`, `verify-audit [--anchor]`, `audit-anchor`, `live-simulator` |

### 3.2 API (prefix `/api`)
- Session: `POST /login`, `POST /login/totp`, `POST /logout`, `GET /me`, `POST /me/password`, `POST /me/totp/setup`, `POST /me/totp/enable`,
  `GET /auth/oidc/start`, `GET /auth/oidc/callback`
- Data: `GET /catalog`, `GET /ecg/{id}`, `GET /holter/{id}`, `GET /holter/{id}/signal`, `GET /patients`,
  `POST /upload`, `POST /recordings/{id}/patient`
- Reviews: `GET /reviews`, `GET|PUT /reviews/{id}`, `GET /reviews/{id}/history`, `POST /reviews/{id}/sign` (body: password or two-factor code), `GET|PUT /holter/{id}/beats` (relabel)
- Reports (12-lead `E…` and Holter `H…`): `GET /report/{id}.pdf`, `.hl7`, `.fhir.json`
- Records: `GET /search`, `GET /patients/{id}/export`, `DELETE /patients/{id}` (typed MRN), `GET /retention`, `GET /catalog?include=…`
- Notifications: `GET /notifications`, `POST /notifications/{n}/ack`, admin: `GET /notifications/history`, `GET|PUT /notify-settings`, `POST /notify-settings/test`
- Site thresholds: `GET /site-config`, `POST /site-config`, `POST /site-config/{n}/activate`, `POST /site-config/deactivate`
- Integration: `GET /outbox`, `POST /outbox/{n}/retry`, `GET|PUT /his`, `GET|PUT /feeds`
- Live: `GET /live`, `GET /live/beds`, `POST /live/ingest`, `GET /live/{bed}/trace`,
  `POST /live/{bed}/flags/{flag}/ack`, `GET|PUT /live/settings`
- Admin: `GET|POST /users`, `PATCH /users/{name}`, `GET|PUT /auth-settings`, `GET|PUT /settings`,
  `GET /audit`, `GET /audit/verify[?anchor=n:hash]`, `GET /audit/anchor`, `GET /models` (engine, models, AF modes)
- Public: `GET /health`

### 3.3 Database (SQLite, WAL, `/data/cardiotic.db`, schema version 5)
Tables: `users`, `sessions`, `challenges`, `patients`, `recordings`, `reviews`, `review_versions`, `beat_labels`, `outbox`, `notifications`, `site_configs`, `audit`, `settings`, `meta`. Migrations are applied in order at start-up.
- `recordings`: `summary` (analysis JSON), `detail` and `signal` blobs (analysis detail and waveform), `file_sha256` for duplicate detection.
- `reviews`: one row per recording with a `version` counter (conflict detection); history is in the audit log. `audit` rows carry the previous hash and their own hash.
- Writes use short transactions; sign + outbox insert happen in one transaction.

### 3.4 Security architecture
- Passwords: scrypt; minimum length, no user name inside, last 5 not reusable, optional expiry, forced change for issued passwords; account lockout and a per-address block (`CARDIOTIC_LOGIN_IP_LIMIT`; `X-Forwarded-For` trusted only from `CARDIOTIC_TRUSTED_PROXIES`).
- Sessions: random token (only its hash stored), idle and absolute timeouts, cookie `HttpOnly`, `SameSite=Strict`, `Secure` when `CARDIOTIC_COOKIE_SECURE`; every write needs `X-Requested-With`; a "choose a new password" or "set up two-factor" session can use nothing else.
- Signing needs the signer's password or two-factor code again (`auth.reauthenticate`); failures count toward the lockout.
- Headers: strict CSP (the one inline theme script allowed by its SHA-256), `X-Frame-Options`, `nosniff`, no referrer. Request bodies capped and always drained.
- Authorisation by role per route (`_role`); administrators cannot alter reviews.
- DICOM and HL7 ports: address allow-lists, AE-title allow-list, optional TLS (client certificates optional); the HIS link can use TLS too.
- Audit: reads of patient data are logged; the hash chain is keyed (HMAC-SHA-256, key from `CARDIOTIC_AUDIT_KEY` / key file); anchors (`audit-anchor`) prove nothing earlier changed or was removed; the server refuses to start on a keyed log without its key.
- XML from machines is parsed with `defusedxml`.
- Container: non-root user, read-only root file system, port bound to 127.0.0.1 behind the hospital's TLS proxy; hashed dependency lock, base images pinned by digest.
- Known gaps (`05_OWNER_TODO.md`, `regulatory/THREAT_MODEL.md`): no independent penetration test; audit key beside the database by default; allow-lists are empty until the hospital sets them; no encryption at rest in the product.

## 4. Data flows

**Upload and read**
1. Browser/feeds → `POST /upload` (or a feed) → engine reads, analyses → `recordings` + draft `reviews`.
2. Worklist (`/catalog`) shows triage; cardiologist opens `/ecg/{id}`, edits via `PATCH /reviews/{id}`.
3. `POST /reviews/{id}/sign` → report built, outbox row inserted, audit written (one transaction).
4. Outbox worker sends HL7 over MLLP (PDF attached); success/failure recorded; retries with backoff.

**Live Assist**: gateway → `POST /live/ingest` → per-bed ring buffer (300 s) → every 5 s a 60 s window is analysed →
rules in `01_FEATURES_AND_LOGIC.md` §3.8 → advisory flags → acknowledged by a named user.

## 5. Frontend

- Entry: `src/app/` — `providers.tsx`, `router.tsx`, `server-store.tsx` (live data via `lib/server.ts`),
  `demo-store.tsx` (static sample data). Mode is chosen from `/api/health`.
- `src/data/`: `api.ts`, `clinical.ts` (triage and clinical rules), `derived.ts`, `types.ts`.
- Features (`src/features/`): `review`, `worklist`, `holter`, `monitoring` (incl. `LiveBoard`), `upload`, `settings`
  (incl. `ServerSettings`), `auth` (incl. `TwoFactorSetup`), `reports`, `audit`, `patients`, `ai`.
- Tests: vitest (unit), Playwright `e2e/` (static) and `e2e-server/` (against a real server: sign-in, review/sign,
  two-factor, Holter, live, printout).

## 6. Deployment

- `Dockerfile`: multi-stage; builds the frontend, installs the hashed lock file (`deploy/requirements.lock`) then the three product packages; Python 3.13 and Node 22 base images pinned by digest; non-root user; port 8720; healthcheck
  on `/api/health`; data in `/data`.
- `docker-compose.yml`: binds `127.0.0.1:8720`; optional DICOM (11112) and HL7 (2576) ports; volume for `/data`.
- `deploy/`: `INSTALL.md`, `nginx.conf.example` (TLS), `cardiotic.service` (systemd option), `backup.sh`,
  `restore_drill.sh`, `loadtest.py`, `make_notices.py`, `requirements.in/.lock`, `sbom/`, `smoke_test.sh`, `container_test.sh`, `make_test_report.py`, and the saved test report/screenshots. Continuous integration: `.github/workflows/ci.yml`.
- Minimum for a site: one server (CPU only is enough; inference runs on ONNX Runtime CPU), reverse proxy with a
  hospital TLS certificate, persistent volume with daily backup, network paths to the HIS.

### Environment variables
| Variable | Meaning |
|---|---|
| `CARDIOTIC_DB` | database path (default `/data/cardiotic.db`) |
| `CARDIOTIC_PORT` | host port in compose |
| `CARDIOTIC_STATIC` | folder with the built frontend |
| `CARDIOTIC_MAX_UPLOAD` | max upload size |
| `CARDIOTIC_IDLE_MINUTES`, `CARDIOTIC_SESSION_HOURS` | session limits |
| `CARDIOTIC_COOKIE_SECURE` | set when behind HTTPS |
| `CARDIOTIC_SITE_CONFIG` | path to the signed site threshold file |
| `CARDIOTIC_NEW_PASSWORD` | initial admin password at `init` |
| `CARDIOTIC_ENGINE_MODELS`, `_THREADS`, `_MAX_BODY` | engine model folder, threads, standalone API body limit |
| `CARDIOTIC_AUDIT_KEY` / `CARDIOTIC_AUDIT_KEY_FILE` | key for the audit chain (default: `<database>.audit.key`, created on first start) |
| `CARDIOTIC_LOGIN_IP_LIMIT`, `CARDIOTIC_TRUSTED_PROXIES` | failed sign-ins per address before a block; proxies whose `X-Forwarded-For` is believed |
| `CARDIOTIC_CATALOG_FULL`, `CARDIOTIC_CATALOG_DAYS` | archive size up to which the worklist loads everything; days of signed recordings loaded beyond it |

## 7. Testing and quality

| Suite | Location | Count / result |
|---|---|---|
| Research | `ml/tests` | 35 pass (includes the AF operating-point rule) |
| Engine | `engine/tests` | 56 pass (formats, integrity, determinism, standalone service, AF mode, XML attacks) |
| Server | `server/tests` | 116 pass (security, records, notifications, site thresholds, Holter, audit key, CLI, feeds, HL7, SSO, live, concurrency) |
| Frontend unit | `frontend/tests` | 28 pass (includes triage cases shared with the server and the time-zone logic) |
| Browser, static | `frontend/e2e` | 2 flows |
| Browser, server | `frontend/e2e-server` | 10 flows (sign-in and signing with password confirmation, forced password change, critical banner, two-factor, Holter relabel and PDF, site thresholds, search, 2.5 h Holter, Live Assist, paper ECG) |
| Equivalence / digitiser / Holter | `engine/validation/*.py` | pass |
| Docker acceptance | `deploy/container_test.sh` | 10 checks, 19 screenshots in `deploy/test-screenshots` |
| Load | `deploy/loadtest.py` | 0 errors; results in `docs/OPERATIONS_RUNBOOK.md` |
| Static checks | typecheck, ESLint | clean |
| Dependencies | `pip-audit` (locked set), `npm audit` | 0 known vulnerabilities |

Reproducibility: training scripts live in `ml/cardiotic_ml/experiments*.py`; results are produced into `ml/reports/*.json` and rendered by `report.py` into `RESULTS.md`. Models enter the engine only through
`export.add_to_engine`, which records hashes and the export check. Regulatory drafts that point at this document: `docs/regulatory/`.

## 8. Third-party licences (summary)

All components are listed in `THIRD_PARTY_NOTICES.md` (generated from what is installed by `deploy/make_notices.py`) and in the SBOMs in `deploy/sbom/`. Permissive: numpy, scipy, onnxruntime, pydicom,
pynetdicom, pypdf, pillow, sierraecg, defusedxml, cryptography, and about 140 npm packages (MIT/ISC/Apache/BSD, one OFL font). **Copyleft:** `ldap3` is LGPL-3 (used unmodified as a library).
The product's own licence is a placeholder in `LICENSE` until the owner's counsel supplies the terms.
