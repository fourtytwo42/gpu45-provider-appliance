import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import Database from "better-sqlite3";
import { afterEach, describe, expect, it } from "vitest";
import { readPayloadRows } from "./job-history";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) fs.rmSync(root, { recursive: true, force: true }); });

describe("readPayloadRows", () => {
  it("reads valid persisted jobs and skips malformed rows", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "gpu45-job-history-"));
    roots.push(root);
    const dbPath = path.join(root, "jobs.db");
    const database = new Database(dbPath);
    database.exec("CREATE TABLE jobs(position INTEGER, payload_json TEXT)");
    database.prepare("INSERT INTO jobs VALUES(?,?)").run(1, JSON.stringify({ id: "good" }));
    database.prepare("INSERT INTO jobs VALUES(?,?)").run(2, "not-json");
    database.close();
    expect(readPayloadRows<{ id: string }>(dbPath, "SELECT payload_json FROM jobs ORDER BY position DESC")).toEqual([{ id: "good" }]);
  });

  it("returns an empty history when a service database is absent", () => {
    expect(readPayloadRows("/missing/gpu45/jobs.db", "SELECT payload_json FROM jobs")).toEqual([]);
  });
});
