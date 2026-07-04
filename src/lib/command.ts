import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export function shQuote(value: string): string {
  return `'${value.replaceAll("'", `'\"'\"'`)}'`;
}

export async function runBash(command: string): Promise<string> {
  const { stdout } = await execFileAsync("bash", ["-lc", command], {
    maxBuffer: 20 * 1024 * 1024,
  });
  return String(stdout);
}

export async function runBashJson<T>(command: string): Promise<T> {
  const text = await runBash(command);
  return JSON.parse(text) as T;
}

export async function runBashLines(command: string): Promise<string[]> {
  const text = await runBash(command);
  return text.split(/\r?\n/).map((line) => line.trimEnd()).filter(Boolean);
}

