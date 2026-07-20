import { acceptLevoLicense } from "@/lib/music";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  try {
    const body = await request.json() as { licenseHash?: string };
    if (!body.licenseHash) return Response.json({ error: "licenseHash is required." }, { status: 400 });
    return Response.json(await acceptLevoLicense(body.licenseHash));
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "License acceptance failed." }, { status: 400 });
  }
}
