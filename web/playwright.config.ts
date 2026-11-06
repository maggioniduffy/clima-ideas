import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  webServer: [
    {
      command: "uv run --project ../backend uvicorn clima_nqn.api.app:app --port 8000",
      env: { CLIMA_NQN_DATA: "e2e/fixtures/processed" },
      url: "http://localhost:8000/health",
      reuseExistingServer: false,
    },
    {
      command: "pnpm dev",
      url: "http://localhost:5173",
      reuseExistingServer: true,
    },
  ],
  use: { baseURL: "http://localhost:5173" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
