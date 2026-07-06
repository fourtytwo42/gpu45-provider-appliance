import { fetchTtsPresentationOutput, fetchTtsPresentationSlideAudio } from "@/lib/tts";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  try {
    const url = new URL(request.url);
    const id = url.searchParams.get("id");
    const slideRaw = url.searchParams.get("slide");
    const shouldDownload = url.searchParams.get("download") === "1";
    if (!id) return Response.json({ error: "Missing presentation job id." }, { status: 400 });

    if (slideRaw != null) {
      const slide = Number(slideRaw);
      if (!Number.isInteger(slide) || slide < 0) return Response.json({ error: "Invalid slide index." }, { status: 400 });
      const upstream = await fetchTtsPresentationSlideAudio(id, slide);
      return new Response(upstream.body, {
        status: 200,
        headers: {
          "Content-Type": upstream.headers.get("content-type") ?? "audio/mpeg",
          "Cache-Control": "no-store",
          ...(shouldDownload ? { "Content-Disposition": `attachment; filename="tts-presentation-${id}-slide-${slide + 1}.mp3"` } : {}),
        },
      });
    }

    const upstream = await fetchTtsPresentationOutput(id);
    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "Cache-Control": "no-store",
        ...(shouldDownload ? { "Content-Disposition": `attachment; filename="tts-presentation-${id}.pptx"` } : {}),
      },
    });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Presentation output fetch failed" }, { status: 500 });
  }
}
