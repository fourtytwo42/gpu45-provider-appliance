import { getUnifiedJob, getUnifiedJobItems } from "@/lib/jobs";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request, context: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await context.params;
  const decodedId = decodeURIComponent(id);
  if (!await getUnifiedJob(decodedId)) return Response.json({ error: "Job not found." }, { status: 404 });
  const url = new URL(request.url);
  const cursor = Number(url.searchParams.get("cursor") ?? 0);
  const limit = Number(url.searchParams.get("limit") ?? 50);
  return Response.json(await getUnifiedJobItems(decodedId, cursor, limit));
}
