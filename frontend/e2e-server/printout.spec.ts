import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const FILES = path.join(path.dirname(fileURLToPath(import.meta.url)), ".files");
const SHOTS = process.env.SHOTS_DIR;

test("a paper ECG (PDF) is digitised, analysed and marked as a printout", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("User name").fill("rsawant");
  await page.getByLabel("Password").fill("correct horse battery");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();
  await page.goto("/upload");
  await page.getByLabel("Patient MRN").fill("UH-PAPER-1");
  await page.getByLabel("ECG file").setInputFiles(path.join(FILES, "printout.pdf"));
  await expect(page.getByText("Analysed — ready for reading")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("link", { name: "Open for reading" }).click();
  await expect(page.getByText(/Digitised printout 3 × 4/)).toBeVisible();
  await expect(page.getByText(/QRS, QT and QTc are not measured/).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "AI findings" })).toBeVisible();
  if (SHOTS) {
    await page.addStyleTag({ content: "header, aside { position: static !important; }" });
    await page.screenshot({ path: path.join(SHOTS, "18-paper-ecg-digitised.png"), fullPage: true });
  }
});
