import json
import os
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock


class JobStore:
    def __init__(self, json_path: Path):
        self.json_path = json_path
        self.db_path = json_path.with_suffix(".db")
        self.lock = RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self):
        with closing(self._connect()) as connection, connection:
            connection.executescript("CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL); CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY,position INTEGER NOT NULL,payload_json TEXT NOT NULL,updated_at TEXT NOT NULL); CREATE INDEX IF NOT EXISTS jobs_position_idx ON jobs(position);")
            connection.execute("INSERT OR REPLACE INTO metadata VALUES ('schema_version','1')")
            if connection.execute("SELECT 1 FROM metadata WHERE key='json_imported'").fetchone() is None:
                jobs = json.loads(self.json_path.read_text(encoding="utf-8")) if self.json_path.exists() else []
                now = datetime.now(timezone.utc).isoformat()
                for position, job in enumerate(jobs):
                    connection.execute("INSERT OR REPLACE INTO jobs VALUES(?,?,?,?)", (str(job.get("id") or position), position, json.dumps(job), now))
                if self.json_path.exists():
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    backup = self.json_path.with_name(f"{self.json_path.name}.migration-{stamp}.bak")
                    shutil.copy2(self.json_path, backup)
                    os.chmod(backup, 0o444)
                connection.execute("INSERT INTO metadata VALUES('json_imported',?)", (now,))

    def load(self):
        with self.lock, closing(self._connect()) as connection:
            return [json.loads(row[0]) for row in connection.execute("SELECT payload_json FROM jobs ORDER BY position")]

    def save(self, jobs):
        now = datetime.now(timezone.utc).isoformat()
        with self.lock, closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM jobs")
            for position, job in enumerate(jobs):
                connection.execute("INSERT INTO jobs VALUES(?,?,?,?)", (str(job.get("id") or position), position, json.dumps(job), now))
