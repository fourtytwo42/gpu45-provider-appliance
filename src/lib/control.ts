import { promises as fs } from "node:fs";
import path from "node:path";
import { prisma } from "./db";
import { getConfig, isLiveRuntime } from "./config";
import { shQuote } from "./command";
import { removeHostPath, runHostCommand, writeHostText } from "./proxmox";
import { collectDashboardSnapshot } from "./collectors";
import type { FanCurveProfile, LaunchProfile } from "./types";
import { classifyModelAsset, findModelCompanions } from "./model-assets";
import { modelProfileName } from "./model-catalog";

type ControlResult = {
  ok: boolean;
  message: string;
};

async function ensureDir(filePath: string): Promise<void> {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
}

async function writeJson(filePath: string, value: unknown): Promise<void> {
  const payload = `${JSON.stringify(value, null, 2)}\n`;
  const remoteWritten = await writeHostText(filePath, payload);
  if (remoteWritten) return;
  await ensureDir(filePath);
  await fs.writeFile(filePath, payload, "utf8");
}

export function validateFanCurve(profile: FanCurveProfile): string | null {
  if (!profile.name?.trim()) return "Fan curve name is required.";
  if (!Array.isArray(profile.points) || profile.points.length < 2) return "Fan curve needs at least two points.";
  let previousTemp = -Infinity;
  let hasFullFanGuard = false;
  for (const point of profile.points) {
    if (!Number.isFinite(point.temperatureC) || !Number.isInteger(point.pwm)) {
      return "Fan curve points must use numeric temperatures and integer PWM values.";
    }
    if (point.temperatureC <= previousTemp) return "Fan curve temperatures must increase from top to bottom.";
    if (point.pwm < 70 || point.pwm > 255) return "Fan PWM must stay between 70 and 255.";
    if (point.temperatureC <= 86 && point.pwm === 255) hasFullFanGuard = true;
    previousTemp = point.temperatureC;
  }
  if (!hasFullFanGuard) return "Fan curve must force 255 PWM at or below 86C.";
  if (profile.idlePwm !== undefined && (profile.idlePwm < 70 || profile.idlePwm > 255)) {
    return "Idle PWM must stay between 70 and 255.";
  }
  if (profile.startupPwm !== undefined && (profile.startupPwm < 70 || profile.startupPwm > 255)) {
    return "Startup PWM must stay between 70 and 255.";
  }
  if (profile.channels?.some((channel) => !channel.pwm.startsWith("pwm") || !channel.fan.startsWith("fan") || !channel.fan.endsWith("_input"))) {
    return "Fan channel mapping is invalid.";
  }
  return null;
}

export async function restartProvider(): Promise<ControlResult> {
  if (!isLiveRuntime()) return { ok: true, message: "Mock runtime - restart skipped." };
  const output = await runHostCommand(`sudo -n systemctl restart ${shQuote(getConfig().providerService)}`);
  if (output === null) return { ok: false, message: "Provider restart failed." };
  await prisma.auditLog.create({
    data: {
      action: "provider.restart",
      subject: getConfig().providerService,
      details: "Restarted via web console",
    },
  });
  return { ok: true, message: "Provider restart requested." };
}

export async function deleteModel(modelPath: string): Promise<ControlResult> {
  if (!isLiveRuntime()) return { ok: true, message: "Mock runtime - delete skipped." };
  const current = await collectDashboardSnapshot();
  const known = current.models.find((model) => model.path === modelPath);
  if (!known) return { ok: false, message: "Model is not in the managed model inventory." };
  const paths = new Set([modelPath]);
  if (classifyModelAsset(known.name) === "model") {
    const companions = findModelCompanions(current.models, modelPath);
    if (companions.modelDraftPath) paths.add(companions.modelDraftPath);
    if (companions.mmprojPath) paths.add(companions.mmprojPath);
    const stored = await prisma.modelAsset.findUnique({ where: { path: modelPath } });
    if (stored?.draftPath) paths.add(stored.draftPath);
    if (stored?.projectorPath) paths.add(stored.projectorPath);
    const profiles = await prisma.launchProfile.findMany({ where: { modelPath } });
    for (const profile of profiles) {
      if (profile.modelDraftPath) paths.add(profile.modelDraftPath);
      if (profile.mmprojPath) paths.add(profile.mmprojPath);
    }
  }
  if (current.models.some((model) => model.active && paths.has(model.path))) {
    return { ok: false, message: "Refusing to delete an active model bundle." };
  }
  for (const managedPath of paths) {
    if (!await removeHostPath(managedPath)) return { ok: false, message: `Model deletion failed for ${path.basename(managedPath)}.` };
  }
  await prisma.$transaction([
    prisma.modelAsset.deleteMany({ where: { path: { in: [...paths] } } }),
    prisma.launchProfile.deleteMany({ where: { modelPath } }),
  ]);
  await prisma.auditLog.create({
    data: {
      action: "model.delete",
      subject: modelPath,
      details: `Deleted ${paths.size} managed artifact(s) via web console`,
    },
  });
  return { ok: true, message: `Deleted model bundle (${paths.size} artifact${paths.size === 1 ? "" : "s"}).` };
}

