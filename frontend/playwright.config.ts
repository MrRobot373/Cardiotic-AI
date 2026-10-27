import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  use: {
    baseURL: process.env.E2E_BASE ?? "http://localhost:5174",
    viewport: { width: 1440, height: 900 },
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : undefined,
  },
  webServer: process.env.E2E_BASE ? undefined : { command: "npx vite --port 5174 --strictPort", url: "http://localhost:5174", reuseExistingServer: true },
});
