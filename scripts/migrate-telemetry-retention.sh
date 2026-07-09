#!/usr/bin/env bash
set -euo pipefail

database="${1:-/var/lib/gpu45/appliance.db}"
marker="/var/lib/gpu45/.telemetry-retention-v2"
[[ -f "$marker" ]] && exit 0

sqlite3 "$database" <<'SQL'
CREATE TABLE IF NOT EXISTS MetricMinute (
  id TEXT PRIMARY KEY NOT NULL, kind TEXT NOT NULL, series TEXT NOT NULL,
  average REAL NOT NULL, minimum REAL NOT NULL, maximum REAL NOT NULL,
  samples INTEGER NOT NULL, unit TEXT NOT NULL, bucketAt DATETIME NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS MetricMinute_kind_series_bucketAt_key ON MetricMinute(kind, series, bucketAt);
CREATE INDEX IF NOT EXISTS MetricMinute_kind_bucketAt_idx ON MetricMinute(kind, bucketAt);
CREATE TABLE IF NOT EXISTS MetricHour (
  id TEXT PRIMARY KEY NOT NULL, kind TEXT NOT NULL, series TEXT NOT NULL,
  average REAL NOT NULL, minimum REAL NOT NULL, maximum REAL NOT NULL,
  samples INTEGER NOT NULL, unit TEXT NOT NULL, bucketAt DATETIME NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS MetricHour_kind_series_bucketAt_key ON MetricHour(kind, series, bucketAt);
CREATE INDEX IF NOT EXISTS MetricHour_kind_bucketAt_idx ON MetricHour(kind, bucketAt);
INSERT OR REPLACE INTO MetricMinute(id,kind,series,average,minimum,maximum,samples,unit,bucketAt)
SELECT lower(hex(randomblob(16))),kind,series,avg(value),min(value),max(value),count(*),unit,
       strftime('%Y-%m-%dT%H:%M:00.000Z',capturedAt)
FROM MetricSample WHERE datetime(capturedAt) >= datetime('now','-7 days')
GROUP BY kind,series,unit,strftime('%Y-%m-%dT%H:%M',capturedAt);
INSERT OR REPLACE INTO MetricHour(id,kind,series,average,minimum,maximum,samples,unit,bucketAt)
SELECT lower(hex(randomblob(16))),kind,series,avg(value),min(value),max(value),count(*),unit,
       strftime('%Y-%m-%dT%H:00:00.000Z',capturedAt)
FROM MetricSample WHERE datetime(capturedAt) >= datetime('now','-365 days')
GROUP BY kind,series,unit,strftime('%Y-%m-%dT%H',capturedAt);
DELETE FROM MetricSample WHERE datetime(capturedAt) < datetime('now','-6 hours');
DELETE FROM ProviderState WHERE datetime(capturedAt) < datetime('now','-6 hours');
PRAGMA wal_checkpoint(TRUNCATE);
VACUUM;
PRAGMA optimize;
SQL
touch "$marker"
