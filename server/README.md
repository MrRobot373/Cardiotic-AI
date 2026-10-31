# cardiotic-server

The hospital-side server of Cardiotic AI: accounts, ECG upload and analysis (through `cardiotic-engine`),
worklist data, review and sign-off, audit log, and delivery of signed reports to the HIS. One process, one
SQLite file, standard library plus the engine. It runs on the hospital's own server.

## Run it

```bash
pip install ./ml ./engine ./server
export CARDIOTIC_DB=/var/lib/cardiotic/cardiotic.db
cardiotic-server init
CARDIOTIC_NEW_PASSWORD='…' cardiotic-server create-user kdesai "Kiran Desai" admin --title "IT administrator"
cardiotic-server serve --host 127.0.0.1 --port 8720 --static frontend/dist [--site-config site_config.json]
```

Put TLS in front (the hospital's reverse proxy) and set `CARDIOTIC_COOKIE_SECURE=1`. Other commands:
`set-password USER`, `backup FILE` (consistent copy while running), `verify-audit`.

## What it enforces

| Rule | Where |
|---|---|
| Passwords: scrypt, ≥ 10 characters, not containing the user name; 5 failed sign-ins lock the account for 5 minutes; unknown user and wrong password look identical | `auth.py` |
| Sessions: HttpOnly, SameSite=Strict cookie (or Bearer token for API clients); 15 min idle and 12 h absolute timeout (`CARDIOTIC_IDLE_MINUTES`, `CARDIOTIC_SESSION_HOURS`); cookie requests that change data need `X-Requested-With: cardiotic` | `app.py` |
| Roles: **cardiologist** decides findings and signs; **technician** uploads, matches patients, sends for reading or requests a repeat; **admin** manages users, settings, HIS connection and audit, and cannot sign or change reviews | `store.py` |
| Signing: every AI finding must be accepted or rejected first; a signed report is read-only until a cardiologist amends it (audit-logged); stale edits are refused (version check) | `store.py` |
| Audit log: append-only hash chain; `GET /api/audit/verify` / `cardiotic-server verify-audit` finds any edited or deleted entry | `db.py` |
| Duplicates: the same ECG exported twice is recognised by its samples, not its file | `store.py` |
| No raw bodies in logs; errors never include patient data or internals | `app.py` |

## API (JSON, under `/api`)

`POST /login` · `POST /logout` · `GET /me` · `GET /catalog` · `GET /ecg/{id}` · `GET /holter/{id}` (+ `/signal`) ·
`GET /reviews` · `PUT /reviews/{id}` · `POST /reviews/{id}/sign` · `POST /upload` (raw file; headers `X-Filename`,
`X-Fs`, `X-Units`, `X-Patient-MRN`, `X-Location`, `X-Ordered-By`) · `POST /patients` ·
`POST /recordings/{id}/patient` · `GET|PUT /settings` · `GET|PUT /his` · `GET /outbox` · `POST /outbox/{id}/retry` ·
`GET /report/{id}.hl7` · `GET /report/{id}.fhir.json` · `GET|POST|PATCH /users` · `GET /audit` · `GET /audit/verify`.

Uploads accept every format `cardiotic-engine` reads (CSV, EDF, HL7 aECG, GE MUSE XML, DICOM, SCP-ECG). A file with
12 leads (or I, II and V1–V6) becomes an ECG; a single lead becomes a Holter recording. A file with no patient ID
is kept under an `UNMATCHED-…` patient until a technician matches it.

## HIS delivery

Signing queues an HL7 v2.5.1 `ORU^R01` (MLLP) in the outbox; a background worker sends it to the host and port set
under `PUT /api/his`, retrying with growing waits (up to 12 tries), and records each acknowledgement or rejection
in the audit log. Signing never waits for the HIS. `GET /report/{id}.fhir.json` returns a FHIR R4 transaction
bundle (Patient, Observations, DiagnosticReport) for sites that prefer REST.

**Limits, stated plainly:**
- The report is sent as text, not as a PDF. The printable report in the web app produces the PDF.
- Measurement codes are LOINC (8867-4, 8625-6, 8633-0, 8634-8, 8636-3, 8632-2); statements use the SCP-ECG code as a local
  code. Each hospital maps these to its own dictionary during integration.
- Verified against our own MLLP listener and structural FHIR checks, not against a real HIS or the official FHIR
  validator. Integration testing with the hospital's interface engine is part of every installation.
- ADT feeds (patients in from the HIS) are not implemented; patients are created by hand or from the file's patient ID.
