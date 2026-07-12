import { getUnifiedJob } from "@/lib/jobs";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await context.params;
  const job = await getUnifiedJob(decodeURIComponent(id));
  return job ? Response.json(job) : Response.json({ error: "Job not found." }, { status: 404 });
}
