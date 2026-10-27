// Screenshot every screen (light, optionally dark and mobile) and report console errors.
// node scripts/shots.mjs [baseUrl] [outDir] [route ...]
import { chromium } from "playwright";
const base = process.argv[2] ?? "http://localhost:5174";
const out = process.argv[3] ?? "shots";
const only = process.argv.slice(4);
const ROUTES = [
  ["login", "/login", false], ["worklist", "/", true], ["review", "/ecg/E0025", true], ["review-lbbb", "/ecg/E0026", true],
  ["report", "/ecg/E0025/report", true], ["patients", "/patients", true], ["patient", "/patients/P004", true],
  ["holter-list", "/holter", true], ["holter", "/holter/H001", true], ["monitoring", "/monitoring", true],
  ["reports", "/reports", true], ["upload", "/upload", true], ["ai", "/ai", true], ["audit", "/audit", true],
  ["settings", "/settings/site", true],
];
const user = { name: "Dr. Ananya Rao", role: "cardiologist", title: "Consultant cardiologist" };
const browser = await chromium.launch().catch(() => chromium.launch({ executablePath: "/opt/pw-browsers/chromium" }));
const errors = [];
for (const [mode, vp] of [["light", { width: 1536, height: 960 }], ["dark", { width: 1536, height: 960 }], ["mobile", { width: 390, height: 844 }]]) {
  if (only.length && !only.includes(mode) && !ROUTES.some(([n]) => only.includes(n))) continue;
  const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 1 });
  await ctx.addInitScript((u) => {
    try { if (!location.pathname.endsWith("/login")) localStorage.setItem("cardiotic.demo.v1", JSON.stringify({ user: u, reviews: {}, audit: [] })); } catch {}
  }, user);
  const pageObj = await ctx.newPage();
  pageObj.on("console", (m) => { if (m.type() === "error") errors.push(`${mode} ${pageObj.url()}: ${m.text()}`); });
  pageObj.on("pageerror", (e) => errors.push(`${mode} ${pageObj.url()}: ${e.message}`));
  for (const [name, path] of ROUTES) {
    if (only.length && !only.includes(name) && !only.includes(mode)) continue;
    if (mode !== "light" && !["worklist", "review", "holter", "monitoring", "patient"].includes(name)) continue;
    const url = base + path + (mode === "dark" ? (path.includes("?") ? "&" : "?") + "theme=dark" : "");
    await pageObj.goto(url, { waitUntil: "networkidle" });
    await pageObj.waitForTimeout(700);
    await pageObj.screenshot({ path: `${out}/${name}-${mode}.png`, fullPage: mode !== "mobile" || true });
    const overflow = await pageObj.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (overflow > 1) errors.push(`${mode} ${name}: horizontal overflow ${overflow}px`);
  }
  await ctx.close();
}
await browser.close();
console.log(errors.length ? errors.join("\n") : "no console errors, no horizontal overflow");
