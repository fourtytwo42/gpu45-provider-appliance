import "@testing-library/jest-dom/vitest";
import os from "node:os";
import path from "node:path";

process.env.DATABASE_URL ??= `file:${path.join(os.tmpdir(), `gpu45-vitest-${process.pid}.db`)}`;
process.env.GPU45_MODE ??= "mock";
