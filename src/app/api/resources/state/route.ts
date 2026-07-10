import { getResourceState } from "@/lib/resource-manager";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  const state = await getResourceState();
  return Response.json(state, {
    status: 200,
    headers: { "Cache-Control": "no-store" },
  });
}
