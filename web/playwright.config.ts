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
      // Any non-empty key turns the basemap on; tile requests are answered by e2e/fixtures/test.ts.
      env: { VITE_CARTO_KEY: "e2e-fixture-key" },
      url: "http://localhost:5173",
      reuseExistingServer: true,
    },
  ],
  use: { baseURL: "http://localhost:5173" },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Software WebGL (SwiftShader): keeps e2e off the GPU.
        launchOptions: { args: ["--use-angle=swiftshader", "--use-gl=angle", "--enable-unsafe-swiftshader"] },
      },
    },
  ],
});
