import { searchHuggingFaceModels } from "@/lib/huggingface";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const query = new URL(request.url).searchParams.get("q")?.trim() ?? "";
  if (!query) return Response.json({ results: [] });
  try {
    return Response.json({ results: await searchHuggingFaceModels(query) });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Search failed" }, { status: 502 });
  }
}
