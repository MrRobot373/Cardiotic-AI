/** Clinical presentation rules: statement names, triage priority, normal ranges. */
import type { EcgSummary, Measurements, Sex, Statement } from "./types";

export const SUPERCLASS_NAMES: Record<string, string> = {
  SUPER_NORM: "Normal ECG",
  SUPER_MI: "Myocardial infarction",
  SUPER_STTC: "ST/T change",
  SUPER_CD: "Conduction disturbance",
  SUPER_HYP: "Hypertrophy",
};

/** Plain names for the statements clinicians see most (the SCP-ECG description otherwise). */
const NAMES: Record<string, string> = {
  NORM: "Normal ECG", SR: "Sinus rhythm", SBRAD: "Sinus bradycardia", STACH: "Sinus tachycardia", SARRH: "Sinus arrhythmia",
  AFIB: "Atrial fibrillation", AFLT: "Atrial flutter", SVTAC: "Supraventricular tachycardia", PSVT: "Paroxysmal SVT",
  PVC: "Premature ventricular complexes", PAC: "Premature atrial complexes", BIGU: "Bigeminal pattern", TRIGU: "Trigeminal pattern",
  "1AVB": "First-degree AV block", "2AVB": "Second-degree AV block", "3AVB": "Third-degree (complete) AV block",
  CLBBB: "Complete left bundle branch block", CRBBB: "Complete right bundle branch block", IRBBB: "Incomplete right bundle branch block",
  ILBBB: "Incomplete left bundle branch block", LAFB: "Left anterior fascicular block", LPFB: "Left posterior fascicular block",
  IVCD: "Non-specific intraventricular conduction delay", WPW: "Wolff-Parkinson-White pattern", PACE: "Pacemaker rhythm",
  LVH: "Left ventricular hypertrophy", RVH: "Right ventricular hypertrophy", "LAO/LAE": "Left atrial enlargement", "RAO/RAE": "Right atrial enlargement",
  HVOLT: "High QRS voltage", LVOLT: "Low QRS voltage", LNGQT: "Long QT interval",
  IMI: "Inferior myocardial infarction", ASMI: "Anteroseptal myocardial infarction", AMI: "Anterior myocardial infarction",
  ALMI: "Anterolateral myocardial infarction", LMI: "Lateral myocardial infarction", ILMI: "Inferolateral myocardial infarction",
  IPLMI: "Inferoposterolateral myocardial infarction", IPMI: "Inferoposterior myocardial infarction", PMI: "Posterior myocardial infarction",
  ISC_: "Ischaemic ST-T changes", ISCAL: "Ischaemia, anterolateral leads", ISCIN: "Ischaemia, inferior leads", ISCIL: "Ischaemia, inferolateral leads",
  ISCAS: "Ischaemia, anteroseptal leads", ISCLA: "Ischaemia, lateral leads", ISCAN: "Ischaemia, anterior leads",
  NDT: "Non-diagnostic T-wave abnormality", NST_: "Non-specific ST change", STD_: "ST depression", STE_: "ST elevation",
  LOWT: "Low-amplitude T waves", INVT: "Inverted T waves", TAB_: "T-wave abnormality", QWAVE: "Q waves present",
  ABQRS: "Abnormal QRS", DIG: "Digitalis effect", EL: "Electrolyte disturbance", ANEUR: "Ventricular aneurysm",
  SEHYP: "Septal hypertrophy", PRC: "Premature complexes", LPR: "Prolonged PR interval", HVOLT_: "High voltage",
};

let DESCRIPTIONS: Record<string, string> = {};
/** SCP-ECG descriptions from the demo catalog, used for statements without a short name above. */
export function registerDescriptions(d: Record<string, string>) {
  DESCRIPTIONS = { ...DESCRIPTIONS, ...d };
}

export function statementName(code: string, descriptions: Record<string, string> = DESCRIPTIONS): string {
  if (SUPERCLASS_NAMES[code]) return SUPERCLASS_NAMES[code];
  if (NAMES[code]) return NAMES[code];
  const d = descriptions[code] ?? DESCRIPTIONS[code];
  return d ? d.charAt(0).toUpperCase() + d.slice(1) : code;
}

export const isGroup = (code: string) => code.startsWith("SUPER_");

/** Rhythm statements describe the rhythm; the rest describe morphology/conduction. */
export const RHYTHM_CODES = new Set(["SR", "SBRAD", "STACH", "SARRH", "AFIB", "AFLT", "SVTAC", "PSVT", "PACE", "BIGU", "TRIGU", "SVARR", "PVC", "PAC"]);

