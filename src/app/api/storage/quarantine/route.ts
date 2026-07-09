import { quarantineStorage } from "@/lib/storage";
export async function POST(request: Request): Promise<Response> {
  try { const body = await request.json() as { paths?: string[] }; return Response.json(await quarantineStorage(body.paths ?? [])); }
  catch (error) { return Response.json({ error: error instanceof Error ? error.message : "Quarantine failed." }, { status: 400 }); }
}
