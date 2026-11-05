# Instructions for use — draft

**DRAFT. Wording must be reviewed by the clinical lead and the regulatory lead; the intended-use statement they choose (`INTENDED_USE_DRAFT.md`) replaces the
bracketed text. Until then the product is for research use only.**

## 1. What Cardiotic AI is
Software that analyses ECG recordings and suggests measurements, findings and a reading order. **[A qualified cardiologist decides: every finding is accepted or
rejected by the cardiologist, and a report exists only after the cardiologist signs it.]**

## 2. Warnings (always visible in the product or its documentation)
- Results are **suggestions**. They may be wrong. Do not rely on them to exclude a serious condition.
- The reading order (critical, urgent, routine, normal) only helps you decide what to read first. A "normal" or "routine" label does not mean the ECG is safe.
- The system was developed on public ECG databases from other countries and older devices. Its performance on this hospital's patients and equipment must be checked before use.
- Detection of some conditions is weak: anterior infarction, long QT, atrial flutter, high-grade AV block. Read these ECGs yourself.
- Results are less reliable for paced rhythms, very wide QRS, severe artefact and patients under 18. The system is for adults.
- Findings from a **paper ECG** that was scanned or photographed are less reliable than from the original recording.
- AI detection of AF in long recordings over-calls in recordings with many ectopic beats. The "screening" setting finds more AF and creates more false alarms.
- Live Assist flags are advisory. It is not an alarm system and does not replace the bedside monitor.
- The notification banner does not replace the hospital's own procedure for critical results.

## 3. Roles
| Role | Can | Cannot |
|---|---|---|
| Technician | upload ECGs, match patients, send for reading, request repeat, acknowledge notifications | accept/reject findings, sign |
| Cardiologist | read, accept/reject, add findings, edit measurements, relabel Holter beats, sign, amend | change users or settings other than the clinical ones |
| Administrator | users, integrations, security settings, backups, data export/erase | change a review or sign |

## 4. Reading an ECG
1. Check the patient name and MRN at the top against the order. If an ECG is marked *unmatched*, assign the right patient first.
2. Review the tracing, the measurements and each suggested finding. Accept, reject, or add findings. Edit a measurement if it is wrong (it is printed as *edited*).
3. Write a comment if needed. Press **Sign & send report** and confirm with your password (or two-factor code).
4. A signed report is locked. To change it, use **Amend**: the signature is removed and the change is recorded; sign again.
5. The signed report goes to the hospital system. Check *Recent deliveries* under Settings → Integrations if a report does not arrive.

## 5. Critical-result notifications
A red banner appears on every screen for cardiologists and technicians when a critical ECG arrives. **Open and acknowledge** or **Acknowledge** it; the acknowledgement is recorded. Follow the hospital's critical-result procedure; the banner is a prompt, not the procedure.

## 6. Settings that change behaviour (administrator or cardiology lead)
Site thresholds (switch on only a file the cardiology lead approved), AF mode, password rules, time zone, retention period, notification levels and e-mail. Every change is in the audit log.

## 7. Data and privacy
Data stays on the hospital's server. Reading, signing, exports and setting changes are audited. An administrator can export or erase a patient's data; erasure is blocked until the retention period has passed.

## 8. Installation and support
See the installation guide and operations runbook. Contact: [OWNER vendor support details]. Report any incident or suspected malfunction to [vendor vigilance contact] and to the hospital's safety officer.

## 9. Labelling items to complete ([OWNER])
Manufacturer name and address, product name/version/UDI, date, regulatory marks and numbers, symbols, storage/system requirements, the exact intended-use statement, the contact for adverse events.
