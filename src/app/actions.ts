"use server";

import { revalidatePath } from "next/cache";
import { activateProfile, deleteModel, restartProvider, saveFanCurve } from "@/lib/control";
import { queueDownload } from "@/lib/downloads";
import { runConfiguredBenchmark } from "@/lib/benchmarks";
import { getFanCurvePreset, toFanCurveProfile } from "@/lib/fan-presets";
import type { FanCurveProfile, LaunchProfile } from "@/lib/types";
import { currentAdminSession } from "@/lib/admin-auth";

async function requireAdmin(): Promise<void> {
  if (!await currentAdminSession()) throw new Error("Authentication required.");
}

async function revalidateAll(): Promise<void> {
  revalidatePath("/");
  revalidatePath("/models");
  revalidatePath("/benchmarks");
  revalidatePath("/logs");
  revalidatePath("/settings");
}

export async function restartProviderAction(): Promise<void> {
  await requireAdmin();
  await restartProvider();
  await revalidateAll();
}

export async function deleteModelAction(formData: FormData): Promise<void> {
  await requireAdmin();
  const modelPath = String(formData.get("modelPath") ?? "");
  await deleteModel(modelPath);
  await revalidateAll();
}

export async function activateProfileAction(formData: FormData): Promise<void> {
  await requireAdmin();
  const profile = JSON.parse(String(formData.get("profileJson") ?? "{}")) as LaunchProfile;
  await activateProfile(profile);
  await revalidateAll();
}

export async function saveFanCurveAction(formData: FormData): Promise<void> {
  await requireAdmin();
  const curve = JSON.parse(String(formData.get("curveJson") ?? "{}")) as FanCurveProfile;
  await saveFanCurve(curve);
  await revalidateAll();
}

export async function applyFanCurvePresetAction(formData: FormData): Promise<void> {
  await requireAdmin();
  const presetId = String(formData.get("presetId") ?? "");
  const preset = getFanCurvePreset(presetId);
  if (!preset) throw new Error(`Unknown fan preset: ${presetId}`);
  await saveFanCurve(toFanCurveProfile(preset));
  await revalidateAll();
}

export async function runBenchmarkAction(formData: FormData): Promise<void> {
  await requireAdmin();
  const prompt = String(formData.get("prompt") ?? "");
  const model = String(formData.get("model") ?? "");
  await runConfiguredBenchmark({ model, prompt, maxOutputTokens: 256, temperature: 0, repetitions: 1, warmup: true });
  await revalidateAll();
}

export async function downloadHuggingFaceAction(formData: FormData): Promise<void> {
  await requireAdmin();
  const repoId = String(formData.get("repoId") ?? "");
  const fileName = String(formData.get("fileName") ?? "");
  const revision = String(formData.get("revision") ?? "main");
  await queueDownload({ repoId, fileName, revision });
  await revalidateAll();
}