export async function activateProfile(profile: LaunchProfile): Promise<ControlResult> {
  if (!isLiveRuntime()) return { ok: true, message: "Mock runtime - profile saved." };
  const cfg = getConfig();
  await writeJson(cfg.providerProfilePath, profile);
  await prisma.launchProfile.updateMany({ data: { active: false } });
  await prisma.launchProfile.upsert({
    where: { name: profile.name },
    create: { ...profile, active: true },
    update: { ...profile, active: true },
  });
  const output = await runHostCommand(`sudo -n systemctl restart ${shQuote(cfg.providerService)}`);
  if (output === null) return { ok: false, message: "Profile saved, but provider restart failed." };
  await prisma.auditLog.create({
    data: {
      action: "profile.activate",
      subject: profile.name,
      details: `Wrote ${cfg.providerProfilePath} and restarted service`,
    },
  });
  return { ok: true, message: `Activated profile ${profile.name}.` };
}

export async function activateModel(modelPath: string): Promise<ControlResult> {
  if (!isLiveRuntime()) return { ok: true, message: "Mock runtime - model activation skipped." };
  const snapshot = await collectDashboardSnapshot();
  const model = snapshot.models.find((asset) => asset.path === modelPath);
  if (!model) return { ok: false, message: "Model is not in the managed inventory." };
  if (classifyModelAsset(model.name) !== "model") return { ok: false, message: "MTP and projector files cannot be loaded as primary models." };

  const saved = await prisma.launchProfile.findFirst({ where: { modelPath } });
  const base = saved ?? snapshot.profiles.find((profile) => profile.active) ?? snapshot.profiles[0];
  if (!base) return { ok: false, message: "No launch profile is available." };
  const discovered = findModelCompanions(snapshot.models, modelPath);
  const stored = await prisma.modelAsset.findUnique({ where: { path: modelPath } });
  const modelDraftPath = saved?.modelDraftPath ?? stored?.draftPath ?? discovered.modelDraftPath;
  const mmprojPath = saved?.mmprojPath ?? stored?.projectorPath ?? discovered.mmprojPath;
  const embeddedMtp = path.dirname(modelPath).toLowerCase().includes("mtp");
  const specType = modelDraftPath || embeddedMtp ? "draft-mtp" : "none";
  const profile: LaunchProfile = {
    ...base,
    name: saved?.name ?? modelProfileName(modelPath),
    description: saved?.description ?? `${model.name}${modelDraftPath ? " with external MTP" : embeddedMtp ? " with embedded MTP" : ""}`,
    modelPath,
    modelDraftPath,
    mmprojPath,
    specType,
    active: true,
  };
  const result = await activateProfile(profile);
  if (!result.ok) return result;
  return {
    ok: true,
    message: `${model.name} activation requested${modelDraftPath ? ` with ${path.basename(modelDraftPath)}` : ""}.`,
  };
}

export async function saveFanCurve(profile: FanCurveProfile): Promise<ControlResult> {
  const validationError = validateFanCurve(profile);
  if (validationError) return { ok: false, message: validationError };
  if (!isLiveRuntime()) return { ok: true, message: "Mock runtime - fan curve saved." };
  const cfg = getConfig();
  await writeJson(cfg.fanProfilePath, profile);
  await prisma.fanCurveProfile.updateMany({ data: { active: false } });
  await prisma.fanCurveProfile.upsert({
    where: { name: profile.name },
    create: { name: profile.name, description: profile.description ?? null, pointsJson: JSON.stringify(profile.points), active: true },
    update: { description: profile.description ?? null, pointsJson: JSON.stringify(profile.points), active: true },
  });
  const output = await runHostCommand(`sudo -n systemctl restart ${shQuote(cfg.fanService)}`);
  if (output === null) return { ok: false, message: "Fan curve saved, but service restart failed." };
  await prisma.auditLog.create({
    data: {
      action: "fan_curve.save",
      subject: profile.name,
      details: `Wrote ${cfg.fanProfilePath} and restarted service`,
    },
  });
  return { ok: true, message: `Saved fan curve ${profile.name}.` };
}
