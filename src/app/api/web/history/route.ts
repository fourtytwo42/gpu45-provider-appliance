import { researchHistory } from "@/lib/research";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const kind = url.searchParams.get("kind") ?? "search";
  const limit = Number(url.searchParams.get("limit") ?? 30);
  try {
    return Response.json(await researchHistory(kind, limit));
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "History failed" }, { status: 500 });
  }
}
