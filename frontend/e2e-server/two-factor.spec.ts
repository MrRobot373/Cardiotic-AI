import { createHmac } from "node:crypto";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const PASSWORD = "correct horse battery";
const SHOTS = process.env.SHOTS_DIR;

function totp(secret: string, step: number): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of secret.replace(/\s/g, "")) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const msg = Buffer.alloc(8);
  msg.writeBigUInt64BE(BigInt(step));
  const h = createHmac("sha1", key).update(msg).digest();
  const o = h[h.length - 1] & 0xf;
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}
const step = () => Math.floor(Date.now() / 30000);

async function snap(page: Page, name: string) {
  if (!SHOTS) return;
  await page.addStyleTag({ content: "header, aside { position: static !important; }" });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

test("two-factor sign-in: set up with an authenticator, then a code at every sign-in", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("User name").fill("kdesai");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();

  await page.goto("/settings/account");
  await page.getByRole("button", { name: "Set up" }).click();
  const key = page.getByLabel("Set-up key");
  await expect(key).toBeVisible();
  await expect(page.getByAltText(/QR code/)).toBeVisible();
  await snap(page, "13-two-factor-set-up");
  const secret = (await key.textContent())!;
  await page.getByLabel("Code from the app").fill(totp(secret, step()));
  await page.getByRole("button", { name: /Turn on two-factor/ }).click();
  await expect(page.getByText("On", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByText("Sign out").click();
  await page.getByLabel("User name").fill("kdesai");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByLabel("Two-factor code")).toBeVisible();
  await page.getByLabel("Two-factor code").fill("000000");
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByText(/Wrong user name or password|locked/)).toBeVisible();
  await snap(page, "14-two-factor-code-required");
  await page.getByLabel("Two-factor code").fill(totp(secret, step() + 1)); // the enrolment code cannot be reused
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();

  await page.goto("/settings/security");
  await expect(page.getByText("Require two-factor sign-in")).toBeVisible();
  await expect(page.getByText("Active Directory / LDAP")).toBeVisible();
  await expect(page.getByText("Single sign-on (OpenID Connect)")).toBeVisible();
  await snap(page, "15-security-settings");
});
