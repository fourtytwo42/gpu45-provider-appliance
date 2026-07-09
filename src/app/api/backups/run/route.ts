import { startBackupOperation } from "@/lib/backups";

export async function POST(): Promise<Response> {
  await startBackupOperation("backup");
  return Response.json({ ok: true }, { status: 202 });
}
