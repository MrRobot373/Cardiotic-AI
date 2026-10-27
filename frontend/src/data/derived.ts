import { useMemo } from "react";
import { useDemo, type Review } from "@/app/demo-store";
import { useCatalog } from "./api";
import { ecgTriage, PRIORITY_META, type Priority } from "./clinical";
import type { EcgSummary, Patient } from "./types";

const COLLEAGUE = "Dr. Vivek Sharma";

/** Earlier ECGs of a patient were read before today: unless the demo user re-opened one, show it as
 *  signed by a colleague two hours after recording, with the AI findings accepted. */
function withHistory(r: Review, ecg: EcgSummary, historical: boolean): Review {
  if (!historical || r.status !== "new" || Object.keys(r.decisions).length || r.added.length) return r;
  const at = new Date(new Date(ecg.recorded_at).getTime() + 2 * 3600e3).toISOString();
  return { ...r, status: "signed", signedBy: COLLEAGUE, signedAt: at,
    decisions: Object.fromEntries(ecg.statements.filter((s) => !s.statement.startsWith("SUPER_")).map((s) => [s.statement, "accepted" as const])) };
}

export interface WorkItem {
  ecg: EcgSummary;
  patient: Patient;
  priority: Priority;
  reason: string;
  review: Review;
  previous?: EcgSummary;
}

/** ECGs joined with patients, AI triage and this browser's review state; newest first within priority. */
export function useWorkItems() {
  const { data: catalog, ...rest } = useCatalog();
  const { review } = useDemo();
  const items = useMemo<WorkItem[]>(() => {
    if (!catalog) return [];
    const pats = new Map(catalog.patients.map((p) => [p.id, p]));
    const byPatient = new Map<string, EcgSummary[]>();
    for (const e of catalog.ecgs) byPatient.set(e.patient_id, [...(byPatient.get(e.patient_id) ?? []), e]);
    for (const list of byPatient.values()) list.sort((a, b) => a.recorded_at.localeCompare(b.recorded_at));
    return catalog.ecgs.map((ecg) => {
      const t = ecgTriage(ecg);
      const list = byPatient.get(ecg.patient_id)!;
      const idx = list.indexOf(ecg);
      return { ecg, patient: pats.get(ecg.patient_id)!, priority: t.priority, reason: t.reason, review: withHistory(review(ecg.id), ecg, idx < list.length - 1), previous: idx > 0 ? list[idx - 1] : undefined };
    });
  }, [catalog, review]);
  return { items, catalog, ...rest };
}

export const byPriorityThenTime = (a: WorkItem, b: WorkItem) =>
  PRIORITY_META[a.priority].rank - PRIORITY_META[b.priority].rank || b.ecg.recorded_at.localeCompare(a.ecg.recorded_at);

/** "Unread" = the latest ECG of each patient that nobody has signed. Older ones are history. */
export function isOpen(i: WorkItem, all: WorkItem[]) {
  const latest = all.filter((x) => x.patient.id === i.patient.id).sort((a, b) => b.ecg.recorded_at.localeCompare(a.ecg.recorded_at))[0];
  return latest === i && i.review.status !== "signed";
}
