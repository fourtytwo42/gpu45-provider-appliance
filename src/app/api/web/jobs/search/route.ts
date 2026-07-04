import { searchJobs } from "@/lib/research";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  try {
    const body = await request.json() as { query?: string; remoteOnly?: boolean; officialOnly?: boolean; limit?: number };
    if (!body.query?.trim()) return Response.json({ error: "query is required" }, { status: 400 });
    return Response.json(await searchJobs(body.query, body.remoteOnly !== false, body.officialOnly !== false, body.limit ?? 10));
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Job search failed" }, { status: 502 });
  }
}
