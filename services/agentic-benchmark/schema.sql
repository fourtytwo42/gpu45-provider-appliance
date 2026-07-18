PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_qualifications (
  profile_name TEXT PRIMARY KEY,
  profile_hash TEXT NOT NULL,
  model_path TEXT NOT NULL,
  model_checksum TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  remediation TEXT,
  last_smoke_campaign_id TEXT,
  last_checked_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaigns (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  preset TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  phase TEXT NOT NULL DEFAULT 'common',
  model_profiles_json TEXT NOT NULL,
  suite_ids_json TEXT NOT NULL,
  ranking_policy_json TEXT NOT NULL,
  configuration_hash TEXT NOT NULL,
  previous_profile_name TEXT,
  current_run_id TEXT,
  pause_requested INTEGER NOT NULL DEFAULT 0,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  started_at TEXT,
  completed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS campaigns_status_created_idx ON campaigns(status, created_at);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  profile_name TEXT NOT NULL,
  profile_snapshot_json TEXT NOT NULL,
  profile_hash TEXT NOT NULL,
  suite_id TEXT NOT NULL,
  suite_snapshot_json TEXT NOT NULL,
  track TEXT NOT NULL DEFAULT 'controlled',
  status TEXT NOT NULL DEFAULT 'queued',
  expected_tasks INTEGER NOT NULL DEFAULT 0,
  completed_tasks INTEGER NOT NULL DEFAULT 0,
  passed_tasks INTEGER NOT NULL DEFAULT 0,
  failed_tasks INTEGER NOT NULL DEFAULT 0,
  infrastructure_failures INTEGER NOT NULL DEFAULT 0,
  score REAL,
  invalid_output_rate REAL,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  peak_gpu_temp_c REAL,
  peak_vram_bytes INTEGER,
  lease_id TEXT,
  error TEXT,
  started_at TEXT,
  completed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(campaign_id, profile_name, suite_id, track)
);
CREATE INDEX IF NOT EXISTS runs_campaign_status_idx ON runs(campaign_id, status, created_at);

CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  external_task_id TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'queued',
  reward REAL,
  passed INTEGER,
  steps INTEGER NOT NULL DEFAULT 0,
  prompt_tokens INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  error_class TEXT,
  user_message TEXT,
  technical_error TEXT,
  started_at TEXT,
  completed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(run_id, external_task_id, attempt)
);
CREATE INDEX IF NOT EXISTS tasks_run_status_idx ON tasks(run_id, status, created_at);

CREATE TABLE IF NOT EXISTS request_metrics (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  attempt INTEGER NOT NULL,
  request_id TEXT NOT NULL UNIQUE,
  model TEXT,
  requested_model TEXT,
  api_path TEXT NOT NULL,
  status_code INTEGER NOT NULL,
  prompt_tokens INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  cached_tokens INTEGER NOT NULL DEFAULT 0,
  reasoning_tokens INTEGER NOT NULL DEFAULT 0,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  tool_calls INTEGER NOT NULL DEFAULT 0,
  usage_source TEXT NOT NULL DEFAULT 'response',
  completed INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS request_metrics_task_attempt_idx ON request_metrics(task_id, attempt, created_at);
CREATE INDEX IF NOT EXISTS request_metrics_campaign_created_idx ON request_metrics(campaign_id, created_at);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id TEXT REFERENCES campaigns(id) ON DELETE CASCADE,
  run_id TEXT,
  task_id TEXT,
  event_type TEXT NOT NULL,
  message TEXT NOT NULL,
  details_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_campaign_created_idx ON events(campaign_id, created_at);

CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,
  task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  relative_path TEXT NOT NULL,
  size_bytes INTEGER NOT NULL DEFAULT 0,
  sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS artifacts_run_kind_idx ON artifacts(run_id, kind);

CREATE TABLE IF NOT EXISTS coordinator_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_migrations(version, applied_at)
VALUES (1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

INSERT OR IGNORE INTO schema_migrations(version, applied_at)
VALUES (2, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
