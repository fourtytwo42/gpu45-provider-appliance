import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  use: {
    baseURL: "http://127.0.0.1:3010",
  },
  webServer: {
    command: "npm run build && node .next/standalone/server.js",
    port: 3010,
    timeout: 180_000,
    reuseExistingServer: !process.env.CI,
    env: {
      GPU45_MODE: "mock",
      DATABASE_URL: "file:./prisma/dev.db",
      GPU45_E2E_AUTH_BYPASS: "true",
      PORT: "3010",
      HOSTNAME: "127.0.0.1",
    },
  },
});
