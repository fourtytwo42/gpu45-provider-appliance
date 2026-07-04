import { extractJob } from "@/lib/research";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  try {
    const body = await request.json() as { url?: string; render?: "auto" | true | false };
    if (!body.url) return Response.json({ error: "url is required" }, { status: 400 });
    return Response.json(await extractJob(body.url, body.render ?? "auto"));
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Job extraction failed" }, { status: 502 });
  }
}
