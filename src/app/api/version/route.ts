import { getApplianceVersion } from "@/lib/version";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(): Promise<Response> {
  return Response.json(getApplianceVersion(), {
    headers: { "Cache-Control": "no-store" },
  });
}
