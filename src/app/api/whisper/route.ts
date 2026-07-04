import { createWhisperJob, deleteWhisperJob, getWhisperSnapshot } from "@/lib/whisper";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return Response.json(await getWhisperSnapshot());
}

export async function POST(request: Request): Promise<Response> {
  try {
    const contentType = request.headers.get("content-type") ?? "";
    if (contentType.includes("multipart/form-data")) {
      const formData = await request.formData();
      const job = await createWhisperJob(formData);
      return Response.json({ ok: true, job }, { status: 202 });
    }

    const body = await request.json() as Record<string, unknown>;
    const action = String(body.action ?? "");
    if (action === "deleteJob") {
      return Response.json(await deleteWhisperJob(String(body.id ?? "")));
    }
    return Response.json({ error: "Unknown Whisper action." }, { status: 400 });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Whisper action failed" }, { status: 500 });
  }
}
