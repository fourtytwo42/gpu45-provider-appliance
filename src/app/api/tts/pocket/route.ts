import { createPocketTtsJob, deletePocketTtsJob, deletePocketTtsVoice, getPocketTtsSnapshot, importPocketTtsVoice } from "@/lib/pocket-tts";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return Response.json(await getPocketTtsSnapshot());
}

export async function POST(request: Request): Promise<Response> {
  try {
    const contentType = request.headers.get("content-type") ?? "";
    if (contentType.includes("multipart/form-data")) {
      const voice = await importPocketTtsVoice(await request.formData());
      return Response.json({ ok: true, voice }, { status: 201 });
    }
    const body = await request.json() as Record<string, unknown>;
    const action = String(body.action ?? "createJob");
    if (action === "createJob") {
      const job = await createPocketTtsJob(String(body.text ?? ""), String(body.voiceId ?? ""));
      return Response.json({ ok: true, job }, { status: 202 });
    }
    if (action === "deleteJob") {
      await deletePocketTtsJob(String(body.id ?? ""));
      return Response.json({ ok: true });
    }
    if (action === "deleteVoice") {
      await deletePocketTtsVoice(String(body.id ?? ""));
      return Response.json({ ok: true });
    }
    return Response.json({ error: "Unknown Pocket TTS action." }, { status: 400 });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Pocket TTS request failed" }, { status: 500 });
  }
}
