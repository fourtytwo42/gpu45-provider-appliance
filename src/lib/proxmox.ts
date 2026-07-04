import path from "node:path";
import { promises as fs } from "node:fs";
import { Client } from "ssh2";
import { getConfig } from "./config";
import { runBash, shQuote } from "./command";

type RemoteSettings = {
  host: string;
  user: string;
  password: string;
  port: number;
};

type RemoteCommandResult = {
  stdout: string;
  stderr: string;
  code: number | null;
};

function getRemoteSettings(): RemoteSettings | null {
  const cfg = getConfig();
  if (!cfg.proxmoxHost || !cfg.proxmoxPassword) return null;
  return {
    host: cfg.proxmoxHost,
    user: cfg.proxmoxUser,
    password: cfg.proxmoxPassword,
    port: cfg.proxmoxPort,
  };
}

function connectRemote(): Promise<Client> {
  const settings = getRemoteSettings();
  if (!settings) return Promise.reject(new Error("remote Proxmox access is not configured"));

  return new Promise((resolve, reject) => {
    const client = new Client();
    client
      .on("ready", () => resolve(client))
      .on("error", reject)
      .connect({
        host: settings.host,
        port: settings.port,
        username: settings.user,
        password: settings.password,
        readyTimeout: 20_000,
      });
  });
}

async function runRemoteCommand(command: string): Promise<RemoteCommandResult | null> {
  if (!getRemoteSettings()) return null;

  let client: Client | null = null;
  try {
    client = await connectRemote();
    return await new Promise<RemoteCommandResult>((resolve, reject) => {
      client?.exec(command, (error, stream) => {
        if (error || !stream) {
          reject(error ?? new Error("remote command stream missing"));
          return;
        }

        let stdout = "";
        let stderr = "";
        stream.on("data", (chunk: Buffer) => {
          stdout += chunk.toString();
        });
        stream.stderr.on("data", (chunk: Buffer) => {
          stderr += chunk.toString();
        });
        stream.on("close", (code: number | undefined) => {
          resolve({ stdout, stderr, code: code ?? null });
        });
      });
    });
  } catch {
    return null;
  } finally {
    client?.end();
  }
}

export async function runHostCommand(command: string): Promise<string | null> {
  const remote = await runRemoteCommand(command);
  if (remote && remote.code === 0) {
    return remote.stdout;
  }
  return runBash(command).catch(() => null);
}

export async function readHostText(filePath: string): Promise<string | null> {
  const remote = await runRemoteCommand(`cat ${shQuote(filePath)}`);
  if (remote && remote.code === 0) {
    return remote.stdout;
  }

  try {
    return await fs.readFile(filePath, "utf8");
  } catch {
    return null;
  }
}

export async function readContainerText(filePath: string, containerId?: number): Promise<string | null> {
  const cfg = getConfig();
  const targetContainerId = containerId ?? cfg.gpuContainerId;
  const remote = await runRemoteCommand(`pct exec ${targetContainerId} -- cat ${shQuote(filePath)}`);
  if (remote && remote.code === 0) {
    return remote.stdout;
  }

  try {
    return await fs.readFile(filePath, "utf8");
  } catch {
    return runBash(`pct exec ${targetContainerId} -- cat ${shQuote(filePath)}`).catch(() => null);
  }
}

export async function runContainerCommand(command: string, containerId?: number): Promise<string | null> {
  const cfg = getConfig();
  const targetContainerId = containerId ?? cfg.gpuContainerId;
  const wrapped = `pct exec ${targetContainerId} -- sh -lc ${shQuote(command)}`;
  const remote = await runRemoteCommand(wrapped);
  if (remote && remote.code === 0) {
    return remote.stdout;
  }
  return runBash(wrapped).catch(() => null);
}

export async function writeHostText(filePath: string, content: string): Promise<boolean> {
  const remote = getRemoteSettings();
  if (remote) {
    const encoded = Buffer.from(content, "utf8").toString("base64");
    const command = `mkdir -p ${shQuote(path.posix.dirname(filePath))} && printf '%s' ${shQuote(encoded)} | base64 -d > ${shQuote(filePath)}`;
    const result = await runRemoteCommand(command);
    if (result && result.code === 0) {
      return true;
    }
    return false;
  }

  try {
    await fs.mkdir(path.dirname(filePath), { recursive: true });
    await fs.writeFile(filePath, content, "utf8");
    return true;
  } catch {
    return false;
  }
}

export async function writeContainerText(filePath: string, content: string, containerId?: number): Promise<boolean> {
  const cfg = getConfig();
  const targetContainerId = containerId ?? cfg.gpuContainerId;
  const encoded = Buffer.from(content, "utf8").toString("base64");
  const command = `pct exec ${targetContainerId} -- sh -lc ${shQuote(
    `mkdir -p ${shQuote(path.posix.dirname(filePath))} && printf '%s' ${shQuote(encoded)} | base64 -d > ${shQuote(filePath)}`,
  )}`;
  const remote = await runRemoteCommand(command);
  if (remote && remote.code === 0) {
    return true;
  }
  return false;
}

export async function removeHostPath(filePath: string): Promise<boolean> {
  const remote = await runRemoteCommand(`rm -rf ${shQuote(filePath)}`);
  if (remote && remote.code === 0) {
    return true;
  }

  try {
    await fs.rm(filePath, { recursive: true, force: true });
    return true;
  } catch {
    return false;
  }
}

export async function listModelFiles(rootPath: string): Promise<Array<{ path: string; sizeBytes: number }>> {
  const remote = await runRemoteCommand(
    `if [ -d ${shQuote(rootPath)} ]; then find ${shQuote(rootPath)} -type f -name '*.gguf' -printf '%p\t%s\n'; fi`,
  );
  if (!remote || remote.code !== 0 || !remote.stdout.trim()) {
    return [];
  }

  return remote.stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [filePath, sizeText] = line.split("\t");
      const sizeBytes = Number(sizeText);
      return Number.isFinite(sizeBytes) ? { path: filePath, sizeBytes } : null;
    })
    .filter((item): item is { path: string; sizeBytes: number } => item !== null);
}
