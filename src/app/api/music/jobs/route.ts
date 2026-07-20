import { createMusicJob } from "@/lib/music";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  try {
    const contentType = request.headers.get("content-type") ?? "";
    const payload = contentType.startsWith("multipart/form-data")
      ? await request.formData()
      : await request.json() as Record<string, unknown>;
    return Response.json(await createMusicJob(payload), { status: 202 });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Music job could not be created." }, { status: 400 });
  }
}
