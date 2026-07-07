import {
  createTtsAudiobook,
  createTtsPresentation,
  createTtsSynthesisJob,
  createTtsVoice,
  deleteTtsModel,
  deleteTtsPresentation,
  deleteTtsAudiobook,
  deleteTtsSynthesisJob,
  deleteTtsVoice,
  deleteTtsVoiceJob,
  getTtsSnapshot,
  importTtsVoice,
  renameTtsModel,
  renameTtsVoice,
  resumeTtsAudiobook,
  regenerateTtsAudiobookChunk,
  resumeTtsPresentation,
  stopTtsAudiobook,
  stopTtsPresentation,
  synthesizeTts,
  trainTtsModel,
} from "@/lib/tts";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return Response.json(await getTtsSnapshot());
}

export async function POST(request: Request): Promise<Response> {
  try {
    const contentType = request.headers.get("content-type") ?? "";
    if (contentType.includes("multipart/form-data")) {
      const formData = await request.formData();
      const action = String(formData.get("action") ?? "");
      if (action === "importVoice") {
        const job = await importTtsVoice(formData);
        return Response.json({ ok: true, job }, { status: 202 });
      }
      if (action === "createAudiobook") {
        const job = await createTtsAudiobook(formData);
        return Response.json({ ok: true, job }, { status: 202 });
      }
      if (action === "createPresentation") {
        const job = await createTtsPresentation(formData);
        return Response.json({ ok: true, job }, { status: 202 });
      }
      return Response.json({ error: "Unknown TTS multipart action." }, { status: 400 });
    }

    const body = await request.json() as Record<string, unknown>;
    const action = String(body.action ?? "");

    if (action === "createVoice") {
      const voice = await createTtsVoice({
        name: body.name,
        instruct: body.instruct,
        language: body.language || "English",
        device: body.device || undefined,
      });
      return Response.json({ ok: true, job: voice }, { status: 202 });
    }

    if (action === "trainModel") {
      const model = await trainTtsModel({
        voice_id: body.voiceId,
        name: body.name,
      });
      return Response.json({ ok: true, model }, { status: 202 });
    }

    if (action === "renameVoice") {
      const voice = await renameTtsVoice(String(body.id ?? ""), String(body.name ?? ""));
      return Response.json({ ok: true, voice });
    }

    if (action === "renameModel") {
      const model = await renameTtsModel(String(body.id ?? ""), String(body.name ?? ""));
      return Response.json({ ok: true, model });
    }

    if (action === "deleteVoice") {
      await deleteTtsVoice(String(body.id ?? ""));
      return Response.json({ ok: true });
    }

    if (action === "deleteVoiceJob") {
      await deleteTtsVoiceJob(String(body.id ?? ""));
      return Response.json({ ok: true });
    }

    if (action === "deleteModel") {
      await deleteTtsModel(String(body.id ?? ""));
      return Response.json({ ok: true });
    }

    if (action === "createSynthesisJob") {
      const job = await createTtsSynthesisJob({
        text: body.text,
        model_id: body.modelId,
      });
      return Response.json({ ok: true, job }, { status: 202 });
    }

    if (action === "deleteSynthesisJob") {
      await deleteTtsSynthesisJob(String(body.id ?? ""));
      return Response.json({ ok: true });
    }

    if (action === "stopAudiobook") {
      const job = await stopTtsAudiobook(String(body.id ?? ""));
      return Response.json({ ok: true, job });
    }

    if (action === "resumeAudiobook") {
      const job = await resumeTtsAudiobook(String(body.id ?? ""));
      return Response.json({ ok: true, job }, { status: 202 });
    }

    if (action === "regenerateAudiobookChunk") {
      const chunk = Number(body.chunk);
      if (!Number.isInteger(chunk) || chunk < 0) return Response.json({ error: "Invalid audiobook chunk index." }, { status: 400 });
      const job = await regenerateTtsAudiobookChunk(String(body.id ?? ""), chunk);
      return Response.json({ ok: true, job }, { status: 202 });
    }

    if (action === "deleteAudiobook") {
      await deleteTtsAudiobook(String(body.id ?? ""));
      return Response.json({ ok: true });
    }

    if (action === "stopPresentation") {
      const job = await stopTtsPresentation(String(body.id ?? ""));
      return Response.json({ ok: true, job });
    }

    if (action === "resumePresentation") {
      const job = await resumeTtsPresentation(String(body.id ?? ""));
      return Response.json({ ok: true, job }, { status: 202 });
    }

    if (action === "deletePresentation") {
      await deleteTtsPresentation(String(body.id ?? ""));
      return Response.json({ ok: true });
    }

    if (action === "synthesize") {
      const upstream = await synthesizeTts({
        text: body.text,
        voice_id: body.voiceId || undefined,
        model_id: body.modelId || undefined,
        use_default: body.useDefault === true,
      });
      return new Response(upstream.body, {
        status: 200,
        headers: {
          "Content-Type": "audio/mpeg",
          "Cache-Control": "no-store",
        },
      });
    }

    return Response.json({ error: "Unknown TTS action." }, { status: 400 });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "TTS action failed" }, { status: 500 });
  }
}
