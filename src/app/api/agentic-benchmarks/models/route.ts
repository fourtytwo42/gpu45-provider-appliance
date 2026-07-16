import { agenticModelSmoke, listAgenticModels } from "@/lib/agentic-benchmarks";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  try { return Response.json({ models: await listAgenticModels() }); }
  catch (error) { return Response.json({ error: error instanceof Error ? error.message : "Coordinator unavailable" }, { status: 503 }); }
}

export async function POST(request: Request): Promise<Response> {
  try {
    const body = await request.json() as { profileName?: string };
    if (!body.profileName) return Response.json({ error: "profileName is required" }, { status: 400 });
    return Response.json(await agenticModelSmoke(body.profileName), { status: 202 });
  } catch (error) { return Response.json({ error: error instanceof Error ? error.message : "Smoke test could not be queued" }, { status: 400 }); }
}
