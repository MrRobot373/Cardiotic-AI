/** Accent-color math: hex → HSL triplets for the CSS variables. */
export function hexToHsl(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  let h = m[1];
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  const r = parseInt(h.slice(0, 2), 16) / 255;
  const g = parseInt(h.slice(2, 4), 16) / 255;
  const b = parseInt(h.slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  let s = 0;
  let hue = 0;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    hue = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    hue *= 60;
  }
  return [Math.round(hue), Math.round(s * 100), Math.round(l * 100)];
}

function hslLuminance(h: number, s: number, l: number): number {
  const sat = s / 100;
  const light = l / 100;
  const k = (n: number) => (n + h / 30) % 12;
  const a = sat * Math.min(light, 1 - light);
  const f = (n: number) => light - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(f(0)) + 0.7152 * lin(f(8)) + 0.0722 * lin(f(4));
}

export function accentVars(hex: string, dark: boolean): Record<string, string> {
  const hsl = hexToHsl(hex) ?? [221, 98, 57];
  const [h, s, l] = hsl;
  // Keep text on the accent readable, and lift very dark accents in dark mode.
  const lAdj = dark ? Math.max(l, 55) : Math.min(Math.max(l, 30), 60);
  // White text unless it would fall below the 3:1 WCAG contrast for UI components
  // (very light accents such as yellow then get dark text).
  const whiteContrast = 1.05 / (hslLuminance(h, s, lAdj) + 0.05);
  const fg = whiteContrast >= 3 ? "0 0% 100%" : "222 47% 11%";
  return {
    "--primary": `${h} ${s}% ${lAdj}%`,
    "--ring": `${h} ${s}% ${lAdj}%`,
    "--primary-foreground": fg,
    "--primary-soft": dark ? `${h} ${Math.min(s, 50)}% 17%` : `${h} ${Math.min(s, 90)}% 96%`,
    "--primary-soft-foreground": dark ? `${h} ${Math.min(s + 10, 95)}% 76%` : `${h} ${Math.min(s, 85)}% ${Math.min(lAdj, 42)}%`,
    // Deep "navy" emphasis derived from the accent hue (active pills, key actions)
    "--strong": dark ? `${h} ${Math.min(s, 85)}% 62%` : `${h} ${Math.min(s, 55)}% 25%`,
    "--strong-foreground": dark ? "224 40% 8%" : "0 0% 100%",
  };
}

export const ACCENT_PRESETS: { name: string; hex: string }[] = [
  { name: "Clinical blue", hex: "#246BFD" },
  { name: "Ocean", hex: "#0E7490" },
  { name: "Teal", hex: "#0D9488" },
  { name: "Emerald", hex: "#059669" },
  { name: "Indigo", hex: "#4F46E5" },
  { name: "Violet", hex: "#7C3AED" },
  { name: "Rose", hex: "#E11D48" },
  { name: "Amber", hex: "#D97706" },
  { name: "Graphite", hex: "#475569" },
];
