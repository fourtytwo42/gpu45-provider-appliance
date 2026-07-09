import { restoreStorage } from "@/lib/storage";
export async function POST(request: Request): Promise<Response> {
  try { const body = await request.json() as { operationId?: string }; return Response.json(await restoreStorage(body.operationId ?? "")); }
  catch (error) { return Response.json({ error: error instanceof Error ? error.message : "Restore failed." }, { status: 400 }); }
}
