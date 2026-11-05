# Clinical validation protocol — draft template

**DRAFT for the clinical lead, a biostatistician and the ethics committee. Nothing here has been approved. It is written so that the protocol is fixed
BEFORE any partner-hospital result is looked at; the numbers in square brackets are placeholders for the statistician.** The same discipline the research used
(rules written first, test data scored once) is the standard to keep.

## 1. Questions
1. How well does the AI's statement set agree with two cardiologists' reading at *this* hospital, on its devices and population (per statement and for triage)?
2. Do the per-site thresholds, set on a calibration part, hold on a held-out part?
3. Are the measurements (HR, PR, QRS, QT/QTc, axis) acceptable against the cardiologists' manual measurements?
4. In silent mode, how many critical/urgent notifications would have appeared per day, and how many were true?
5. For Holter and long recordings: beat and AF-episode agreement, and the effect of the AF mode (balanced / screening).

## 2. Design
Retrospective, consecutive, de-identified study of the hospital's archived resting 12-lead ECGs (with the originals in the machine's own format), followed by a prospective **silent-mode** period (AI runs, readers see nothing from the AI, notifications are logged only) of [8] weeks. Single site first; second site (different device make) before any claim of generalisability. A separate sample of Holter recordings for question 5.

## 3. Population
Adults ≥ 18 with a resting 12-lead ECG. Exclusions fixed in advance: unreadable files, paediatric, [pacemaker-dependent rhythm if the intended use excludes it]. **Report the number excluded and why.** Aim for the range of devices actually in use; record device make/model per ECG.

## 4. Reference standard
Two independent board-certified cardiologists label each ECG using the product's statement list (SCP-ECG codes), blinded to the AI and to each other; a third adjudicates disagreements. Record inter-reader agreement (kappa per statement). For measurements: manual caliper measurement by one reader on a [random 300] subset, second reader on [100] for variability. For the intended-use statements that matter most (below) enrich the sample with confirmed cases.

## 5. Sample size (statistician to finalise)
Per statement the number of positive cases bounds the precision of sensitivity: for an expected sensitivity p and a half-width of the 95% interval *d*, positives needed ≈ 1.96² · p(1 − p) / d². Examples: p = 0.85, d = 0.07 → about 100 positives; p = 0.9, d = 0.05 → about 140. Statements that are rare (complete AV block, 2nd-degree AV block, long QT, flutter, anterior MI) will **not** reach these numbers in a consecutive sample: either enrich from the archive (search the hospital's reports for the diagnosis, then have the two readers confirm), or state clearly that no performance claim is made for them. The research test sets had 1–35 cases for these statements (`MODEL_CARDS.md`).

## 6. Primary and secondary endpoints
| | Endpoint | Success criterion ([OWNER] clinical lead, fixed before data) |
|---|---|---|
| Primary | Sensitivity and specificity with 95% CI for [AFIB, MI (any), complete BBB, high-grade AV block, long QT] against the adjudicated label, at the site thresholds | e.g. lower CI bound of sensitivity ≥ [x]% and of specificity ≥ [y]% |
| Primary | Triage: share of adjudicated *critical* ECGs that the triage places in *critical* or *urgent*; share of *normal* ECGs placed critical | [ ] |
| Secondary | AUC per statement; calibration (reliability plot) | [ ] |
| Secondary | Measurement agreement: mean difference and 95% limits (Bland–Altman) for HR, PR, QRS, QT, QTc, axis | within [ ] ms |
| Secondary | Subgroups: sex, age bands, device make; report every one, even if worse | none worse than [ ] without explanation |
| Secondary | Silent mode: notifications/day; share true; time from arrival to reading | [ ] |
| Secondary | Holter: beat-level agreement; AF burden difference; balanced vs screening | [ ] |

## 7. Analysis plan
Calibration part (random [50]% of patients, by patient not by ECG) sets the site thresholds with the shipped tool (`cardiotic-engine site-config`); the held-out part is scored **once** with the thresholds the clinical lead has signed. Report confusion matrices, not only summaries; bootstrap (by patient) 95% CIs; no post-hoc threshold changes after the held-out score; every deviation recorded. Missing/failed analyses are counted against the product (intention-to-analyse).

## 8. Ethics, data and conduct ([OWNER])
Ethics committee approval or documented waiver for retrospective use; data-sharing agreement; de-identification procedure and who holds the key; DPDP/HIPAA basis; data stays on the hospital's servers (the product runs there); access log from the product's audit; protocol registration (CTRI in India / ClinicalTrials.gov) if required for the prospective part; named principal investigator; statistician independent of the product team.

## 9. Outputs
A validation report with the pre-specified endpoints, deviations, the signed site-threshold file and its report, the audit-chain verification of the study period, and the list of every ECG excluded. Feeds the clinical evaluation report and the labelling (what is claimed, what is not).
