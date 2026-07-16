import { getAgenticCampaign } from "@/lib/agentic-benchmarks";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }): Promise<Response> {
  try { return Response.json(await getAgenticCampaign((await context.params).id)); }
  catch (error) { return Response.json({ error: error instanceof Error ? error.message : "Campaign unavailable" }, { status: 503 }); }
}
