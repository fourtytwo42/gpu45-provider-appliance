import { createAgenticCampaign, listAgenticCampaigns } from "@/lib/agentic-benchmarks";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  try { return Response.json({ campaigns: await listAgenticCampaigns() }); }
  catch (error) { return Response.json({ error: error instanceof Error ? error.message : "Coordinator unavailable" }, { status: 503 }); }
}

export async function POST(request: Request): Promise<Response> {
  try { return Response.json(await createAgenticCampaign(await request.json()), { status: 202 }); }
  catch (error) { return Response.json({ error: error instanceof Error ? error.message : "Campaign creation failed" }, { status: 400 }); }
}
