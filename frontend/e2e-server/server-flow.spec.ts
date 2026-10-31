import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

const FILES = path.join(path.dirname(fileURLToPath(import.meta.url)), ".files");
const PASSWORD = "correct horse battery";

async function signIn(page: Page, user: string, password = PASSWORD) {
  await page.goto("/login");
  await page.getByLabel("User name").fill(user);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  if (password === PASSWORD) await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible(); // wait for the sign-in to finish
}

test("real sign-in, upload, reading, signing, delivery queue and audit", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("response", (r) => { if (r.status() >= 400) console.log("HTTP", r.status(), r.request().method(), r.url()); });
  page.on("console", (m) => m.type() === "error" && !/401|409|400/.test(m.text()) && errors.push(m.text()));

  // sign-in is real: no sample users, no single sign-on button, wrong password refused
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByText("Pulse Care")).toBeVisible();
  await expect(page.getByText("Recent on this workstation")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /SSO/ })).toHaveCount(0);
  await signIn(page, "rsawant", "wrong password!!");
  await expect(page.getByRole("alert").or(page.getByText(/Wrong user name or password/))).toBeVisible();

  // technician uploads a DICOM ECG and a PDF
  await signIn(page, "rsawant");
  await expect(page.getByRole("heading", { name: /Rohit/ })).toBeVisible();
  await page.goto("/upload");
  await page.getByLabel("ECG file").setInputFiles(path.join(FILES, "scan.pdf"));
  await expect(page.getByText(/digitiser/)).toBeVisible();
  await page.getByLabel("ECG file").setInputFiles(path.join(FILES, "ecg.dcm"));
  await expect(page.getByText("Analysed — ready for reading")).toBeVisible({ timeout: 20_000 });
  await page.getByRole("link", { name: "Open for reading" }).click();
  await expect(page).toHaveURL(/\/ecg\/E\d+/);
  await expect(page.getByRole("heading", { name: "AI findings" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Sign & send report/ })).toHaveCount(0); // a technician cannot sign
  await page.getByRole("button", { name: /Send for reading/ }).click();
  await expect(page.getByText(/Sent to the cardiologist/)).toBeVisible();

  // the cardiologist reads and signs
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByText("Sign out").click();
  await expect(page).toHaveURL(/\/login/);
  await signIn(page, "arao");
  await expect(page.getByRole("heading", { name: /Dr\. Ananya/ })).toBeVisible();
  await page.getByRole("button", { name: /Start reading/ }).click();
  await expect(page).toHaveURL(/\/ecg\/E\d+/);
  const sign = page.getByRole("button", { name: /Sign & send report/ });
  await expect(sign).toBeDisabled();
  await page.getByRole("button", { name: "Accept remaining" }).click();
  await page.getByPlaceholder(/Interpretation note/).fill("Reviewed; no change in therapy.");
  await expect(sign).toBeEnabled();
  await sign.click();
  await expect(page.getByText(/Signed by Dr\. Ananya Rao/)).toBeVisible();
  await expect(page.getByText(/queued for the HIS/).first()).toBeVisible();

  // a reload shows the same state: it lives on the server, not in the browser
  await page.reload();
  await expect(page.getByText(/Signed by Dr\. Ananya Rao/)).toBeVisible();
  await page.getByRole("link", { name: /View report/ }).click();
  await expect(page.getByText("FINAL REPORT")).toBeVisible();
  await expect(page.getByText("Reviewed; no change in therapy.")).toBeVisible();
  await expect(page.getByText("Pulse Care").first()).toBeVisible();

  // the signed report left as HL7 and FHIR
  const hl7 = await page.request.get("/api/report/E000001.hl7");
  expect(hl7.status()).toBe(200);
  expect(await hl7.text()).toContain("ORU^R01");
  const fhir = await (await page.request.get("/api/report/E000001.fhir.json")).json();
  expect(fhir.resourceType).toBe("Bundle");

  // the administrator sees the audit trail and the queued HIS message; no monitoring board with invented data
  await page.goto("/");
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByText("Sign out").click();
  await signIn(page, "kdesai");
  await expect(page.getByRole("link", { name: "Monitoring" })).toHaveCount(0);
  await page.goto("/audit");
  await expect(page.getByText("Signed ECG report")).toBeVisible();
  await expect(page.getByText("Uploaded ECG")).toBeVisible();
  await page.goto("/settings/integrations");
  await expect(page.getByText("queued")).toBeVisible();
  await page.goto("/settings/users");
  await expect(page.getByText("rsawant")).toBeVisible();

  expect(errors).toEqual([]);
});
