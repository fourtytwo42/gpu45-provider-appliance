import { currentAdminSession } from "@/lib/admin-auth";

export async function GET(): Promise<Response> {
  const session = await currentAdminSession();
  return session ? Response.json({ authenticated: true, username: session.username }) : Response.json({ authenticated: false }, { status: 401 });
}
