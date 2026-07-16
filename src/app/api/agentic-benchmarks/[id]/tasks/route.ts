import { listAgenticTasks } from "@/lib/agentic-benchmarks";

export const dynamic = "force-dynamic";

export async function GET(request: Request, context: { params: Promise<{ id: string }> }): Promise<Response> {
  const query = new URL(request.url).searchParams;
  try { return Response.json(await listAgenticTasks((await context.params).id, Number(query.get("cursor") || 0), Number(query.get("limit") || 50))); }
  catch (error) { return Response.json({ error: error instanceof Error ? error.message : "Tasks unavailable" }, { status: 503 }); }
}
