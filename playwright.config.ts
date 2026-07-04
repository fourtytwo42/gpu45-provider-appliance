import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  use: {
    baseURL: "http://127.0.0.1:3010",
  },
  webServer: {
    command: "npm run dev -- --port 3010",
    port: 3010,
    reuseExistingServer: !process.env.CI,
    env: {
      GPU45_MODE: "mock",
      DATABASE_URL: "file:./prisma/dev.db",
    },
  },
});
