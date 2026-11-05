import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

const FILES = path.join(path.dirname(fileURLToPath(import.meta.url)), ".files");
const PASSWORD = "correct horse battery";

async function signIn(page: Page, user: string) {
  await page.goto("/login");
  await page.getByLabel("User name").fill(user);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();
}
async function signOut(page: Page) {
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByText("Sign out").click();
  await expect(page).toHaveURL(/\/login/);
}

test("Holter: relabel a beat, sign with the password, get the PDF; history shows each step", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await signIn(page, "rsawant");
  await page.goto("/upload");
  await page.getByLabel("Patient MRN").fill("UH-PHB-1");
  await page.getByLabel("ECG file").setInputFiles(path.join(FILES, "holter-60s.csv"));
  await expect(page.getByText("Analysed — Holter recording")).toBeVisible({ timeout: 120_000 });
  await page.getByRole("link", { name: "Open for reading" }).click();
  await expect(page).toHaveURL(/\/holter\/H\d+/);
  const id = page.url().match(/holter\/(H\d+)/)![1];
  await signOut(page);

  await signIn(page, "arao");
  await page.goto(`/holter/${id}`);
  await expect(page.getByText("Ventricular ectopy")).toBeVisible();
  // relabel the first beat as ventricular
  const beats = (await (await page.request.get(`/api/holter/${id}`)).json()).analysis.result.beats;
  const relabel = await page.request.put(`/api/holter/${id}/beats`, { data: { time_s: beats[0].time_s, label: "V" }, headers: { "X-Requested-With": "cardiotic" } });
  expect(relabel.status()).toBe(200);
  await page.reload();
  await expect(page.getByText(/incl\. your changes/)).toBeVisible();
  await expect(page.getByRole("link", { name: /Draft report \(PDF\)/ })).toBeVisible();
  // the beat dialog opens from the strip and offers the four classes
  const canvas = page.locator("canvas").first();
  await canvas.scrollIntoViewIfNeeded();
  const box = (await canvas.boundingBox())!;
  for (let x = 20; x < box.width; x += 12) {
    await canvas.click({ position: { x, y: box.height / 2 }, trial: false, force: true });
    if (await page.getByRole("dialog").isVisible()) break;
  }
  await expect(page.getByRole("dialog")).toContainText(/Count this beat as/);
  await page.keyboard.press("Escape");

  // sign: wrong password refused, right one signs
  await page.getByRole("button", { name: "Sign Holter report" }).click();
  const dlg = page.getByRole("dialog", { name: "Confirm your signature" });
  await dlg.getByLabel("Password").fill("not my password");
  await dlg.getByRole("button", { name: "Sign report" }).click();
  await expect(dlg.getByText(/password is not right/)).toBeVisible();
  await dlg.getByLabel("Password").fill(PASSWORD);
  await dlg.getByRole("button", { name: "Sign report" }).click();
  await expect(page.getByText(/Signed by Dr\. Ananya Rao/).first()).toBeVisible();
  const pdf = await page.request.get(`/api/report/${id}.pdf`);
  expect(pdf.status()).toBe(200);
  expect((await pdf.body()).subarray(0, 4).toString()).toBe("%PDF");
  const hl7 = await (await page.request.get(`/api/report/${id}.hl7`)).text();
  expect(hl7).toContain("18754-2^Holter ECG study");
  await expect(page.getByRole("list", { name: "Review history" })).toContainText("Signed");
  expect(errors).toEqual([]);
});

test("site thresholds: upload an approved file, switch it on, see it in force", async ({ page }) => {
  await signIn(page, "kdesai");
  await page.goto("/settings/site");
  await expect(page.getByText("Site thresholds")).toBeVisible();
  await page.getByLabel("Upload site threshold file").setInputFiles(path.join(FILES, "site-config.json"));
  await expect(page.getByText("PULSE-1 · version 1")).toBeVisible();
  await page.getByRole("button", { name: "Switch on" }).click();
  await expect(page.getByText("On", { exact: true })).toBeVisible();
  await expect(page.getByText(/approved by Dr\. Ananya Rao, 2026-11-01 · 2 findings/)).toBeVisible();
  await page.getByRole("button", { name: "Use the model's own thresholds" }).click();
  await expect(page.getByText("Model defaults")).toBeVisible();
});

test("find a recording by MRN and open it", async ({ page }) => {
  await signIn(page, "arao");
  await page.goto("/reports");
  await page.getByLabel("Search recordings").fill("UH-PHB-1");
  await page.getByLabel("Search recordings").press("Enter");
  const hit = page.getByRole("button", { name: /UH-PHB-1/ }).first();
  await expect(hit).toBeVisible();
  await hit.click();
  await expect(page).toHaveURL(/\/holter\/H\d+/);
  await expect(page.getByText("AF burden")).toBeVisible();
});
