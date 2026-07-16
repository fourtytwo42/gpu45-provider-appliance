import { agenticDownload } from "@/lib/agentic-benchmarks";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ id: string; artifactId: string }> }): Promise<Response> {
  const { id, artifactId } = await context.params;
  return agenticDownload(`/v1/campaigns/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(artifactId)}`);
}
