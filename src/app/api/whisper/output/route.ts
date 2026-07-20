import { fetchWhisperOutline, fetchWhisperTranscript } from "@/lib/whisper";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  try {
    const url = new URL(request.url);
    const id = url.searchParams.get("id");
    if (!id) return Response.json({ error: "Missing transcript id." }, { status: 400 });
    const asset = url.searchParams.get("asset") === "outline" ? "outline" : "transcript";
    const upstream = asset === "outline" ? await fetchWhisperOutline(id) : await fetchWhisperTranscript(id);
    const filename = upstream.headers.get(asset === "outline" ? "x-outline-name" : "x-transcript-name")
      ?? (asset === "outline" ? `${id}-outline.md` : `${id}.md`);
    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": "text/markdown; charset=utf-8",
        "Content-Disposition": `attachment; filename="${filename.replace(/"/g, "")}"`,
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Markdown download failed" }, { status: 500 });
  }
}
