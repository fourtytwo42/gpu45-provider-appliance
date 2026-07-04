import { getConfig } from "@/lib/config";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const kind = url.searchParams.get("kind");
  const id = url.searchParams.get("id");
  if ((kind !== "voices" && kind !== "models") || !id) {
    return Response.json({ error: "kind and id are required" }, { status: 400 });
  }

  const upstream = await fetch(`${getConfig().ttsUrl.replace(/\/$/, "")}/${kind}/${encodeURIComponent(id)}/sample`, {
    cache: "no-store",
  });
  if (!upstream.ok) {
    return Response.json({ error: await upstream.text() }, { status: upstream.status });
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "audio/mpeg",
      "Cache-Control": "no-store",
    },
  });
}
