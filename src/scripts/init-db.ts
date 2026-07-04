import { execSync } from "node:child_process";

(async () => {
  execSync("npx prisma generate --config prisma.config.ts", { stdio: "inherit" });
  await import("../lib/db");
  console.log("GPU45 database schema initialized.");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