export type Priority = "critical" | "urgent" | "routine" | "normal";

export const PRIORITY_META: Record<Priority, { label: string; tone: "danger" | "warning" | "info" | "success"; rank: number }> = {
  critical: { label: "Critical", tone: "danger", rank: 0 },
  urgent: { label: "Urgent", tone: "warning", rank: 1 },
  routine: { label: "Routine", tone: "info", rank: 2 },
  normal: { label: "Normal", tone: "success", rank: 3 },
};

const MI = /MI$/;
const URGENT = new Set(["AFIB", "AFLT", "2AVB", "LNGQT", "SVTAC", "PSVT", "WPW", "CLBBB"]);

/** Worklist triage from the AI statements + measurements (a reading-order aid, never a diagnosis). */
export function triage(statements: { statement: string }[], m: Measurements): { priority: Priority; reason: string } {
  const codes = new Set(statements.map((s) => s.statement));
  const hr = m.heart_rate_bpm ?? 0;
  const qtc = m.qtc_bazett_ms ?? 0;
  if (codes.has("3AVB")) return { priority: "critical", reason: "Complete heart block suggested" };
  if ((codes.has("AFIB") || codes.has("AFLT")) && hr >= 120) return { priority: "critical", reason: `AF/flutter with rate ${Math.round(hr)} bpm` };
  // QTc is not interpretable with a wide QRS (bundle branch block, pacing): it never drives triage there
  const wide = (m.qrs_ms ?? 0) >= 120 || codes.has("PACE");
  if (qtc >= 500 && !wide) return { priority: "critical", reason: `QTc ${Math.round(qtc)} ms` };
  if (hr >= 150 || (hr > 0 && hr < 40)) return { priority: "critical", reason: `Rate ${Math.round(hr)} bpm` };
  const mi = [...codes].find((c) => MI.test(c) && !isGroup(c));
  if (mi) return { priority: "urgent", reason: statementName(mi) };
  const u = [...codes].find((c) => URGENT.has(c));
  if (u) return { priority: "urgent", reason: statementName(u) };
  const abnormal = [...codes].filter((c) => !isGroup(c) && !["NORM", "SR"].includes(c));
  if (abnormal.length || !codes.has("NORM")) return { priority: "routine", reason: abnormal.length ? statementName(abnormal[0]) : "Not classified normal" };
  return { priority: "normal", reason: "Normal ECG" };
}

export function ecgTriage(e: EcgSummary) {
  return triage(e.statements, e.measurements);
}

/** Reference ranges (adult) used to flag measurements. */
export function rangeFlag(key: keyof Measurements, v: number | null | undefined, sex?: Sex): "low" | "high" | null {
  if (v === null || v === undefined) return null;
  switch (key) {
    case "heart_rate_bpm": return v < 60 ? "low" : v > 100 ? "high" : null;
    case "pr_ms": return v < 120 ? "low" : v > 200 ? "high" : null;
    case "qrs_ms": return v >= 120 ? "high" : null;
    case "qtc_bazett_ms": return v >= (sex === "F" ? 460 : 450) ? "high" : null; // caller suppresses this when QRS is wide
    case "qrs_axis_deg": return v < -30 ? "low" : v > 90 ? "high" : null;
    default: return null;
  }
}

export function axisLabel(deg: number | undefined): string {
  if (deg === undefined) return "";
  if (deg < -90 || deg > 180) return "Extreme axis";
  if (deg < -30) return "Left axis deviation";
  if (deg > 90) return "Right axis deviation";
  return "Normal axis";
}

export const BEAT_NAMES: Record<string, string> = { N: "Normal", S: "Supraventricular ectopic", V: "Ventricular ectopic", F: "Fusion", Q: "Unclassifiable" };
export const RHYTHM_NAMES: Record<string, string> = { N: "Sinus rhythm", A: "Atrial fibrillation", O: "Other rhythm", "~": "Too noisy" };

export function primaryFindings(statements: Statement[]) {
  return statements.filter((s) => !isGroup(s.statement));
}

export function ageLabel(age: number | null, plus: boolean) {
  if (age === null) return "Age n/a";
  return plus ? "90+ y" : `${age} y`;
}

/** QTc can only be judged with a narrow QRS. */
export function qtcInterpretable(m: Measurements, statements: { statement: string }[] = []) {
  return (m.qrs_ms ?? 0) < 120 && !statements.some((s) => s.statement === "PACE");
}
