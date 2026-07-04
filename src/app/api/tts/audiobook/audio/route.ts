import { fetchTtsAudiobookAudio } from "@/lib/tts";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  try {
    const url = new URL(request.url);
    const id = url.searchParams.get("id");
    const chunkRaw = url.searchParams.get("chunk");
    const shouldDownload = url.searchParams.get("download") === "1";
    if (!id) return Response.json({ error: "Missing audiobook job id." }, { status: 400 });

    let chunk: number | undefined;
    if (chunkRaw != null) {
      const parsedChunk = Number(chunkRaw);
      if (!Number.isInteger(parsedChunk) || parsedChunk < 0) {
        return Response.json({ error: "Invalid chunk index." }, { status: 400 });
      }
      chunk = parsedChunk;
    }

    const upstream = await fetchTtsAudiobookAudio(id, chunk);
    const filename = chunk == null ? `tts-audiobook-${id}.mp3` : `tts-audiobook-${id}-chunk-${chunk}.mp3`;
    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "audio/mpeg",
        "Cache-Control": "no-store",
        ...(shouldDownload ? { "Content-Disposition": `attachment; filename="${filename}"` } : {}),
      },
    });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Audiobook audio fetch failed" }, { status: 500 });
  }
}
