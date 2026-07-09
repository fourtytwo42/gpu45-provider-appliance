import { cookies } from "next/headers";
import { authenticateAdmin } from "@/lib/admin-auth";
import { adminSessionCookie } from "@/lib/auth-token";

export async function POST(request: Request): Promise<Response> {
  try {
    const body = await request.json() as { username?: string; password?: string };
    if (!body.username || !body.password) return Response.json({ error: "Username and password are required." }, { status: 400 });
    const forwardedFor = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim();
    const session = await authenticateAdmin({ username: body.username, password: body.password, userAgent: request.headers.get("user-agent"), ipAddress: forwardedFor });
    const store = await cookies();
    const forwardedProto = request.headers.get("x-forwarded-proto")?.split(",")[0]?.trim();
    const secure = forwardedProto === "https" || new URL(request.url).protocol === "https:";
    store.set(adminSessionCookie, session.token, { httpOnly: true, sameSite: "strict", secure, path: "/", expires: session.expiresAt });
    return Response.json({ ok: true, username: session.username });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Login failed." }, { status: 401 });
  }
}
