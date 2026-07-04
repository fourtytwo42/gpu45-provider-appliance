import { createApiKey, deleteApiKey, getEndpointSettings, listApiKeys, setAllowAnonymous, setApiKeySuspended } from "@/lib/api-keys";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return Response.json({ keys: await listApiKeys(), settings: await getEndpointSettings() });
}

export async function POST(request: Request): Promise<Response> {
  try {
    return Response.json(await createApiKey(await request.json()), { status: 201 });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to create key" }, { status: 400 });
  }
}

export async function PATCH(request: Request): Promise<Response> {
  try {
    const body = await request.json() as { id?: string; suspended?: boolean; allowAnonymous?: boolean };
    if (typeof body.allowAnonymous === "boolean") await setAllowAnonymous(body.allowAnonymous);
    else if (body.id && typeof body.suspended === "boolean") await setApiKeySuspended(body.id, body.suspended);
    else return Response.json({ error: "Invalid key update" }, { status: 400 });
    return Response.json({ ok: true });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to update key" }, { status: 400 });
  }
}

export async function DELETE(request: Request): Promise<Response> {
  try {
    const id = new URL(request.url).searchParams.get("id");
    if (!id) return Response.json({ error: "Key id is required" }, { status: 400 });
    await deleteApiKey(id);
    return Response.json({ deleted: 1 });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to delete key" }, { status: 400 });
  }
}
