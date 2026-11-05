# Intended use — draft options (for decision)

**[OWNER] Management and the regulatory lead choose one statement, then everything else (device class, route, validation design, claims, labelling)
follows from it.** The product's engine currently carries: *"Research use only. Not a medical device. Not validated for clinical use."* That text stays until a
deliberate decision, supported by the regulator's view, replaces it.

## Option A — decision support for the reading cardiologist (narrowest; recommended starting point)
> Cardiotic AI is software that receives resting 12-lead electrocardiograms and long single-lead ECG recordings from ECG devices and hospital systems, and
> presents measurements, automated interpretive statements and a suggested reading order to a qualified cardiologist, who reviews, edits and signs the
> report. It does not diagnose, treat or monitor by itself, and its output is not to be used as the sole basis for a clinical decision.

## Option B — A plus long-recording (Holter) analysis support
Option A with: "…and long single-lead recordings, for which it presents beat classification, rhythm segments and episode summaries for review by a qualified cardiologist."

## Option C — embedded in equipment (OEM)
Engine only, supplied to a manufacturer who integrates it in a device with its own intended use. The manufacturer is the legal manufacturer of the combined device; the contract must say who holds which responsibility ([OWNER], lawyer).

## Not in any option, today
Live Assist (bedside advisory flags) — keep **off the claims** until a silent-mode study has been done; ECG photographs/scans as a diagnostic input — claims only after real-printout testing; flutter, long-QT, anterior-MI or high-grade AV block "detection" (insufficient evidence, see `MODEL_CARDS.md`); paediatric patients; use without a cardiologist's review; stand-alone use in primary care or by patients.

## Draft details to confirm
| Item | Draft |
|---|---|
| Intended users | Cardiologists / physicians qualified in ECG interpretation (read, edit, sign); ECG technicians (upload, match patient, send for reading); IT administrators (installation, users, integrations) |
| Intended patient population | Adults (18 years and over) having a resting 12-lead ECG or a single-lead ambulatory recording. [OWNER] clinical lead to confirm; models are not validated below 18 |
| Intended environment | Hospital or clinic network, on a server the hospital operates; used on a workstation browser. Not for use in transit (ambulance), at home, or on public networks |
| Inputs | DICOM, HL7 aECG, GE MUSE, Philips XLI, SCP-ECG, EDF, CSV waveforms; PDF/image printouts via the digitiser (printout statements flagged as such) |
| Outputs | Heart rate, PR, QRS, QT, QTc, axis; suggested statements with probability; triage level (critical/urgent/routine/normal) as a reading order; report PDF; HL7/FHIR to the HIS after signature |
| Clinical benefit claimed (draft) | Faster prioritisation of ECGs awaiting reading; consistent measurements; fewer transcription steps. **[OWNER] No accuracy or outcome claim until the site validation is done.** |
| Contraindications / warnings | Do not rely on the triage to exclude urgent disease; paced rhythms, very wide QRS, severe artefact, lead-reversal and non-adult patients may give wrong output; every statement needs confirmation; the product is not an alarm system |
| Reference predicates (FDA) | [OWNER] regulatory consultant to identify (ECG analysis software with a cleared 510(k)), then confirm substantial equivalence or choose De Novo |
| Software safety class proposal (IEC 62304) | Class B (a failure could contribute to a hazardous situation, but the cardiologist reviews every output and signs); to be confirmed by the risk file, see `RISK_MANAGEMENT_DRAFT.md` |
