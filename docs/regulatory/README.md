# Regulatory draft pack

**Status: DRAFTS for the regulatory consultant and the clinical lead. These are not filings, not a quality-system record and not
legal advice.** Engineering prepared them from the code, the tests and the measured results at commit `c0b414c` so that the
people who own the regulatory work start from facts, not from a blank page. Items marked **[OWNER]** need a decision or a
rating by a named person (clinical lead, regulatory lead, management); nothing in these files has been approved by anyone.

| File | What it is | Standard it feeds (to be confirmed by the consultant) |
|---|---|---|
| `INTENDED_USE_DRAFT.md` | Options for the intended-use and indications statement, users, environment, limits | all submissions; ISO 13485 design inputs |
| `SOFTWARE_REQUIREMENTS.md` | Software requirements with a traceability matrix to code and tests; safety classification proposal | IEC 62304 |
| `RISK_MANAGEMENT_DRAFT.md` | Hazard analysis with controls already built, gaps and proposed ratings | ISO 14971 |
| `THREAT_MODEL.md` | Security threat model (STRIDE) with controls and open gaps | FDA cybersecurity guidance; IEC 81001-5-1 |
| `MODEL_CARDS.md` | Each AI model: purpose, data, measured performance, subgroups, limits | FDA AI-enabled device guidance; CDSCO technical file |
| `CLINICAL_VALIDATION_PROTOCOL_DRAFT.md` | Protocol template for the site validation and the silent-mode study | clinical evaluation; ethics submission |
| `INSTRUCTIONS_FOR_USE_DRAFT.md` | Draft user instructions and labelling statements | labelling requirements |

Also relevant, elsewhere in the repository: `deploy/sbom/` (software bill of materials), `THIRD_PARTY_NOTICES.md`,
`docs/OPERATIONS_RUNBOOK.md`, `docs/04_ARCHITECTURE.md`, `ml/reports/RESULTS.md` (all measured results, including the models that
were rejected and why), `.github/workflows/ci.yml` (automated verification).

What engineering cannot supply, and why, is in `docs/03_MANAGEMENT_ACTIONS.md` and `docs/05_OWNER_TODO.md`.
