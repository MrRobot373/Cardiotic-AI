# Cardiotic AI — Operations runbook

For the hospital's IT team (and the vendor's support engineer). Install is in `deploy/INSTALL.md`; this is how to *run* it.
Commands assume the container (`docker compose exec cardiotic …`); on a systemd install drop the prefix.

## 1. What to watch

| What | How | Healthy | Act when |
|---|---|---|---|
| Service up, models verified | `GET /api/health` (every minute from the hospital monitor) | `{"status": "ok", "models_verified": true}` | no answer for 3 minutes → section 5.1 |
| Delivery to the HIS | Settings → Integrations → Recent deliveries, or `GET /api/outbox` | all `sent` | `pending` older than 15 min or any `failed` → 5.2 |
| Machine feeds | Settings → Integrations → ECG machines (status) | "Receiving", last received recent | "Check" badge → read the message under it |
| Critical results waiting | the red banner in the app; Settings → Result notifications → Recent | acknowledged within the hospital's own target | unacknowledged results are the clinical team's, not IT's |
| Audit chain | `cardiotic-server verify-audit` nightly (cron), non-zero exit alerts | exit 0 | exit 5 → 5.4 |
| Disk | volume `/data` usage | < 70% | > 80% → grow the volume; the database grows about 1 MB per 12-lead ECG and about 20 MB per 24 h Holter |
| Backups | `deploy/backup.sh` output and file dates | one new file a night, "audit chain ok" | missing or failed → run it by hand and read the error |
| Certificates | expiry of the TLS certificate on the reverse proxy and of any DICOM/HL7 TLS files | > 30 days left | < 30 days → renew (5.6) |

Logs go to the container's standard output (`docker compose logs cardiotic`). They contain request lines and errors, no patient data or report text.

## 2. Backup and restore

1. **Nightly:** `deploy/backup.sh /backup/cardiotic` from cron. It writes a consistent copy while the server runs, verifies its audit chain, compresses it, keeps 30 days.
2. **Copy the backups off the server** and encrypt them (they hold patient data).
3. **Keep the audit key separately.** The key (`CARDIOTIC_AUDIT_KEY`, or the file `cardiotic.db.audit.key` next to the database) is *not* in the backup on purpose: someone who steals only the database or a backup cannot then recompute the audit log. Store a copy where the hospital keeps its other secrets (password vault, sealed envelope with the CISO). **Without it the log cannot be verified, and the server refuses to start on a keyed database** (exit code 6, clear message).
4. **Restore drill — every quarter:** `deploy/restore_drill.sh /backup/cardiotic/cardiotic-<date>.db.gz /path/to/audit.key`. It unpacks the backup into a temporary folder, checks database integrity, verifies the audit chain, prints record counts and starts a throw-away server. Keep the output with the hospital's records. Target to agree with the hospital: *recovery point* ≤ 24 h (nightly backup; shorten with more frequent runs), *recovery time* ≤ 2 h.
5. **Real restore:** stop the service; replace the database file with the gunzipped backup (and make sure the audit key is available); start; run `verify-audit`; sign in and open a recent ECG. Reports signed after the backup was taken are lost from the server — they were also sent to the HIS, which is the second record.

## 3. Audit anchors (proof that the log was not rewritten)

The audit log is hash-chained and keyed. To make removal of the *latest* entries detectable too, record an anchor outside the server regularly:

```
cardiotic-server audit-anchor        # prints  <entries>:<head hash>
cardiotic-server verify-audit --anchor 1842:3fa9…   # later: proves nothing up to entry 1842 changed or was removed
```
Suggested: monthly, e-mail the line to the hospital's records office (or print it for the file). `GET /api/audit/anchor` returns the same for the administrator.

## 4. Upgrade and roll back

1. Read the release notes. Take a backup (`deploy/backup.sh`) and note the current image tag.
2. Load the new image (`docker load < cardiotic-X.tar.gz`), change the tag in `docker-compose.yml`, `docker compose up -d`.
3. The database upgrades itself on start (schema version in `meta`). Model files are verified; a changed model file stops the service (exit 3).
4. If the site uses threshold files (Settings → Site thresholds) and the statement model changed, the active file is switched off at start and the audit log says so: re-validate the thresholds for the new model (`cardiotic-engine site-config`) before switching a new file on.
5. Check `GET /api/health`, sign in, open an ECG, check Recent deliveries.
6. **Roll back:** stop; put the old image tag back; **restore the pre-upgrade backup** (a newer schema is not read by an older version); start.
7. Run the restore drill and `verify-audit` after any upgrade.

## 5. When something is wrong

### 5.1 The service does not answer
`docker compose ps`, `docker compose logs --tail 100 cardiotic`. Exit codes of `cardiotic-server serve`:

