import { defineConfig } from "@playwright/test";

// End-to-end against a real Cardiotic server (fresh database, built web app): `npm run test:e2e:server`
export default defineConfig({
  testDir: "e2e-server",
  timeout: 120_000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:8721",
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : undefined,
  },
  webServer: { command: "python3 e2e-server/run_server.py", url: "http://127.0.0.1:8721/api/health", reuseExistingServer: false, timeout: 60_000 },
});
