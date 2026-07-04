import { fetchUrl } from "@/lib/research";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  try {
    const body = await request.json() as { url?: string; render?: false | "auto" | true; extractLinks?: boolean };
    if (!body.url) return Response.json({ error: "url is required" }, { status: 400 });
    return Response.json(await fetchUrl(body.url, body.render ?? false, body.extractLinks !== false));
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Fetch failed" }, { status: 502 });
  }
}
