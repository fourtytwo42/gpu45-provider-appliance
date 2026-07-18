import { getAgenticEfficiency } from "@/lib/agentic-benchmarks";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }): Promise<Response> {
  try {
    return Response.json(await getAgenticEfficiency((await context.params).id));
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : "Efficiency results unavailable" },
      { status: 503 },
    );
  }
}
