import { expect, test, type Page } from "@playwright/test";

const PASSWORD = "correct horse battery";

async function signIn(page: Page, user: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("User name").fill(user);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
}
async function signedIn(page: Page) {
  await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();
}
async function signOut(page: Page) {
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByText("Sign out").click();
  await expect(page).toHaveURL(/\/login/);
}

test("an issued password must be changed at first sign-in, then the app opens", async ({ page }) => {
  await signIn(page, "kdesai", PASSWORD);
  await signedIn(page);
  await page.goto("/settings/users");
  await page.getByLabel("User name").fill("newnurse");
  await page.getByLabel("Full name").fill("Nina Nurse");
  await page.getByLabel("Initial password").fill("Issued-by-admin-1");
  await page.getByRole("button", { name: "Add user" }).click();
  await expect(page.getByText("Nina Nurse")).toBeVisible();
  await signOut(page);

  await signIn(page, "newnurse", "Issued-by-admin-1");
  await expect(page.getByRole("heading", { name: "Choose a new password" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Upload ECG/ })).toHaveCount(0); // nothing else is open
  await page.getByLabel("Current password").fill("Issued-by-admin-1");
  await page.getByLabel("New password", { exact: true }).fill("Issued-by-admin-1");
  await page.getByLabel("New password again").fill("Issued-by-admin-1");
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByText(/not used before/)).toBeVisible(); // the same password is refused
  await page.getByLabel("New password", { exact: true }).fill("My-own-new-pass-7");
  await page.getByLabel("New password again").fill("My-own-new-pass-7");
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();
});

test("a critical ECG shows a banner to the reading team until acknowledged", async ({ page }) => {
  await signIn(page, "rsawant", PASSWORD);
  const banner = page.getByRole("alert").filter({ hasText: /Critical ECG/ });
  await expect(banner).toBeVisible({ timeout: 20000 });
  await expect(banner).toContainText("Complete heart block suggested");
  await expect(banner).toContainText("Ward 4");
  await signOut(page);
  await signIn(page, "kdesai", PASSWORD); // administrators do not read ECGs: no banner
  await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: /Critical ECG/ })).toHaveCount(0);
  await signOut(page);
  await signIn(page, "arao", PASSWORD);
  await expect(banner).toBeVisible({ timeout: 20000 });
  await banner.getByRole("button", { name: "Acknowledge" }).click();
  await expect(banner).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();
  await expect(banner).toHaveCount(0); // it stays acknowledged for everyone
});
