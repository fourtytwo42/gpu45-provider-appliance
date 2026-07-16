import { listAgenticSuites } from "@/lib/agentic-benchmarks";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  try { return Response.json({ suites: await listAgenticSuites() }); }
  catch (error) { return Response.json({ error: error instanceof Error ? error.message : "Coordinator unavailable" }, { status: 503 }); }
}
