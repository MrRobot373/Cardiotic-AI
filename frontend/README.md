# Cardiotic AI — frontend

The clinician-facing app. This build runs **without a backend** (static data, reviews kept in the browser) so it can be shown anywhere. It uses the same design system as
MED AI: React 18, TypeScript, Vite, Tailwind, Radix UI and lucide icons.

**Everything the AI shows is real.**
- Every waveform is a real ECG from a public research database: PTB-XL test fold, Chapman–Shaoxing, or
  MIT-BIH test records, all from patients the models never trained on.
- Every measurement, beat, rhythm and finding is the actual output of `cardiotic-engine`, mistakes included.

**What is not real:**
- Patient names, record numbers, doctors and dates are invented.
- Reviews and sign-offs are stored in the browser only.
- The UI carries no "demo" or "research use" wording, by product decision. Dataset provenance is visible only with **Settings → Validation view** on.

## Screens

Screenshots: [worklist](screenshots/worklist-light.png) · [ECG review](screenshots/review-light.png) · [dark](screenshots/review-dark.png) · [phone](screenshots/review-mobile.png) · [Holter](screenshots/holter-light.png) · [monitoring](screenshots/monitoring-dark.png) · [patient](screenshots/patient-light.png) · [report](screenshots/report-light.png) · [sign-in](screenshots/login-light.png) · [upload](screenshots/upload-light.png) · [AI & validation](screenshots/ai-light.png)


| Screen | What it shows |
|---|---|
| Sign-in | User name + password (any password; SSO button fills one). Users: `arao` cardiologist (can sign), `rsawant` technician (records, sends for reading), `kdesai` IT admin |
| Worklist | ECGs pre-read by the AI and ordered by urgency (critical / urgent / routine / normal), with key findings, rate and QTc |
| ECG review | 12-lead ECG on ECG paper: 3×4, 6×2 or 12×1 layout, 25/50 mm/s, gain, beat markers and RR intervals, a drag caliper. Also median beats per lead with the AI's fiducial points, which can be edited (intervals are recomputed and marked "edited"). AI measurements are flagged against reference ranges; QTc is not interpreted with a wide QRS. AI findings show probability, threshold and confidence, with Accept / Reject / Show on ECG, plus "add finding". Comparison with the previous ECG, sign-off, and repeat request. With Validation view on: the dataset cardiologists' labels |
| Report | Printable A4 report (DRAFT until signed), with the engine version and model fingerprints in the footer |
| Patients / patient | ECG history, HR / PR / QRS / QTc trends against usual ranges, Holter recordings |
| Holter | Beat-by-beat review of 30-minute recordings: summary, HR trend with AF shaded, rhythm timeline, event list (AF episodes, ventricular runs and couplets, pauses), strip viewer with beat labels, and, with Validation view on, agreement with the dataset cardiologists |
| Monitoring | OT/ICU board (Live Assist, future product). Traces replay real MIT-BIH recordings; heart rate comes from AI beats; SpO₂/BP are made up. States: flags, diathermy, offline |
| Upload | Drop zone (a dropped file is shown as queued), import from a machine inbox (runs the analysis steps on a stored recording), connected ECG machines and file formats |
| AI models & validation | Every model's task, test data, key numbers and known weaknesses, generated from `ml/reports` |
| Audit log, Settings | Who did what; site name, operating points, Validation view, reset of local review data (admin), appearance (theme, accent, ECG paper colour), integrations, roles |

## Two ways to run

One build, two modes, chosen when the app starts: if `/api/health` answers, the app runs against the
**Cardiotic server** (real accounts, uploads, storage, sign-off, audit, HIS delivery: see
[../server/README.md](../server/README.md)); if not, it runs **static** on the recorded sample data in
`public/data`, with reviews kept in the browser. In server mode there are no sample users, no single sign-on
button and no Monitoring board (that screen replays recordings and is still in development).

```bash
npm run dev:server        # Vite on :5174 proxying /api to a server on :8720 (cardiotic-server serve)
npm run test:e2e:server   # builds the app, starts a real server on a fresh database and drives the whole flow
```

## Run it

```bash
npm install
npm run dev            # http://localhost:5174
npm run build          # static site in dist/ (any web server; set VITE_BASE=/path/ for a sub-path)
npm run preview
```

Checks:

```bash
npm run typecheck && npm run lint && npm test
PW_CHROMIUM=/path/to/chromium npx playwright test     # end-to-end: read, edit calipers, sign, report, audit, roles
node scripts/shots.mjs http://localhost:5174 shots   # screenshots of every screen (light, dark, phone); console errors; overflow
```

Rebuild the demo data, which needs the research environment and data:

```bash
npm run demo-data                         # public/data/catalog.json, ecg/*.json, holter/*  (real engine output)
python3 scripts/build_validation.py       # public/data/validation.json (numbers for the AI page)
```

Static hosting must send unknown paths to `index.html` (single-page app).
