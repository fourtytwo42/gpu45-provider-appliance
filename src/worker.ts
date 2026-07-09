import { collectLiveTelemetry, persistLiveTelemetry, pruneTelemetry } from "./lib/collectors";
import { isLiveRuntime } from "./lib/config";
import { processNextDownload, recoverInterruptedDownloads } from "./lib/downloads";

const intervalMs = 5_000;
let tickCount = 0;

async function tick(): Promise<void> {
  const telemetry = await collectLiveTelemetry();
  tickCount += 1;
  if (tickCount % 3 === 0) {
    await persistLiveTelemetry(telemetry);
    console.log(`[collector] saved telemetry at ${telemetry.collectedAt}`);
  }
  if (tickCount % 720 === 0) await pruneTelemetry();
}

let downloadRunning = false;

async function downloadTick(): Promise<void> {
  if (downloadRunning) return;
  downloadRunning = true;
  try {
    await processNextDownload();
  } finally {
    downloadRunning = false;
  }
}

async function main(): Promise<void> {
  if (!isLiveRuntime()) {
    console.log("[collector] mock runtime; exiting");
    return;
  }

  const recovered = await recoverInterruptedDownloads();
  if (recovered > 0) console.log(`[download] requeued ${recovered} interrupted job(s)`);
  await Promise.all([tick(), downloadTick(), pruneTelemetry()]);
  setInterval(() => {
    void tick().catch((error) => {
      console.error("[collector] tick failed", error);
    });
  }, intervalMs);
  setInterval(() => {
    void downloadTick().catch((error) => {
      console.error("[download] tick failed", error);
    });
  }, intervalMs);
}

void main().catch((error) => {
  console.error("[collector] fatal error", error);
  process.exitCode = 1;
});
