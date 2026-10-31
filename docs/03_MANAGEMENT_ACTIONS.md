# Cardiotic AI — What the Owner and Management Must Do

None of this can be done by software. Each item says why it matters and what blocks if it is not done.
This list is a planning aid, not legal or regulatory advice: confirm each point with a regulatory consultant
and a lawyer in each country.

---

## 1. Decide first (blocks everything else)

| Decision | Why it matters |
|---|---|
| **Intended use statement** (for example: "software that analyses 12-lead resting ECGs and proposes findings to a cardiologist, who reviews and signs") | It decides the device class, the regulatory route, the validation design and what you may say in marketing. The product currently carries "Research use only" |
| **Markets and order** (India first, USA next?) | Different regulators, forms and timelines |
| **Business model**: sell software, sell to equipment makers (OEM), or both | Decides contracts, support and liability |
| **Hosting**: on-premise only, or also hosted | On-premise keeps patient data in the hospital; hosted adds privacy and security duties |
| **Open questions in `docs/PRODUCT_PLAN.md` §14** | Listed there, still unanswered |

## 2. Regulatory

| Item | Notes |
|---|---|
| **India: CDSCO** | Software that analyses ECGs for diagnosis is regulated as a medical device under the Medical Devices Rules 2017; classification and licence route to be confirmed with a consultant |
| **USA: FDA** | Most likely a 510(k) with a predicate ECG analysis device, or De Novo; confirm with a pre-submission (Q-Sub) meeting |
| **Quality management system** | ISO 13485 (device quality system) is expected in both markets |
| **Software lifecycle** | IEC 62304 (software), ISO 14971 (risk management), IEC 62366 (usability), IEC 60601-2-25 / ANSI/AAMI EC57 (ECG analysis performance) |
| **Cybersecurity file** | FDA premarket cybersecurity guidance (SBOM, threat model, patch plan); IEC 81001-5-1 |
| **AI change control** | A plan for how models are updated after clearance (FDA predetermined change control plan) |
| **Labelling** | Instructions for use, limitations, the documented sex gap, intended population (adults) |
| **Post-market** | Complaint handling, vigilance/incident reporting, field safety actions |

Engineering supplies the technical documentation (architecture, risk inputs, test evidence, SBOM). A regulatory
owner must be named to write and file it.

## 3. Clinical validation and ethics

| Item | Notes |
|---|---|
| **Partner hospital(s)** | Needed for local validation, real device files, and the HIS test connection |
| **Ethics committee approval** | For retrospective study on hospital ECGs and for any prospective use |
| **Data-sharing agreement** | De-identification rules, who owns derived data, publication rights |
| **Validation protocol** | Written and approved **before** looking at the results; sample sizes, reference standard (two cardiologists + adjudicator), success criteria per statement |
| **Local operating points** | Run the site-configuration process on the hospital's labelled ECGs; the site's cardiology lead signs the thresholds |
| **Silent-mode study** | Run Live Assist silently before showing flags to clinicians |
| **Clinical lead** | A named cardiologist who owns clinical decisions and signs off the labelling |

## 4. Data and licences

- **CinC 2017 (AF challenge) data** was used for the quality and rhythm models: confirm the terms allow commercial use, or retrain without it.
- **PTB-XL, Chapman-Shaoxing-Ningbo, MIT-BIH**: record each licence and attribution requirement in a register (training-data provenance is also a regulatory requirement).
- **Real vendor files**: obtain sample files from each device make you want to support (GE, Philips, Schiller, BPL, Nihon Kohden, Mortara) with the maker's or hospital's permission.
- **Product licence**: choose the licence for the software you sell (proprietary EULA) and the open-source obligations (`ldap3` is LGPL-3).
- **HIS test interface**: a hospital IT contact and a non-production HL7 endpoint.

## 5. Security and privacy compliance

| Item | Notes |
|---|---|
| **Independent penetration test** | Required before real patient data; fix findings, retest |
| **Privacy law** | India DPDP Act 2023; USA HIPAA (if you handle protected health information as a business associate); GDPR if you ever serve the EU |
| **Security policies** | Access control, incident response, vulnerability disclosure, patch SLAs |
| **ISO 27001 / SOC 2** | Often requested by large hospital groups and equipment makers; not mandatory to start |
| **Insurance** | Professional indemnity and product liability for a medical-software vendor |
| **Customer agreements** | Contract, SLA, data-processing agreement, and clear division: the hospital's cardiologist is responsible for each signed report |

## 6. Company and people

| Role | Why |
|---|---|
| Regulatory / quality manager | Owns QMS and submissions |
| Clinical advisor (cardiologist) | Validation, labelling, user training content |
| Security and IT support | Install, upgrades, 24x7 contact for critical issues |
| Implementation engineer | On-site install, HIS integration, site-threshold set-up |
| Sales / partnerships | Hospitals and equipment makers |

Also: company registration and tax, **trademark search and filing for "Cardiotic AI"** in India and the USA,
domain names, and a company-owned code repository and cloud account (the repository currently sits under a
personal GitHub account).

## 7. Budget lines to plan (get quotes; no figures are given here)

Regulatory consultant and filing fees; QMS certification audit; clinical study costs; penetration test;
legal (contracts, privacy, IP); insurance; hospital pilot support; hardware for demos and pilot servers.

## 8. Go-to-market

- Pilot plan: one hospital, silent mode first, defined success measures, 3–6 months.
- Equipment-maker route: engine API (`/v1`) integration kit and an evaluation agreement.
- Price and support model; training material for cardiologists and technicians.
- What you may say before clearance: "research use only" language until the regulator allows more.

## 9. Suggested order

1. Intended use + market decision → 2. Name regulatory owner and clinical lead → 3. Partner hospital and ethics approval →
4. QMS start → 5. Licence checks → 6. Pen test → 7. Local validation → 8. Pilot (silent) → 9. Submission.
Items 1–5 can start now, in parallel with the remaining engineering in `02_REMAINING_DEVELOPMENT.md`.
