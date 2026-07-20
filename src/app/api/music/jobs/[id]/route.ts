import { deleteMusicJob, getMusicJob } from "@/lib/music";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }): Promise<Response> {
  try {
    return Response.json(await getMusicJob((await params).id));
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Music job was not found." }, { status: 404 });
  }
}

export async function DELETE(_request: Request, { params }: { params: Promise<{ id: string }> }): Promise<Response> {
  try {
    return Response.json(await deleteMusicJob((await params).id));
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Music job could not be deleted." }, { status: 409 });
  }
}
