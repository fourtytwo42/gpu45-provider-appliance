import { agenticCampaignAction } from "@/lib/agentic-benchmarks";

export async function POST(request: Request, context: { params: Promise<{ id: string }> }): Promise<Response> {
  try {
    const body = await request.json() as { action?: string };
    if (!body.action) return Response.json({ error: "action is required" }, { status: 400 });
    return Response.json(await agenticCampaignAction((await context.params).id, body.action));
  } catch (error) { return Response.json({ error: error instanceof Error ? error.message : "Action failed" }, { status: 400 }); }
}
