/**
 * Demo state (no backend): who is signed in, review decisions, sign-off and the audit trail.
 * Kept in this browser's localStorage; Settings → "Reset local review data" clears it.
 */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

export type Role = "cardiologist" | "technician" | "admin";

export interface DemoUser {
  name: string;
  role: Role;
  title: string;
  username: string;
}

export const DEMO_USERS: DemoUser[] = [
  { name: "Dr. Ananya Rao", role: "cardiologist", title: "Consultant cardiologist", username: "arao" },
  { name: "Rohit Sawant", role: "technician", title: "ECG technician", username: "rsawant" },
  { name: "Kiran Desai", role: "admin", title: "Hospital IT administrator", username: "kdesai" },
];

export type ReviewStatus = "new" | "in_review" | "signed" | "repeat";
export type Decision = "accepted" | "rejected";

export interface Review {
  status: ReviewStatus;
  decisions: Record<string, Decision>;
  added: string[];
  edits: Record<string, number | null>;
  note: string;
  signedBy?: string;
  signedAt?: string;
}

export interface AuditEvent {
  at: string;
  user: string;
  action: string;
  target: string;
}

export interface SiteSettings {
  operatingPoint: "sensitive" | "balanced" | "specific";
  thresholdOverrides: Record<string, number>;
  ratesFromMeasurements: boolean;
  autoSendHis: boolean;
  siteName: string;
  /** Show the dataset cardiologists' labels next to the AI (validation / sales presentations). */
  showReference: boolean;
}

interface State {
  user: DemoUser | null;
  reviews: Record<string, Review>;
  audit: AuditEvent[];
  site: SiteSettings;
}

const KEY = "cardiotic.demo.v1";
const EMPTY_REVIEW: Review = { status: "new", decisions: {}, added: [], edits: {}, note: "" };
const DEFAULT_SITE: SiteSettings = { operatingPoint: "balanced", thresholdOverrides: {}, ratesFromMeasurements: false, autoSendHis: true, siteName: "Department of Cardiology", showReference: false };
const INITIAL: State = { user: null, reviews: {}, audit: [], site: DEFAULT_SITE };

function load(): State {
  try {
    const s = JSON.parse(localStorage.getItem(KEY) || "null");
    return s ? { ...INITIAL, ...s, site: { ...DEFAULT_SITE, ...(s.site ?? {}) } } : INITIAL;
  } catch {
    return INITIAL;
  }
}

interface Ctx extends State {
  signIn: (u: DemoUser) => void;
  signOut: () => void;
  review: (id: string) => Review;
  updateReview: (id: string, patch: Partial<Review> | ((r: Review) => Partial<Review>), auditAction?: string) => void;
  log: (action: string, target: string) => void;
  updateSite: (patch: Partial<SiteSettings>) => void;
  reset: () => void;
}

const DemoContext = createContext<Ctx | null>(null);

export function DemoProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>(load);

  const commit = useCallback((fn: (s: State) => State) => {
    setState((cur) => {
      const next = fn(cur);
      try {
        localStorage.setItem(KEY, JSON.stringify(next));
      } catch {
        /* storage unavailable: the demo still works for this session */
      }
      return next;
    });
  }, []);

  const value = useMemo<Ctx>(() => {
    const event = (s: State, action: string, target: string): AuditEvent[] =>
      [{ at: new Date().toISOString(), user: s.user?.name ?? "system", action, target }, ...s.audit].slice(0, 300);
    return {
      ...state,
      signIn: (u) => commit((s) => ({ ...s, user: u, audit: event({ ...s, user: u }, "Signed in", u.title) })),
      signOut: () => commit((s) => ({ ...s, user: null, audit: event(s, "Signed out", "") })),
      review: (id) => state.reviews[id] ?? EMPTY_REVIEW,
      updateReview: (id, patch, auditAction) =>
        commit((s) => {
          const cur = s.reviews[id] ?? EMPTY_REVIEW;
          const p = typeof patch === "function" ? patch(cur) : patch;
          return { ...s, reviews: { ...s.reviews, [id]: { ...cur, ...p } }, audit: auditAction ? event(s, auditAction, id) : s.audit };
        }),
      log: (action, target) => commit((s) => ({ ...s, audit: event(s, action, target) })),
      updateSite: (patch) => commit((s) => ({ ...s, site: { ...s.site, ...patch }, audit: event(s, "Changed site settings", Object.keys(patch).join(", ")) })),
      reset: () => commit((s) => ({ ...INITIAL, user: s.user })),
    };
  }, [state, commit]);

  return <DemoContext.Provider value={value}>{children}</DemoContext.Provider>;
}

export function useDemo() {
  const ctx = useContext(DemoContext);
  if (!ctx) throw new Error("useDemo outside DemoProvider");
  return ctx;
}

export const canSign = (u: DemoUser | null) => u?.role === "cardiologist";
