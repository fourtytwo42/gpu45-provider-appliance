import { cookies } from "next/headers";
import { revokeAdminSession } from "@/lib/admin-auth";
import { adminSessionCookie } from "@/lib/auth-token";

export async function POST(): Promise<Response> {
  const store = await cookies();
  const token = store.get(adminSessionCookie)?.value;
  await revokeAdminSession(token);
  store.delete(adminSessionCookie);
  return Response.json({ ok: true });
}
