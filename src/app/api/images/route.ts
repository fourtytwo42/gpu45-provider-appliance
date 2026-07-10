import {
  createImageJob,
  deleteImageJob,
  downloadImageModel,
  getImageSnapshot,
} from "@/lib/images";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(): Promise<Response> {
  return Response.json(await getImageSnapshot());
}

export async function POST(request: Request): Promise<Response> {
  try {
    const body = await request.json() as Record<string, unknown>;
    const action = String(body.action ?? "");

    if (action === "createJob") {
      const { action: _action, ...payload } = body;
      void _action;
      const job = await createImageJob(payload);
      return Response.json({ ok: true, job }, { status: 202 });
    }

    if (action === "deleteJob") {
      return Response.json(await deleteImageJob(String(body.id ?? "")));
    }

    if (action === "downloadModel") {
      return Response.json(await downloadImageModel(String(body.profile ?? "")), { status: 202 });
    }

    return Response.json({ error: "Unknown image action." }, { status: 400 });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Image action failed" }, { status: 500 });
  }
}
