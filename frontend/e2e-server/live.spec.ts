import path from "node:path";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const FILES = path.join(path.dirname(fileURLToPath(import.meta.url)), ".files");
const SHOTS = process.env.SHOTS_DIR;

test("Live Assist: connect a bed, a gateway streams ECG, the board analyses it", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("User name").fill("kdesai");
  await page.getByLabel("Password").fill("correct horse battery");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();
  await page.goto("/settings/integrations");
  await page.getByLabel("Bed ID").fill("ICU-4");
  await page.getByLabel("Bed label").fill("Bed 4");
  await page.getByRole("button", { name: /Connect bed/ }).click();
  const token = (await page.getByLabel("Device token").textContent())!.trim();
  expect(token).toMatch(/^lv_/);

  // the gateway: 70 s of a real MIT-BIH recording, sent in 1 s packets as a monitor gateway does
  const strip: number[] = JSON.parse(readFileSync(path.join(FILES, "live-strip.json"), "utf8"));
  for (let i = 0; i + 360 <= strip.length; i += 360) {
    const r = await page.request.post("/api/live/ingest", { headers: { "X-Device-Token": token }, data: { fs: 360, samples: strip.slice(i, i + 360), vitals: { spo2: 97, abp_sys: 121, abp_dia: 74 } } });
    expect(r.status()).toBe(200);
  }
  await page.goto("/monitoring");
  await expect(page.getByText("ICU-4")).toBeVisible();
  await expect(page.getByText("Analysing")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/SpO₂ 97%/)).toBeVisible();
  await expect(page.getByText(/Silent mode/).first()).toBeVisible();
  if (SHOTS) {
    await page.addStyleTag({ content: "header, aside { position: static !important; }" });
    await page.screenshot({ path: path.join(SHOTS, "17-live-assist.png"), fullPage: true });
  }
});
