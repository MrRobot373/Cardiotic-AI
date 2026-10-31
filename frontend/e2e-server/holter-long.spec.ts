import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const FILES = path.join(path.dirname(fileURLToPath(import.meta.url)), ".files");
const SHOTS = process.env.SHOTS_DIR;

test("a 2.5-hour Holter: analysed in sections, the viewer loads only the minutes on screen", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const signalRequests: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/signal")) signalRequests.push(r.url()); });
  await page.goto("/login");
  await page.getByLabel("User name").fill("rsawant");
  await page.getByLabel("Password").fill("correct horse battery");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();
  await page.goto("/upload");
  await page.getByLabel("Patient MRN").fill("UH-HOLTER-1");
  await page.getByLabel("ECG file").setInputFiles(path.join(FILES, "holter-2h30.edf"));
  await expect(page.getByText("Analysed — Holter recording")).toBeVisible({ timeout: 120_000 });
  await page.getByRole("link", { name: "Open for reading" }).click();
  await expect(page).toHaveURL(/\/holter\/H\d+/);
  await expect(page.getByText("AF burden")).toBeVisible();
  await expect(page.locator("canvas").first()).toBeVisible();
  const first = signalRequests.length;
  expect(signalRequests.every((u) => u.includes("from="))).toBe(true); // never the whole recording
  await page.getByRole("slider", { name: "Position in recording" }).press("End"); // jump to the end of the recording
  await expect.poll(() => signalRequests.length).toBeGreaterThan(first);
  expect(signalRequests.at(-1)).toMatch(/from=(8[4-9]|9\d)\d\d/); // a block near 2.5 h, not the whole file
  if (SHOTS) {
    await page.addStyleTag({ content: "header, aside { position: static !important; }" });
    await page.screenshot({ path: path.join(SHOTS, "16-holter-2h30-sections.png"), fullPage: true });
  }
  expect(errors).toEqual([]);
});
