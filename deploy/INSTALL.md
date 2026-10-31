# Installing Cardiotic AI at a hospital

One server process (web app + API + AI engine + models) and one database file. Nothing is downloaded at run
time and no patient data leaves the machine except the HL7 messages you configure to the HIS.

**Status: both install paths are tested.**
- `deploy/container_test.sh` checks the image as `docker compose` runs it (read-only, no capabilities, named volume). It checks:
  - start-up and model verification, a non-root user, a read-only filesystem, users created with the CLI;
  - the whole reading flow in a browser, with a screenshot per step in `deploy/test-screenshots/`;
  - that data survives a restart, a backup with audit verification, and that a tampered model file is refused.
- `deploy/smoke_test.sh` checks the same steps in a clean Python environment without containers.

## 1. What you need

| | |
|---|---|
| Server | Linux, 4 CPU cores, 8 GB RAM, 50 GB disk (the database grows with ECGs: about 150 KB per 12-lead ECG, 1.5 MB per 30 min Holter) |
| Software | Docker 24+ *or* Python 3.11+ |
| Network | A hostname and TLS certificate from the hospital's CA; a reverse proxy (nginx example in `deploy/nginx.conf.example`) |
| For the HIS | The interface engine's host and MLLP port; a test environment first |
| People | An IT administrator, the cardiology lead (approves operating points), a technician for testing |

## 2. Install

**Container** (recommended):

```bash
docker build -t cardiotic:0.1.0 .                       # where the internet is available
#   Docker Hub rate-limited? the same official images: --build-arg NODE_IMAGE=mirror.gcr.io/library/node:22-slim --build-arg BASE_IMAGE=mirror.gcr.io/library/python:3.12-slim
#   behind a TLS-inspecting proxy: --network host --secret id=ca,src=proxy-ca.pem --build-arg HTTPS_PROXY=…   (the CA is not stored in the image)
docker save cardiotic:0.1.0 | gzip > cardiotic-0.1.0.tar.gz   # move to the hospital, then: docker load < …
docker compose up -d
docker compose exec cardiotic cardiotic-server create-user admin "IT Administrator" admin   # asks for a password
deploy/container_test.sh                                 # optional: the acceptance test above (own project, volume and port; leaves the installation alone)
```

**Without containers:**

```bash
python3 -m venv /opt/cardiotic/venv
/opt/cardiotic/venv/bin/pip install ./ml ./engine ./server "pydicom>=2.4"
cp -r frontend/dist /opt/cardiotic/web                  # built with: cd frontend && npm ci && npm run build
useradd --system cardiotic && install -d -o cardiotic /var/lib/cardiotic
cp deploy/cardiotic.service /etc/systemd/system/ && systemctl enable --now cardiotic
CARDIOTIC_DB=/var/lib/cardiotic/cardiotic.db /opt/cardiotic/venv/bin/cardiotic-server create-user admin "IT Administrator" admin
```

Then put TLS in front (`deploy/nginx.conf.example`). The server listens on 127.0.0.1 only. Open the hospital's
hostname, sign in as the administrator, and add users under Settings → Users & roles.

The server refuses to start if any model file differs from the signed manifest (exit code 3), or if a site
configuration is for other models or not signed off (exit code 4).

## 3. Configure the site

1. **Name** — Settings → Site. It appears on sign-in and on every report.
2. **Users** — a cardiologist reads and signs; a technician uploads, matches patients, sends for reading; an administrator manages users, settings and the HIS connection. Passwords: 10+ characters; five wrong attempts lock the account for 5 minutes; sessions end after 15 minutes idle.
3. **AI operating points** — the model's yes/no thresholds do not transfer between hospitals (ml/reports/RESULTS.md §7.3, §7.7). Collect a few hundred of the site's own ECGs, have cardiologists label them with SCP-ECG codes (`file,statements` CSV), then:
   ```bash
   cardiotic-engine site-config --dir ecgs/ --labels labels.csv --site-id HOSPITAL-1 --out site_config.json
   ```
   This writes a **draft** and a report next to it. The cardiology lead reviews the report and fills in `approved_by` and `approved_at`; the server then starts with `--site-config site_config.json` (or `CARDIOTIC_SITE_CONFIG`). Without one, the model's own thresholds are used and the Site screen says so. Statements with fewer than 20 site examples keep the model's threshold. Do not claim atrial flutter or long QT: they stay weak even with site thresholds.
4. **HIS** — Settings → Integrations: host, port, receiving facility. Signed reports are queued and delivered as HL7 v2.5.1 ORU^R01 over MLLP; failures retry with growing waits and show in the delivery list. Test against the hospital's test interface first: the measurement and statement codes (LOINC / SCP-ECG) are mapped to the hospital's dictionary during integration. Reports go as text, not PDF; ADT feeds are not implemented.
5. **ECG machines** — export to a folder or send DICOM/HL7 aECG/MUSE XML, and upload. Direct machine feeds (a watched folder or DICOM storage endpoint) are **not built yet**: today a technician uploads files. Each cart model must be tested with real exports before it is listed as supported: the readers are tested against files built from the format specifications, not vendor files.

## 4. Operate

| Task | How |
|---|---|
| Backup | `deploy/backup.sh /backup/cardiotic` nightly from cron; copies are patient data: encrypt, keep off-server, test a restore |
| Restore | Stop the server, replace the database file with a backup (`gunzip`), start, run `cardiotic-server verify-audit` |
| Upgrade | Install the new version, start: the database upgrades in place (take a backup first). Model files are verified at start |
| Audit | Settings or `GET /api/audit`; `cardiotic-server verify-audit` finds any edited or deleted entry |
| Forgotten password | `cardiotic-server set-password USER` (ends the user's sessions) |
| Logs | Request lines only; no ECG data or patient names |

## 5. Before clinical use

This software is not cleared as a medical device. Its results come from public research datasets and have
not been validated on this hospital's patients. Clinical use needs: the site validation (step 3), a usability
study, regulatory clearance for the market (CDSCO / FDA, see docs/PRODUCT_PLAN.md) and the hospital's own
clinical safety sign-off. A cardiologist confirms every finding before a report is signed; nothing is sent to
the HIS before that.

## 6. Security checklist

- [ ] TLS in front; `CARDIOTIC_COOKIE_SECURE=1`; HTTP redirects to HTTPS
- [ ] Server reachable only from the hospital network; port 8720 bound to 127.0.0.1
- [ ] Database and backups on encrypted storage; backup copies off-server
- [ ] Administrator accounts named, not shared; unused accounts deactivated
- [ ] Time synchronised (audit entries and signatures carry the server clock)
- [ ] Interface to the HIS on an isolated segment (MLLP carries no encryption; use the hospital's VPN or TLS wrapper)
