# Cardiotic AI — frontend (demo)

The clinician-facing app, built to give demos **without a backend**. It uses the same design system as
MED AI: React 18, TypeScript, Vite, Tailwind, Radix UI and lucide icons.

**Everything the AI shows is real.**
- Every waveform is a real ECG from a public research database: PTB-XL test fold, Chapman–Shaoxing, or
  MIT-BIH test records, all from patients the models never trained on.
- Every measurement, beat, rhythm and finding is the actual output of `cardiotic-engine`, mistakes included.

**What is not real:**
- Patient names, record numbers, doctors and dates are invented.
- Reviews and sign-offs are stored in the browser only.
- Research use only.

## Screens

Screenshots: [worklist](screenshots/worklist-light.png) · [ECG review](screenshots/review-light.png) · [dark](screenshots/review-dark.png) · [phone](screenshots/review-mobile.png) · [Holter](screenshots/holter-light.png) · [monitoring](screenshots/monitoring-dark.png) · [patient](screenshots/patient-light.png) · [report](screenshots/report-light.png) · [AI & validation](screenshots/ai-light.png)


| Screen | What it shows |
|---|---|
| Sign-in | Demo users: cardiologist (can sign), technician (records, sends for reading), IT admin |
| Worklist | ECGs pre-read by the AI and ordered by urgency (critical / urgent / routine / normal), with key findings, rate and QTc |
| ECG review | 12-lead ECG on ECG paper: 3×4, 6×2 or 12×1 layout, 25/50 mm/s, gain, beat markers and RR intervals, a drag caliper. Also median beats per lead with the AI's fiducial points, which can be edited (intervals are recomputed and marked "edited"). AI measurements are flagged against reference ranges; QTc is not interpreted with a wide QRS. AI findings show probability, threshold and confidence, with Accept / Reject / Show on ECG, plus "add finding". Comparison with the previous ECG, sign-off, and repeat request. Demo only: the dataset cardiologists' labels |
| Report | Printable A4 report (DRAFT until signed), with the engine version and model fingerprints in the footer |
| Patients / patient | ECG history, HR / PR / QRS / QTc trends against usual ranges, Holter recordings |
| Holter | Beat-by-beat review of 30-minute recordings: summary, HR trend with AF shaded, rhythm timeline, event list (AF episodes, ventricular runs and couplets, pauses), strip viewer with beat labels, and agreement with the dataset cardiologists |
| Monitoring | OT/ICU board (future product). Traces replay real recordings; heart rate comes from AI beats; SpO₂/BP are simulated. States: flags, diathermy, offline |
| Upload | Drop zone plus simulated analysis steps; connected ECG machines and file formats |
| AI models & validation | Every model's task, test data, key numbers and known weaknesses, generated from `ml/reports` |
| Audit log, Settings | Who did what; site operating points, appearance (theme, accent, ECG paper colour), integrations, roles |

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
npm run demo-data                         # public/demo/catalog.json, ecg/*.json, holter/*  (real engine output)
python3 scripts/build_validation.py       # public/demo/validation.json (numbers for the AI page)
```

Static hosting must send unknown paths to `index.html` (single-page app).
