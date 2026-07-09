import "dotenv/config";
import fs from "node:fs";
import path from "node:path";
import { PrismaClient } from "@prisma/client";
import { PrismaBetterSqlite3 } from "@prisma/adapter-better-sqlite3";
import Database from "better-sqlite3";

const globalForPrisma = globalThis as unknown as { prisma?: PrismaClient };
const sqliteTimeoutMs = 30_000;

let schemaInitialized = false;

function resolveSqlitePath(url: string): string {
  if (!url.startsWith("file:")) return url;
  const raw = url.slice("file:".length);
  return path.isAbsolute(raw) ? raw : path.resolve(process.cwd(), raw);
}

function ensureSqliteSchema(): void {
  if (schemaInitialized) return;
  const dbUrl = process.env.DATABASE_URL ?? "file:./prisma/dev.db";
  const dbPath = resolveSqlitePath(dbUrl);
  fs.mkdirSync(path.dirname(dbPath), { recursive: true });
  const sqlite = new Database(dbPath, { timeout: sqliteTimeoutMs });
  sqlite.pragma(`busy_timeout = ${sqliteTimeoutMs}`);
  sqlite.pragma("journal_mode = WAL");
  sqlite.exec(`
    CREATE TABLE IF NOT EXISTS MetricSample (
      id TEXT PRIMARY KEY NOT NULL,
      kind TEXT NOT NULL,
      series TEXT NOT NULL,
      value REAL NOT NULL,
      unit TEXT NOT NULL,
      capturedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS MetricSample_kind_capturedAt_idx ON MetricSample(kind, capturedAt);

    CREATE TABLE IF NOT EXISTS ProviderState (
      id TEXT PRIMARY KEY NOT NULL,
      status TEXT NOT NULL,
      model TEXT NOT NULL,
      activeRequests INTEGER NOT NULL,
      promptTokens INTEGER NOT NULL,
      completionTokens INTEGER NOT NULL,
      tokensPerSecond REAL NOT NULL,
      providerUrl TEXT NOT NULL,
      lastError TEXT,
      capturedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS ProviderState_capturedAt_idx ON ProviderState(capturedAt);

    CREATE TABLE IF NOT EXISTS ModelAsset (
      id TEXT PRIMARY KEY NOT NULL,
      name TEXT NOT NULL,
      path TEXT NOT NULL UNIQUE,
      repo TEXT,
      revision TEXT,
      sizeBytes INTEGER NOT NULL,
      multimodal INTEGER NOT NULL DEFAULT 0,
      projectorPath TEXT,
      draftPath TEXT,
      active INTEGER NOT NULL DEFAULT 0,
      served INTEGER NOT NULL DEFAULT 0,
      servedAlias TEXT UNIQUE,
      defaultModel INTEGER NOT NULL DEFAULT 0,
      createdAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS ModelAsset_name_idx ON ModelAsset(name);

    CREATE TABLE IF NOT EXISTS ApiKey (
      id TEXT PRIMARY KEY NOT NULL,
      name TEXT,
      keyHash TEXT NOT NULL UNIQUE,
      keyPrefix TEXT NOT NULL,
      expiresAt DATETIME,
      suspendedAt DATETIME,
      lastUsedAt DATETIME,
      requestCount INTEGER NOT NULL DEFAULT 0,
      promptTokens INTEGER NOT NULL DEFAULT 0,
      completionTokens INTEGER NOT NULL DEFAULT 0,
      createdAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS ApiKeyUsage (
      id TEXT PRIMARY KEY NOT NULL,
      apiKeyId TEXT,
      model TEXT NOT NULL,
      requestedModel TEXT,
      promptTokens INTEGER NOT NULL DEFAULT 0,
      completionTokens INTEGER NOT NULL DEFAULT 0,
      statusCode INTEGER NOT NULL,
      createdAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      CONSTRAINT ApiKeyUsage_apiKeyId_fkey FOREIGN KEY (apiKeyId) REFERENCES ApiKey(id) ON DELETE SET NULL ON UPDATE CASCADE
    );
    CREATE INDEX IF NOT EXISTS ApiKeyUsage_apiKeyId_createdAt_idx ON ApiKeyUsage(apiKeyId, createdAt);
    CREATE INDEX IF NOT EXISTS ApiKeyUsage_model_createdAt_idx ON ApiKeyUsage(model, createdAt);
    CREATE TABLE IF NOT EXISTS EndpointSetting (
      id TEXT PRIMARY KEY NOT NULL DEFAULT 'default',
      allowAnonymous INTEGER NOT NULL DEFAULT 1,
      updatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    INSERT OR IGNORE INTO EndpointSetting (id, allowAnonymous) VALUES ('default', 1);

    CREATE TABLE IF NOT EXISTS AdminUser (
      id TEXT PRIMARY KEY NOT NULL,
      username TEXT NOT NULL UNIQUE,
      passwordHash TEXT NOT NULL,
      passwordSalt TEXT NOT NULL,
      failedAttempts INTEGER NOT NULL DEFAULT 0,
      lockedUntil DATETIME,
      createdAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS AdminSession (
      id TEXT PRIMARY KEY NOT NULL,
      userId TEXT NOT NULL,
      csrfToken TEXT NOT NULL,
      expiresAt DATETIME NOT NULL,
      revokedAt DATETIME,
      userAgent TEXT,
      ipAddress TEXT,
      createdAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      CONSTRAINT AdminSession_userId_fkey FOREIGN KEY (userId) REFERENCES AdminUser(id) ON DELETE CASCADE ON UPDATE CASCADE
    );
    CREATE INDEX IF NOT EXISTS AdminSession_userId_expiresAt_idx ON AdminSession(userId, expiresAt);
    CREATE INDEX IF NOT EXISTS AdminSession_expiresAt_idx ON AdminSession(expiresAt);

    CREATE TABLE IF NOT EXISTS LaunchProfile (
      id TEXT PRIMARY KEY NOT NULL,
      name TEXT NOT NULL UNIQUE,
      description TEXT,
      modelPath TEXT NOT NULL,
      mmprojPath TEXT,
      modelDraftPath TEXT,
      host TEXT NOT NULL DEFAULT '0.0.0.0',
      port INTEGER NOT NULL DEFAULT 30000,
      ctxSize INTEGER NOT NULL DEFAULT 262144,
      gpuLayers TEXT NOT NULL DEFAULT 'all',
      batchSize INTEGER NOT NULL DEFAULT 2048,
      uBatchSize INTEGER NOT NULL DEFAULT 512,
      cacheRamMiB INTEGER NOT NULL DEFAULT 8192,
      cacheTypeK TEXT NOT NULL DEFAULT 'q4_0',
      cacheTypeV TEXT NOT NULL DEFAULT 'q4_0',
      cacheReuse INTEGER NOT NULL DEFAULT 1024,
      specType TEXT NOT NULL DEFAULT 'draft-mtp',
      specDraftNMax INTEGER NOT NULL DEFAULT 2,
      flashAttention TEXT NOT NULL DEFAULT 'on',
      imageMinTokens INTEGER NOT NULL DEFAULT 1024,
      metrics INTEGER NOT NULL DEFAULT 1,
      jinja INTEGER NOT NULL DEFAULT 1,
      active INTEGER NOT NULL DEFAULT 0,
      createdAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS FanCurveProfile (
      id TEXT PRIMARY KEY NOT NULL,
      name TEXT NOT NULL UNIQUE,
      description TEXT,
      pointsJson TEXT NOT NULL,
      active INTEGER NOT NULL DEFAULT 0,
      createdAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS BenchmarkRun (
      id TEXT PRIMARY KEY NOT NULL,
      modelName TEXT NOT NULL,
      prompt TEXT NOT NULL,
      totalTokens INTEGER NOT NULL,
      promptTokens INTEGER NOT NULL,
      completionTokens INTEGER NOT NULL,
      promptTokensPerSecond REAL NOT NULL,
      generationTokensPerSecond REAL NOT NULL,
      durationMs INTEGER NOT NULL,
      peakGpuTempC REAL,
      peakVramBytes INTEGER,
      notes TEXT,
      optionsJson TEXT,
      createdAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS DownloadJob (
      id TEXT PRIMARY KEY NOT NULL,
      repoId TEXT NOT NULL,
      fileName TEXT NOT NULL,
      revision TEXT NOT NULL DEFAULT 'main',
      status TEXT NOT NULL DEFAULT 'queued',
      bytesDownloaded INTEGER NOT NULL DEFAULT 0,
      totalBytes INTEGER NOT NULL DEFAULT 0,
      targetPath TEXT NOT NULL,
      error TEXT,
      createdAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS DownloadJob_status_createdAt_idx ON DownloadJob(status, createdAt);



    CREATE TABLE IF NOT EXISTS WebSearchRun (
      id TEXT PRIMARY KEY NOT NULL,
      query TEXT NOT NULL,
      category TEXT NOT NULL DEFAULT 'general',
      resultCount INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'completed',
      error TEXT,
      createdAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS WebSearchRun_createdAt_idx ON WebSearchRun(createdAt);

    CREATE TABLE IF NOT EXISTS WebSearchResult (
      id TEXT PRIMARY KEY NOT NULL,
      runId TEXT NOT NULL,
      title TEXT NOT NULL,
      url TEXT NOT NULL,
      snippet TEXT NOT NULL DEFAULT '',
      engine TEXT NOT NULL DEFAULT 'searxng',
      rank INTEGER NOT NULL,
      officialSource INTEGER NOT NULL DEFAULT 1,
      createdAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      CONSTRAINT WebSearchResult_runId_fkey FOREIGN KEY (runId) REFERENCES WebSearchRun(id) ON DELETE CASCADE ON UPDATE CASCADE
    );
    CREATE INDEX IF NOT EXISTS WebSearchResult_runId_rank_idx ON WebSearchResult(runId, rank);
    CREATE INDEX IF NOT EXISTS WebSearchResult_url_idx ON WebSearchResult(url);

    CREATE TABLE IF NOT EXISTS WebPageCache (
      id TEXT PRIMARY KEY NOT NULL,
      url TEXT NOT NULL,
      finalUrl TEXT NOT NULL,
      statusCode INTEGER NOT NULL,
      contentType TEXT NOT NULL,
      fetchedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      title TEXT NOT NULL DEFAULT '',
      text TEXT NOT NULL DEFAULT '',
      linksJson TEXT NOT NULL DEFAULT '[]',
      robotsAllowed INTEGER NOT NULL DEFAULT 1,
      renderMode TEXT NOT NULL DEFAULT 'static'
    );
    CREATE INDEX IF NOT EXISTS WebPageCache_url_fetchedAt_idx ON WebPageCache(url, fetchedAt);

    CREATE TABLE IF NOT EXISTS JobLead (
      id TEXT PRIMARY KEY NOT NULL,
      sourceUrl TEXT NOT NULL,
      company TEXT NOT NULL DEFAULT '',
      title TEXT NOT NULL DEFAULT '',
      location TEXT NOT NULL DEFAULT '',
      remoteStatus TEXT NOT NULL DEFAULT 'unknown',
      applyUrl TEXT NOT NULL DEFAULT '',
      atsType TEXT,
      confidence REAL NOT NULL DEFAULT 0,
      extractedJson TEXT NOT NULL DEFAULT '{}',
      createdAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS JobLead_createdAt_idx ON JobLead(createdAt);
    CREATE INDEX IF NOT EXISTS JobLead_sourceUrl_idx ON JobLead(sourceUrl);

    CREATE TABLE IF NOT EXISTS AuditLog (
      id TEXT PRIMARY KEY NOT NULL,
      action TEXT NOT NULL,
      subject TEXT NOT NULL,
      details TEXT NOT NULL,
      createdAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS AuditLog_createdAt_idx ON AuditLog(createdAt);
  `);
  const launchProfileColumns = new Set(
    (sqlite.prepare("PRAGMA table_info(LaunchProfile)").all() as Array<{ name: string }>).map((column) => column.name),
  );
  const missingLaunchProfileColumns: Record<string, string> = {
    cacheTypeK: "TEXT NOT NULL DEFAULT 'q4_0'",
    cacheTypeV: "TEXT NOT NULL DEFAULT 'q4_0'",
    specType: "TEXT NOT NULL DEFAULT 'draft-mtp'",
    specDraftNMax: "INTEGER NOT NULL DEFAULT 2",
    flashAttention: "TEXT NOT NULL DEFAULT 'on'",
    imageMinTokens: "INTEGER NOT NULL DEFAULT 1024",
    modelDraftPath: "TEXT",
  };
  for (const [name, definition] of Object.entries(missingLaunchProfileColumns)) {
    if (!launchProfileColumns.has(name)) {
      try {
        sqlite.exec(`ALTER TABLE LaunchProfile ADD COLUMN ${name} ${definition}`);
      } catch (error) {
        if (!(error instanceof Error) || !error.message.includes("duplicate column name")) throw error;
      }
    }
  }
  const modelAssetColumns = new Set(
    (sqlite.prepare("PRAGMA table_info(ModelAsset)").all() as Array<{ name: string }>).map((column) => column.name),
  );
  const missingModelAssetColumns: Record<string, string> = {
    served: "INTEGER NOT NULL DEFAULT 0",
    servedAlias: "TEXT",
    defaultModel: "INTEGER NOT NULL DEFAULT 0",
    draftPath: "TEXT",
  };
  const servingMetadataWasMissing = !modelAssetColumns.has("served");
  for (const [name, definition] of Object.entries(missingModelAssetColumns)) {
    if (!modelAssetColumns.has(name)) {
      try {
        sqlite.exec(`ALTER TABLE ModelAsset ADD COLUMN ${name} ${definition}`);
      } catch (error) {
        if (!(error instanceof Error) || !error.message.includes("duplicate column name")) throw error;
      }
    }
  }
  sqlite.exec("CREATE UNIQUE INDEX IF NOT EXISTS ModelAsset_servedAlias_key ON ModelAsset(servedAlias)");
  if (servingMetadataWasMissing) {
    sqlite.exec(`
      UPDATE ModelAsset SET served = 1
      WHERE lower(name) NOT LIKE '%mmproj%'
        AND lower(name) NOT GLOB 'mtp[-_.]*'
        AND lower(name) NOT GLOB 'draft[-_.]*';
    `);
  }
  const benchmarkColumns = new Set(
    (sqlite.prepare("PRAGMA table_info(BenchmarkRun)").all() as Array<{ name: string }>).map((column) => column.name),
  );
  if (!benchmarkColumns.has("optionsJson")) {
    sqlite.exec("ALTER TABLE BenchmarkRun ADD COLUMN optionsJson TEXT");
  }
  sqlite.close();
  schemaInitialized = true;
}

ensureSqliteSchema();

const adapter = new PrismaBetterSqlite3({
  url: process.env.DATABASE_URL ?? "file:./prisma/dev.db",
});

export const prisma =
  globalForPrisma.prisma ??
  new PrismaClient({
    adapter,
    log: ["error", "warn"],
  });

if (process.env.NODE_ENV !== "production") {
  globalForPrisma.prisma = prisma;
}
