import { createHmac, timingSafeEqual } from "node:crypto";

export const adminSessionCookie = "gpu45_admin_session";

export type AdminSessionPayload = {
  sessionId: string;
  userId: string;
  username: string;
  expiresAt: number;
};

function secret(): string {
  const value = process.env.GPU45_SESSION_SECRET?.trim();
  if (!value || value.length < 32) throw new Error("GPU45_SESSION_SECRET must contain at least 32 characters.");
  return value;
}

function signature(encodedPayload: string): string {
  return createHmac("sha256", secret()).update(encodedPayload).digest("base64url");
}

export function signAdminSession(payload: AdminSessionPayload): string {
  const encodedPayload = Buffer.from(JSON.stringify(payload), "utf8").toString("base64url");
  return `${encodedPayload}.${signature(encodedPayload)}`;
}

export function verifyAdminSessionToken(token: string | null | undefined): AdminSessionPayload | null {
  if (!token) return null;
  const [encodedPayload, suppliedSignature, extra] = token.split(".");
  if (!encodedPayload || !suppliedSignature || extra) return null;
  try {
    const expected = Buffer.from(signature(encodedPayload));
    const supplied = Buffer.from(suppliedSignature);
    if (expected.length !== supplied.length || !timingSafeEqual(expected, supplied)) return null;
    const payload = JSON.parse(Buffer.from(encodedPayload, "base64url").toString("utf8")) as AdminSessionPayload;
    if (!payload.sessionId || !payload.userId || !payload.username || payload.expiresAt <= Date.now()) return null;
    return payload;
  } catch {
    return null;
  }
}
