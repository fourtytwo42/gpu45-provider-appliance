import { fetchPocketTtsAudio } from "@/lib/pocket-tts";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const { searchParams } = new URL(request.url);
  const id = searchParams.get("id");
  if (!id) return Response.json({ error: "Missing Pocket TTS job id." }, { status: 400 });
  try {
    const upstream = await fetchPocketTtsAudio(id, searchParams.get("download") === "1");
    return new Response(upstream.body, {
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "audio/wav",
        "Content-Disposition": upstream.headers.get("content-disposition") ?? "inline",
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Pocket TTS audio unavailable" }, { status: 404 });
  }
}
