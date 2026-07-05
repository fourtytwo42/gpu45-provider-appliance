import { getOutputs } from "@/lib/outputs";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(): Promise<Response> {
  return Response.json(await getOutputs());
}
