import { chromium } from "playwright";
const b = await chromium.launch().catch(() => chromium.launch({ executablePath: "/opt/pw-browsers/chromium" }));
const ctx = await b.newContext({ viewport: { width: 390, height: 844 } });
await ctx.addInitScript(() => localStorage.setItem("cardiotic.demo.v1", JSON.stringify({ user: { name: "Dr. Ananya Rao", role: "cardiologist", title: "x" }, reviews: {}, audit: [] })));
const p = await ctx.newPage();
await p.goto(process.argv[2], { waitUntil: "networkidle" });
const r = await p.evaluate(() => [...document.querySelectorAll("body *")].filter((e) => e.getBoundingClientRect().right > window.innerWidth + 1).filter((e) => { let a = e.parentElement; while (a) { const o = getComputedStyle(a).overflowX; if (o === "auto" || o === "hidden" || o === "scroll") return false; a = a.parentElement; } return true; }).slice(0, 8).map((e) => `${e.tagName}.${String(e.className).slice(0, 80)} right=${Math.round(e.getBoundingClientRect().right)}`));
console.log(r.join("\n")); await b.close();