| Code | Meaning | Do |
|---|---|---|
| 3 | A model file does not match its recorded checksum | Do not edit files. Reinstall the image from the vendor; keep the log line; tell the vendor |
| 4 | The site threshold file given in `CARDIOTIC_SITE_CONFIG` is refused | Message says why (wrong model, not signed off). Use the right file or remove the variable |
| 6 | Keyed audit log but the audit key is missing | Restore the key (3 in section 2); do not create a new one |
| other | database file locked, disk full, permission | read the log; free space; the volume must be writable by uid 10001 |

### 5.2 Reports are not reaching the HIS
Signed reports are safe in the outbox and retried with growing waits (up to 12 tries). Read the error beside the message (Settings → Integrations): "cannot reach the HIS" = network/firewall/port or the HIS interface engine is down; "HIS rejected the message" = the HIS answered with an error (read its text; usually an unknown patient or a mapping). After fixing, press **Retry now**. If the HIS connection uses TLS, check the certificate dates (5.6).

### 5.3 ECGs from machines stop arriving
Settings → Integrations → ECG machines. DICOM: check the AE title and address allow-lists (a refused association is listed in the audit log as "DICOM connection refused"), the port, TLS files. Folder feeds: the folder must be reachable by the service user; unreadable files go to `failed/` with a `.reason.txt`.

### 5.4 The audit check fails (exit 5)
Treat it as a security incident. Do not repair anything. Keep the database and the latest backups unchanged, note the first bad entry number printed by `verify-audit`, tell the hospital's information-security officer and the vendor. Compare with the last anchor and with older backups (`restore_drill.sh`) to find when the change happened.

### 5.5 Someone is locked out / forgot a password / lost their phone
Settings → Users (administrator). *Reset password* gives a temporary one the person must change at first sign-in. *Reset two-factor* clears the authenticator. After five wrong passwords an account locks for 5 minutes; more than 20 failures from one computer within 10 minutes block that computer for 15 minutes (the audit log shows "Sign-in blocked for this address"). Directory and single-sign-on accounts are changed in the hospital directory.

### 5.6 Certificates
The web certificate lives on the reverse proxy (`deploy/nginx.conf.example`). DICOM/HL7 TLS files are paths set in Settings → Integrations; replace the files and press Save to reload the listener. HIS connections with TLS read the files at each delivery.

### 5.7 A patient asks for their data or its removal
Administrator, patient page: **Export data** (ZIP with the recordings, reviews, review history and report PDFs) and **Erase**. Erasure is refused while a signed report is younger than the retention period (Settings → Site; the hospital's records policy and the law decide it) and while a message for the patient is still waiting for the HIS. The audit log keeps its earlier entries (they carry record numbers and MRNs, not names) and records the erasure with the internal patient number only. `GET /api/retention` lists what is past the retention period.

## 6. Capacity and speed (measured)

`deploy/loadtest.py`, one server process on 4 CPU cores, 1 inference thread, SQLite; copies of one real 12-lead ECG; 2 minutes each run; 0 errors in both (the 12-lead ECG analysis itself takes about 0.1–0.3 s of CPU).

| Scenario | Archive at the end | Opening an ECG (median / 95th) | Worklist refresh (95th) | Reviews refresh (95th) | Upload + analysis (median / 95th) | Signing (95th) |
|---|---|---|---|---|---|---|
| 20 readers refreshing every 5 s, 3 uploaders (about 4.6 ECGs/s in total), 1 signer | 572 recordings | 0.006 s / 0.03 s | 0.33 s | 0.45 s | 0.09 s / 0.29 s | 0.17 s |
| Same with refresh every 1 s (a stress test, 5× the real refresh rate) | 436 recordings | 0.014 s / 0.05 s | 1.04 s | 1.42 s | 0.35 s / 0.62 s | 0.35 s |

Real use is far lighter: the web app refreshes every 20 s and a busy department uploads about one ECG a minute. What was **not** tested: archives beyond a few thousand recordings under load, hundreds of simultaneous users, a network drive for the database, 24-hour Holters under load, the container on the hospital's real hardware. Run `loadtest.py` on the pilot hardware before go-live (use a test installation). Above 5,000 recordings the worklist loads open and recent ECGs only, and older ones are found with search; moving to a server database is the next scaling step (see `docs/04_ARCHITECTURE.md`).

## 7. Routine calendar

| When | Task |
|---|---|
| daily | glance at health, Recent deliveries, backup result |
| weekly | review failed deliveries/feeds; the CI/dependency scan results (vendor) |
| monthly | audit anchor recorded; users list reviewed (leavers deactivated) |
| quarterly | restore drill; access review; certificate dates; load test after hardware changes |
| yearly | threshold re-validation with the cardiology lead; policy review; penetration test (agreed with the vendor) |
