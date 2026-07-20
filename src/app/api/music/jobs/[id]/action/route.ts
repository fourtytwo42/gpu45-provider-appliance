import { musicJobAction } from "@/lib/music";

export const dynamic = "force-dynamic";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }): Promise<Response> {
  try {
    const body = await request.json() as { action?: "cancel" | "retry" };
    if (body.action !== "cancel" && body.action !== "retry") return Response.json({ error: "Action must be cancel or retry." }, { status: 400 });
    return Response.json(await musicJobAction((await params).id, body.action));
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Music action failed." }, { status: 409 });
  }
}
