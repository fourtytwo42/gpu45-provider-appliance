import { listLatestAgenticResults } from "@/lib/agentic-benchmarks";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  try {
    return Response.json({ results: await listLatestAgenticResults() });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : "Benchmark results unavailable" },
      { status: 503 },
    );
  }
}
