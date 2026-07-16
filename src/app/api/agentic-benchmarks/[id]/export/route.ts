import { agenticDownload } from "@/lib/agentic-benchmarks";

export const dynamic = "force-dynamic";

export async function GET(request: Request, context: { params: Promise<{ id: string }> }): Promise<Response> {
  const format = new URL(request.url).searchParams.get("format") ?? "json";
  return agenticDownload(`/v1/campaigns/${encodeURIComponent((await context.params).id)}/export?format=${encodeURIComponent(format)}`);
}
