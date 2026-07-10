import { fetchImageOutput } from "@/lib/images";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request): Promise<Response> {
  try {
    const id = new URL(request.url).searchParams.get("id");
    if (!id) return Response.json({ error: "Missing image job id." }, { status: 400 });

    const upstream = await fetchImageOutput(id);
    const contentType = upstream.headers.get("content-type") ?? "image/png";
    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": contentType,
        "Cache-Control": "private, no-store",
      },
    });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Image output failed" }, { status: 500 });
  }
}
