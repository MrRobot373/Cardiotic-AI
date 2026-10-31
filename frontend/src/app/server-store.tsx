/** The same context as demo-store.tsx, backed by the Cardiotic server: real accounts, reviews and audit log live there. */
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { api, ApiError, siteName } from "@/lib/server";
import { DEFAULTS, DemoContext, EMPTY, type AuditEvent, type Ctx, type DemoUser, type Review, type SiteSettings } from "./demo-store";

interface ServerReview extends Review {
  version: number;
}

const canSeeAudit = (u: DemoUser | null) => u?.role === "admin" || u?.role === "cardiologist";

export function ServerProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [user, setUser] = useState<DemoUser | null>(null);
  const [ready, setReady] = useState(false);
  const [reviews, setReviews] = useState<Record<string, Review>>({});
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [site, setSite] = useState<SiteSettings>({ ...DEFAULTS.site, siteName: siteName ?? DEFAULTS.site.siteName });
  const reviewsRef = useRef(reviews);
  reviewsRef.current = reviews;
  /** One request at a time: a quick "accept", note and "sign" must reach the server in order, each with the latest version. */
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const put = (next: Record<string, Review>) => { reviewsRef.current = next; setReviews(next); };

  const loadReviews = useCallback(async () => setReviews(await api<Record<string, ServerReview>>("/reviews")), []);
  const loadAudit = useCallback(async (u: DemoUser | null) => {
    if (!canSeeAudit(u)) return setAudit([]);
    setAudit((await api<{ at: string; user: string; action: string; target: string }[]>("/audit?limit=300")).map((e) => ({ at: e.at, user: e.user, action: e.action, target: e.target })));
  }, []);

  const enter = useCallback(async (me: { user: DemoUser; site: SiteSettings }) => {
    setUser(me.user);
    setSite({ ...DEFAULTS.site, ...me.site });
    if (me.user.enrol_2fa) return; // nothing else is open until two-factor sign-in is set up
    await Promise.all([loadReviews(), loadAudit(me.user)]);
  }, [loadReviews, loadAudit]);

  useEffect(() => {
    api<{ user: DemoUser; site: SiteSettings }>("/me").then(enter).catch(() => setUser(null)).finally(() => setReady(true));
    const out = () => { setUser(null); qc.clear(); };
    window.addEventListener("cardiotic:signed-out", out);
    return () => window.removeEventListener("cardiotic:signed-out", out);
  }, [enter, qc]);

  // other readers' work shows up without a reload
  useEffect(() => {
    if (!user) return;
    const t = setInterval(() => { loadReviews().catch(() => undefined); loadAudit(user).catch(() => undefined); qc.invalidateQueries({ queryKey: ["catalog"] }); }, 20000);
    return () => clearInterval(t);
  }, [user, loadReviews, loadAudit, qc]);

  const value = useMemo<Ctx>(() => ({
    serverMode: true,
    ready,
    user,
    reviews,
    audit,
    site,
    login: async (username, password) => {
      const res = await api<{ user?: DemoUser; totp_required?: boolean; challenge?: string }>("/login", { method: "POST", json: { username, password } });
      if (res.totp_required) return { challenge: res.challenge };
      qc.clear();
      await enter(await api<{ user: DemoUser; site: SiteSettings }>("/me"));
      return {};
    },
    loginTotp: async (challenge, code) => {
      await api("/login/totp", { method: "POST", json: { challenge, code } });
      qc.clear();
      await enter(await api<{ user: DemoUser; site: SiteSettings }>("/me"));
    },
    refreshMe: async () => {
      await enter(await api<{ user: DemoUser; site: SiteSettings }>("/me"));
    },
    signIn: () => undefined,
    signOut: () => {
      api("/logout", { method: "POST", json: {}, keepalive: true }).catch(() => undefined); // keepalive: still sent if the page is reloaded at once
      setUser(null);
      setReviews({});
      qc.clear();
    },
    review: (id) => reviews[id] ?? EMPTY,
    updateReview: (id, patch, auditAction) => {
      const before = reviewsRef.current[id] ?? EMPTY;
      const p = typeof patch === "function" ? patch(before) : patch;
      const { signedBy: _sb, signedAt: _sa, version: _v, ...fields } = p as Record<string, unknown>;
      const signing = p.status === "signed";
      if (!signing) put({ ...reviewsRef.current, [id]: { ...before, ...p } }); // show it at once; the server's answer replaces it
      const task = async () => {
        const cur = reviewsRef.current[id] ?? EMPTY;
        try {
          const next = signing
            ? await api<ServerReview>(`/reviews/${id}/sign`, { method: "POST", json: { note: p.note ?? cur.note, version: cur.version } })
            : await api<ServerReview>(`/reviews/${id}`, { method: "PUT", json: { ...fields, version: cur.version, ...(auditAction ? { audit: auditAction } : {}) } });
          put({ ...reviewsRef.current, [id]: next });
          loadAudit(user).catch(() => undefined);
          return true;
        } catch (e) {
          toast.error(e instanceof ApiError ? e.message : "Could not reach the server");
          loadReviews().catch(() => undefined); // drop the optimistic change
          return false;
        }
      };
      const run = queue.current.then(task, task);
      queue.current = run;
      return run;
    },
    log: () => undefined, // the server records its own audit entries
    updateSite: (patch) => {
      api<SiteSettings>("/settings", { method: "PUT", json: patch }).then((s) => { setSite({ ...DEFAULTS.site, ...s }); loadAudit(user).catch(() => undefined); }).catch((e) => toast.error(e instanceof ApiError ? e.message : "Could not reach the server"));
    },
    reset: () => undefined,
  }), [ready, user, reviews, audit, site, qc, enter, loadReviews, loadAudit]);

  return <DemoContext.Provider value={value}>{children}</DemoContext.Provider>;
}
