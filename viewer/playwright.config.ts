import { defineConfig, devices } from "@playwright/test";

/** The local server of the browser test (see e2e/start-lokaal.mjs). The viewer must run on 5173: CORS allows only that. */
export const LOKAAL = "http://127.0.0.1:8749";

export default defineConfig({
  testDir: "e2e",
  timeout: 240_000,
  expect: { timeout: 30_000 },
  workers: 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    // WebGL without a GPU (CI, headless).
    launchOptions: { args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"] },
  },
  webServer: [
    {
      command: "node e2e/start-lokaal.mjs",
      url: `${LOKAAL}/lokaal/project`,
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: "npm run dev",
      url: "http://127.0.0.1:5173",
      timeout: 120_000,
      reuseExistingServer: false,
      env: { VITE_OPENBIM_LOKAAL: LOKAAL },
    },
  ],
});
