import { performUnifiedJobAction } from "@/lib/jobs";
import type { UnifiedJobAction } from "@/lib/jobs";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: Request): Promise<Response> {
  try {
    const body = await request.json() as { id?: string; action?: UnifiedJobAction };
    if (!body.id || !body.action) return Response.json({ ok: false, message: "Job id and action are required." }, { status: 400 });
    const result = await performUnifiedJobAction(body.id, body.action);
    return Response.json(result, { status: result.ok ? 200 : 409 });
  } catch (error) {
    return Response.json({ ok: false, message: error instanceof Error ? error.message : "Job action failed." }, { status: 500 });
  }
}
