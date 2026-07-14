import { getConfig } from "@/lib/config";
import { managedServiceFetch } from "@/lib/managed-service";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  try {
    const form = await request.formData();
    const upstream = await managedServiceFetch(
      "video",
      `${getConfig().videoUrl.replace(/\/$/, "")}/jobs/i2v`,
      { method: "POST", body: form, cache: "no-store" },
      { wake: true, startupTimeoutMs: 120_000 },
    );
    const text = await upstream.text();
    return new Response(text, {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("Content-Type") ?? "application/json" },
    });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Image-to-video request failed" }, { status: 500 });
  }
}
