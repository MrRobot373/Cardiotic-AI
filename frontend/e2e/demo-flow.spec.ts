import { expect, test } from "@playwright/test";

test("cardiologist reads, edits calipers and signs an ECG end to end", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await page.getByRole("button", { name: /Dr\. Ananya Rao/ }).click();
  await expect(page.getByRole("heading", { name: /Dr\. Ananya/ })).toBeVisible();

  // open the most urgent ECG
  await page.getByRole("button", { name: /Start reading/ }).click();
  await expect(page).toHaveURL(/\/ecg\/E\d+/);
  await expect(page.getByText("AI findings")).toBeVisible();

  // signing is blocked until every AI finding is decided
  const sign = page.getByRole("button", { name: /Sign & send report/ });
  await expect(sign).toBeDisabled();

  // median beats: drag the QRS-end caliper and see the measurement marked as edited
  await page.getByRole("radio", { name: "Median beats" }).click();
  await page.getByRole("button", { name: /Edit calipers/ }).click();
  const panel = page.locator("canvas.cursor-ew-resize").first();
  const box = (await panel.boundingBox())!;
  await page.getByRole("button", { name: /Done/ }).click(); // toggle off and on again to prove the switch works
  await page.getByRole("button", { name: /Edit calipers/ }).click();
  // find the J line by scanning for a draggable point near the middle of the panel
  let edited = false;
  for (let f = 0.25; f < 0.75 && !edited; f += 0.01) {
    await page.mouse.move(box.x + box.width * f, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * f + 12, box.y + box.height / 2, { steps: 3 });
    await page.mouse.up();
    edited = await page.getByText("edited", { exact: true }).first().isVisible().catch(() => false);
  }
  expect(edited).toBe(true);

  await page.getByRole("button", { name: "Accept remaining" }).click();
  await page.getByPlaceholder(/Interpretation note/).fill("Demo sign-off note.");
  await expect(sign).toBeEnabled();
  await sign.click();
  await expect(page.getByText(/Signed by Dr\. Ananya Rao/)).toBeVisible();

  // report shows FINAL with the signature
  await page.getByRole("link", { name: /View report/ }).click();
  await expect(page.getByText("FINAL REPORT")).toBeVisible();
  await expect(page.getByText("Demo sign-off note.")).toBeVisible();
  await expect(page.getByText("Intervals adjusted by the reader.", { exact: false })).toBeVisible();

  // reports list and audit log
  await page.goto("/reports");
  await expect(page.getByText("ORU^R01 acknowledged").first()).toBeVisible();
  await page.goto("/audit");
  await expect(page.getByText("Signed ECG report")).toBeVisible();
  await expect(page.getByText("Accepted remaining AI findings")).toBeVisible();

  // technician cannot sign
  await page.goto("/");
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByText("Switch demo user").hover();
  await page.getByRole("menuitemradio", { name: /Rohit Sawant/ }).click();
  await page.getByRole("button", { name: /Start reading/ }).click();
  await expect(page.getByRole("button", { name: /Send for reading/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Sign & send report/ })).toHaveCount(0);

  expect(errors).toEqual([]);
});

test("Holter: events jump the strip; monitoring and upload work", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: /Dr\. Ananya Rao/ }).click();
  await page.goto("/holter/H001");
  await expect(page.getByText("AF burden")).toBeVisible();
  await page.getByRole("button", { name: /Ventricular couplet/ }).first().click();
  await expect(page.locator("text=/^2:4\\d – 3:1\\d$/")).toBeVisible();

  await page.goto("/monitoring");
  await expect(page.getByText("Assist offline")).toBeVisible();

  await page.goto("/upload");
  await page.getByRole("button", { name: "Use sample" }).click();
  await expect(page.getByRole("link", { name: "Open for reading" })).toBeVisible({ timeout: 5000 });
});
