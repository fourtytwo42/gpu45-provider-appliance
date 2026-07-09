import { getBackupStatus, startBackupOperation } from "@/lib/backups";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return Response.json(await getBackupStatus(), { headers: { "Cache-Control": "no-store" } });
}

export async function POST(request: Request): Promise<Response> {
  const body = await request.json().catch(() => ({})) as { action?: string };
  if (body.action !== "run" && body.action !== "verify") {
    return Response.json({ error: "Action must be run or verify." }, { status: 400 });
  }
  await startBackupOperation(body.action === "run" ? "backup" : "verify");
  return Response.json({ ok: true, message: `${body.action} started.` }, { status: 202 });
}
