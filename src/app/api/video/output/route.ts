import { getConfig } from "@/lib/config";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const id = url.searchParams.get("id");
  if (!id) return Response.json({ error: "id is required" }, { status: 400 });

  const upstream = await fetch(`${getConfig().videoUrl.replace(/\/$/, "")}/jobs/${encodeURIComponent(id)}/video`, {
    cache: "no-store",
  });
  if (!upstream.ok) return Response.json({ error: await upstream.text() }, { status: upstream.status });
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": upstream.headers.get("Content-Type") ?? "video/mp4",
      "Cache-Control": "no-store",
    },
  });
}
