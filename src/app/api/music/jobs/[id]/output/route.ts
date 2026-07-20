import { fetchMusicOutput } from "@/lib/music";

export const dynamic = "force-dynamic";

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }): Promise<Response> {
  try {
    const asset = new URL(request.url).searchParams.get("asset") ?? "master";
    const upstream = await fetchMusicOutput((await params).id, asset);
    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": upstream.headers.get("Content-Type") ?? "audio/wav",
        "Content-Disposition": upstream.headers.get("Content-Disposition") ?? `attachment; filename=music-${asset}.wav`,
        "Cache-Control": "private, no-store",
      },
    });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Music output is unavailable." }, { status: 404 });
  }
}
