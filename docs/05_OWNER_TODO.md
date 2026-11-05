# What remains — for the owner and management

Everything engineering could build and verify without a hospital, a regulator or outside data is built. **This file is what is left.** It is ordered: do the
sections top to bottom; most items can run in parallel once Section 1 is decided. For each item: *what to do*, *who*, *why it matters*, and *what is already
prepared* so nobody starts from nothing. Tick the boxes as you go.

Legend: **[BLOCKER]** nothing can ship to a patient without it · **[PILOT]** needed before a hospital pilot · **[LATER]** needed for general release.

---

## 1. Decide (week 1) — these decisions steer everything else

- [ ] **[BLOCKER] Intended use.** Choose Option A, B or C in `docs/regulatory/INTENDED_USE_DRAFT.md`. *Who:* owner + regulatory lead + clinical lead. *Why:* it fixes the regulatory route, the validation design, what you may say, and the label. Until you decide, the engine says "Research use only. Not a medical device", and that is correct.
- [ ] **[BLOCKER] Markets and order.** India first (CDSCO) then USA (FDA)? Or one only? *Prepared:* regulatory outline in `docs/03_MANAGEMENT_ACTIONS.md` §2.
- [ ] **Business model.** Sell to hospitals, to equipment makers (OEM, "Option C"), or both. An OEM contract changes who is the legal manufacturer.
- [ ] **Answer the open questions in `docs/PRODUCT_PLAN.md` §14** (partner hospital, QMS status, team/budget, research-use-only first release, US data source, first manufacturers).
- [ ] **Legal entity.** Fill in the copyright holder in `LICENSE` (currently a placeholder) and choose the licence terms for the software you sell (a lawyer should write the end-user agreement).
- [ ] **Move the repository to a company account** and enable GitHub Actions there (the CI workflow is written but has never run on a hosted runner).

## 2. People and company (weeks 1–4)

- [ ] **[BLOCKER] Name a regulatory/quality lead** (employee or consultant). They own the quality system and the filings. *Prepared:* the draft pack in `docs/regulatory/` (requirements with traceability, risk analysis, threat model, model cards, validation protocol, instructions for use) — a starting point for them, not a finished record.
- [ ] **[BLOCKER] Name a clinical lead** (a cardiologist). They own the clinical claims, the validation protocol, the site thresholds and the labelling wording.
- [ ] Name a **security/IT support contact** and a **vigilance contact** (who receives complaints and incidents) — they appear in the instructions for use and the customer contract.
- [ ] Company registration, tax, bank; **trademark search and filing for "Cardiotic AI"** in India and the USA; domain names; insurance (professional indemnity, product liability).

## 3. Regulatory (start now, runs for months)

- [ ] **[BLOCKER] Quality management system** — ISO 13485 (the consultant sets it up; software lifecycle IEC 62304, risk ISO 14971, usability IEC 62366). *Prepared:* requirements, risk and threat drafts to be adopted or rewritten into the QMS format. *Missing and only you can supply:* QMS procedures (change control, anomaly handling, release, complaint handling), the signed approvals.
- [ ] **[BLOCKER] India — CDSCO.** Confirm the device class and licence route for software that analyses ECGs (consultant). Prepare the technical file. *Prepared:* model cards, SBOM (`deploy/sbom/`), test reports, architecture, labelling draft.
- [ ] **[BLOCKER for USA] FDA.** Pre-submission meeting (Q-Sub) to agree predicate/De Novo, clinical evidence and the AI change plan. Cybersecurity file (SBOM ✔, threat model draft ✔, patch plan ✘). *Needs:* US-representative validation data (see 5).
- [ ] **Predetermined change control plan** for model updates (how a retrained model will be validated and released).
- [ ] **Standards test:** IEC 60601-2-25 (ECG analysis performance) needs the **licensed CSE database** — buy/arrange access (see 5); it is the referee for measurement accuracy. Today measurements are only compared with another algorithm.
- [ ] **Usability engineering** (IEC 62366): user needs, use-related risks, formative and summative tests with real cardiologists and technicians. *Prepared:* the software and the instructions draft. *Not done by anyone.*
- [ ] **Post-market:** complaint handling, vigilance/incident reporting, field safety actions, and a way for hospitals to verify an image came from you (signed release or checksum).

## 4. Clinical partner and validation (weeks 2–24)

- [ ] **[PILOT] Partner hospital (one, then a second with a different ECG device make).** Needs: a cardiology lead, IT contact, ethics approval, a data-sharing agreement. *Prepared:* an installable container, the install guide, runbook, restore drill, load test, site-threshold tool.
- [ ] **Ethics committee approval or waiver** for the retrospective study and for the silent-mode period. *Prepared:* the protocol template `docs/regulatory/CLINICAL_VALIDATION_PROTOCOL_DRAFT.md`.
- [ ] **Hospital IT test connection (HIS):** a non-production HL7 v2 endpoint (reports out, ADT/orders in), their TLS certificates, the AE titles and IP addresses of ECG machines for the allow-lists. *Prepared:* HL7 v2.5.1 ORU/ADT/ORM, FHIR R4, MLLP over TLS, allow-lists, outbox with retries. *Not tested against any real HIS* — expect mapping work (patient identifiers, doctor codes, LOINC/local codes, the Holter study code 18754-2 is a proposal).
- [ ] **Real ECG files from every device make the hospital uses** (GE MUSE, Philips, Schiller, BPL, Nihon Kohden, Mortara…) plus real **paper printouts and phone photos** of the same ECGs. *Why:* all file readers and the digitiser were tested on files this project generated or public files; real devices always surprise.
- [ ] **[PILOT] Run the site validation** per the protocol: label ECGs with two cardiologists + adjudicator, set site thresholds on the calibration half, score the held-out half **once**, have the cardiology lead sign the threshold file (`cardiotic-engine site-config`, then Settings → Site thresholds). Collect enough cases of the weak statements (anterior MI, long QT, flutter, high-grade AV block) or make no claim for them.
- [ ] **[PILOT] Silent-mode study** of the critical-result notifications and, if wanted, Live Assist.
- [ ] A **clinical evaluation report** from the results (consultant + clinical lead).

