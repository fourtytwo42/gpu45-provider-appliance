(async () => {
  await import("../lib/db");
  console.log("GPU45 database schema initialized.");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
