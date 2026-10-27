import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { accentVars } from "@/lib/color";

export interface Appearance {
  theme: "light" | "dark" | "system";
  accent: string;
  density: "comfortable" | "compact";
  contrast: "normal" | "high";
  ecgPaper: "pink" | "green" | "grey";
}

const DEFAULTS: Appearance = { theme: "light", accent: "#246BFD", density: "comfortable", contrast: "normal", ecgPaper: "pink" };
const STORAGE_KEY = "cardiotic.appearance";

interface Ctx {
  appearance: Appearance;
  resolvedTheme: "light" | "dark";
  update: (patch: Partial<Appearance>) => void;
  reset: () => void;
}

const AppearanceContext = createContext<Ctx | null>(null);

function readLocal(): Partial<Appearance> {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

function useSystemDark() {
  const [dark, setDark] = useState(() => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const fn = (e: MediaQueryListEvent) => setDark(e.matches);
    mq.addEventListener("change", fn);
    return () => mq.removeEventListener("change", fn);
  }, []);
  return dark;
}

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [local, setLocal] = useState<Partial<Appearance>>(readLocal);
  const systemDark = useSystemDark();
  const appearance = useMemo(() => {
    // ?theme=dark in the URL (used for screenshots and demos) wins over the saved choice
    const q = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("theme") : null;
    return { ...DEFAULTS, ...local, ...(q === "dark" || q === "light" ? { theme: q } : {}) } as Appearance;
  }, [local]);
  const resolvedTheme = appearance.theme === "system" ? (systemDark ? "dark" : "light") : appearance.theme;

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", resolvedTheme === "dark");
    root.dataset.density = appearance.density;
    root.dataset.contrast = appearance.contrast;
    for (const [k, v] of Object.entries(accentVars(appearance.accent, resolvedTheme === "dark"))) root.style.setProperty(k, v);
  }, [appearance, resolvedTheme]);

  const update = useCallback((patch: Partial<Appearance>) => {
    setLocal((cur) => {
      const next = { ...cur, ...patch };
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        /* storage unavailable */
      }
      return next;
    });
  }, []);
  const reset = useCallback(() => {
    setLocal({});
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }, []);
  return <AppearanceContext.Provider value={{ appearance, resolvedTheme, update, reset }}>{children}</AppearanceContext.Provider>;
}

export function useAppearance() {
  const ctx = useContext(AppearanceContext);
  if (!ctx) throw new Error("useAppearance outside provider");
  return ctx;
}
