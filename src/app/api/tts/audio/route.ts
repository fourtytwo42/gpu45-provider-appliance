import { fetchTtsSynthesisAudio } from "@/lib/tts";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  try {
    const url = new URL(request.url);
    const id = url.searchParams.get("id");
    const shouldDownload = url.searchParams.get("download") === "1";
    if (!id) return Response.json({ error: "Missing synthesis job id." }, { status: 400 });

    const upstream = await fetchTtsSynthesisAudio(id);
    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "audio/mpeg",
        "Cache-Control": "no-store",
        ...(shouldDownload ? { "Content-Disposition": `attachment; filename="tts-synthesis-${id}.mp3"` } : {}),
      },
    });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : "Synthesis audio fetch failed" },
      { status: 500 },
    );
  }
}
