import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: false,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: { baseURL: "http://127.0.0.1:3000", trace: "retain-on-failure" },
  projects: [
    { name: "chromium-desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "chromium-mobile", use: { ...devices["Pixel 5"] } }
  ],
  webServer: [
    {
      command: "DATABASE_URL=postgresql+psycopg://movimento7:movimento7-local@127.0.0.1:54327/movimento7 PYTHONPATH=apps/api FLASK_APP=wsgi:app .venv/bin/flask run --port 5000",
      port: 5000,
      reuseExistingServer: true,
      timeout: 120000
    },
    {
      command: "INTERNAL_API_URL=http://127.0.0.1:5000 npm run dev -w @movimento7/web",
      port: 3000,
      reuseExistingServer: true,
      timeout: 120000
    }
  ]
});
