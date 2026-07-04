import { getBenchmarkJob, startBenchmarkJob } from "@/lib/benchmarks";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const id = new URL(request.url).searchParams.get("id");
  if (!id) return Response.json({ error: "Benchmark job id is required" }, { status: 400 });
  const job = getBenchmarkJob(id);
  return job ? Response.json({ job }) : Response.json({ error: "Benchmark job not found" }, { status: 404 });
}

export async function POST(request: Request): Promise<Response> {
  try {
    return Response.json({ job: startBenchmarkJob(await request.json()) }, { status: 202 });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Benchmark failed" }, { status: 400 });
  }
}