## 5. Data and licences

- [ ] **[BLOCKER for shipping those models] CinC 2017 (PhysioNet challenge) licence.** The signal-quality and rhythm models were trained with it. Confirm commercial use is allowed, or retrain without it. Record every dataset's licence and attribution in a register (`docs/regulatory/MODEL_CARDS.md` lists them; training-data provenance is a regulatory requirement).
- [ ] **Indian and US ECG data.** Needed for training improvements and for the evidence. Options: partner hospitals, a contract research organisation, licensed datasets. *Why:* the models know only German (PTB-XL) and Chinese (Chapman/Ningbo) 12-lead data and 1980s–90s Holter data; weaker statements (anterior MI 8.6%, long QT 18%, flutter) cannot be improved without more labelled cases.
- [ ] **Verified flutter / long-QT / AV-block data** (e.g. CODE-15%, MIMIC-IV-ECG; check each licence).
- [ ] The CSE database licence (Section 3).

## 6. Security and privacy (before real patient data)

- [ ] **[PILOT] Independent penetration test** of the running product; fix the findings; retest. *Prepared:* `docs/regulatory/THREAT_MODEL.md` as the brief; the product is hardened (see runbook), not tested by an outsider.
- [ ] **Privacy impact assessment** and the legal basis: India DPDP Act 2023; USA HIPAA (business-associate agreement if you ever touch PHI); GDPR only if you serve the EU.
- [ ] **Customer contract:** SLA, data-processing terms, who is responsible for what (the hospital's cardiologist is responsible for each signed report), patch SLA, vulnerability-disclosure address.
- [ ] Optional: ISO 27001 / SOC 2 if large hospital groups or OEMs ask.

## 7. Go-to-market (after Section 1)

- [ ] Pilot plan: one hospital, silent mode first, defined success measures, 3–6 months.
- [ ] If OEM: an integration kit and evaluation agreement for the `/v1` engine service (`engine/README.md`).
- [ ] Price and support model; training material for cardiologists and technicians (build from `docs/regulatory/INSTRUCTIONS_FOR_USE_DRAFT.md`).
- [ ] **Until clearance, say "research use only"** in all marketing. Do not claim accuracy, "AI diagnosis", or "FDA/CDSCO" anything.

---

## 8. Engineering work that is NOT done (and why) — ask for these when you are ready

| # | Item | Why it was not done | Needs |
|---|---|---|---|
| E1 | **Hindi (and other language) interface** | A machine translation of clinical text is not safe; needs a clinician-reviewed translation | a translator + clinical reviewer |
| E2 | **Accessibility audit (WCAG 2.1 AA)** | Basic labelling and keyboard use are tested; a full audit needs an expert with assistive technology | an accessibility consultant |
| E3 | **Browsers other than Chromium** | Browser tests ran in Chromium only | a test pass in Firefox/Safari/Edge on the hospital's real workstations |
| E4 | **Hosted CI run** | The workflow is written and its syntax checked, never executed on GitHub | move the repo, enable Actions, fix what the first run finds |
| E5 | **Models: improve weak statements and S/F beats** | needs more labelled data (Section 5); a retraining attempt without it was already rejected by its rule | data |
| E6 | **Long-Term AF Database / INCART** for AF and supraventricular beats | disk and time; licence check first (the data is reachable, `physionet.org`) | an hour of decision + disk space |
| E7 | **Real-photo digitiser tests** | needs real photos (Section 4) | files |
| E8 | **Second patient-identity check** (barcode / order match) | it is a clinical-safety design decision | clinical lead + usability test |
| E9 | **Push alert for failed HIS delivery; SMS/paging for critical results** | needs the hospital's gateway | hospital IT details |
| E10 | **Cryptographic signature on site-threshold files and on releases; build provenance** | needs a signing key and process owned by the company | key management decision |
| E11 | **Database encryption at rest / PostgreSQL and high availability** | the hospital's disk encryption covers the first case; scale is not yet needed (load test: fine to thousands of recordings) | a decision when a customer needs it |
| E12 | **Pediatric support** | different models and reference ranges | data + decision to extend the intended use |
| E13 | **Release management** | every component is version 0.1.0; no changelog or release notes process | agree numbering with the quality lead, then a one-hour job |
| E14 | **Formal SOUP assessment, design document, anomaly/change procedures** | quality-system documents owned by the regulatory lead | Section 3 |

## 9. What engineering delivered, so you know what you are standing on
Product and tests: see `docs/01_FEATURES_AND_LOGIC.md`. Architecture: `docs/04_ARCHITECTURE.md`. Operations: `docs/OPERATIONS_RUNBOOK.md`. Draft regulatory pack: `docs/regulatory/`.
Verified at the time of writing: server 116, engine 56, research 35, web unit 28 tests; 2 static and 10 server browser flows; the container acceptance test (10 checks, 19 screenshots) on the pinned image; dependency scans clean (pip-audit, npm audit); load test (0 errors).
