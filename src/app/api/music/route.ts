import { getMusicSnapshot } from "@/lib/music";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return Response.json(await getMusicSnapshot());
}
