import { type ClassValue, clsx } from "clsx";
import { format, formatDistanceToNowStrict, isToday, isYesterday, parseISO } from "date-fns";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** The hospital's time zone (IANA name, from Settings). Moments with a zone (signing time, audit log) are shown in it. */
let displayZone: string | null = null;
export function setDisplayZone(zone: string | null | undefined) {
  displayZone = zone || null;
}

const hasZone = (v: string) => /[zZ]|[+-]\d{2}:?\d{2}$/.test(v);

export function toDate(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  if (value instanceof Date) return value;
  // Date-only strings are calendar dates, not instants; a time without a zone is the wall-clock time the machine recorded
  // (it is shown as written, not shifted by the viewer's browser).
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return parseISO(value);
  return hasZone(value) ? new Date(value) : parseISO(value);
}

/** A Date whose local fields read as `d` does in `zone`, so date-fns can format it. */
function inZone(d: Date, zone: string): Date {
  try {
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: zone, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", second: "numeric" })
      .formatToParts(d).map((x) => [x.type, x.value]));
    return new Date(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second);
  } catch {
    return d;
  }
}

export function fmtDate(value: string | Date | null | undefined, pattern = "d MMM yyyy") {
  const d = toDate(value);
  if (!d) return "—";
  const instant = value instanceof Date || (typeof value === "string" && hasZone(value));
  return format(instant && displayZone ? inZone(d, displayZone) : d, pattern);
}

export function fmtDateTime(value: string | Date | null | undefined) {
  return fmtDate(value, "d MMM yyyy, HH:mm");
}

export function fmtRelative(value: string | Date | null | undefined) {
  const d = toDate(value);
  if (!d) return "—";
  const diff = Date.now() - d.getTime();
  if (diff < 45_000 && diff > -45_000) return "just now";
  if (isToday(d)) return formatDistanceToNowStrict(d, { addSuffix: true });
  if (isYesterday(d)) return `yesterday, ${format(d, "HH:mm")}`;
  if (Math.abs(diff) < 1000 * 60 * 60 * 24 * 6) return format(d, "EEE, HH:mm");
  return format(d, "d MMM yyyy");
}

const HONORIFIC = /^(dr|mr|mrs|ms|miss|prof|shri|smt)\.?$/i;

/** "Dr. Ananya Rao" → "AR", "Harish Chandra Gupta" → "HG": first and last name, titles skipped. */
export function initials(name: string) {
  const parts = name.split(/\s+/).filter((p) => p && !HONORIFIC.test(p));
  const picked = parts.length > 1 ? [parts[0], parts[parts.length - 1]] : parts;
  return picked.map((p) => p[0]?.toUpperCase()).join("");
}

export function fmtBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

const ACRONYMS: Record<string, string> = { Ecg: "ECG", Ct: "CT", Mri: "MRI", Icd: "ICD", Soap: "SOAP", Qa: "Q&A", Ent: "ENT" };

export function titleCase(s: string) {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()).replace(/\b[A-Z][a-z]+\b/g, (w) => ACRONYMS[w] ?? w);
}

export function fmtNum(v: number | null | undefined) {
  if (v === null || v === undefined) return "—";
  return Number.isInteger(v) ? String(v) : String(Number(v.toFixed(3)));
}

export function sexLabel(sex: string) {
  return { male: "Male", female: "Female", other: "Other", unknown: "Unknown" }[sex] ?? sex;
}

export function greeting(d = new Date()) {
  const h = d.getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}
