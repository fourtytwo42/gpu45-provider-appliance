import { searchWeb } from "@/lib/research";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const q = url.searchParams.get("q")?.trim() ?? "";
  const category = url.searchParams.get("category") === "jobs" ? "jobs" : "general";
  const limit = Number(url.searchParams.get("limit") ?? 10);
  if (!q) return Response.json({ error: "Query is required" }, { status: 400 });
  try {
    return Response.json(await searchWeb(q, category, limit));
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Search failed" }, { status: 502 });
  }
}
