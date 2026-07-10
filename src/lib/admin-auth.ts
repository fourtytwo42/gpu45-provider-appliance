import { promisify } from "node:util";
import { randomBytes, randomUUID, scrypt as scryptCallback, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";
import { prisma } from "./db";
import { adminSessionCookie, signAdminSession, verifyAdminSessionToken } from "./auth-token";

const scrypt = promisify(scryptCallback);
const sessionLifetimeMs = 12 * 60 * 60 * 1000;
const lockDurationMs = 15 * 60 * 1000;
const maxFailedAttempts = 5;

export async function hashAdminPassword(password: string, salt = randomBytes(16).toString("hex")): Promise<{ hash: string; salt: string }> {
  if (password.length < 8) throw new Error("Admin password must contain at least 8 characters.");
  const derived = await scrypt(password, salt, 64) as Buffer;
  return { hash: derived.toString("hex"), salt };
}

export async function verifyAdminPassword(password: string, expectedHash: string, salt: string): Promise<boolean> {
  const derived = await scrypt(password, salt, 64) as Buffer;
  const expected = Buffer.from(expectedHash, "hex");
  return expected.length === derived.length && timingSafeEqual(expected, derived);
}

export async function upsertAdminUser(username: string, password: string): Promise<void> {
  const normalizedUsername = username.trim().toLowerCase();
  if (!normalizedUsername) throw new Error("Admin username is required.");
  const credentials = await hashAdminPassword(password);
  const user = await prisma.adminUser.upsert({
    where: { username: normalizedUsername },
    create: { username: normalizedUsername, passwordHash: credentials.hash, passwordSalt: credentials.salt },
    update: { passwordHash: credentials.hash, passwordSalt: credentials.salt, failedAttempts: 0, lockedUntil: null },
  });
  await prisma.adminSession.deleteMany({ where: { userId: user.id } });
  await prisma.auditLog.create({ data: { action: "admin.provision", subject: user.id, details: normalizedUsername } });
}

export async function authenticateAdmin(input: { username: string; password: string; userAgent?: string | null; ipAddress?: string | null }): Promise<{ token: string; expiresAt: Date; username: string }> {
  const username = input.username.trim().toLowerCase();
  const user = await prisma.adminUser.findUnique({ where: { username } });
  if (!user || (user.lockedUntil && user.lockedUntil > new Date())) throw new Error("Invalid username or password.");

  const valid = await verifyAdminPassword(input.password, user.passwordHash, user.passwordSalt);
  if (!valid) {
    const attempts = user.failedAttempts + 1;
    await prisma.adminUser.update({
      where: { id: user.id },
      data: { failedAttempts: attempts >= maxFailedAttempts ? 0 : attempts, lockedUntil: attempts >= maxFailedAttempts ? new Date(Date.now() + lockDurationMs) : null },
    });
    await prisma.auditLog.create({ data: { action: "admin.login_failed", subject: user.id, details: input.ipAddress ?? "unknown" } });
    throw new Error("Invalid username or password.");
  }

  await prisma.adminUser.update({ where: { id: user.id }, data: { failedAttempts: 0, lockedUntil: null } });
  const expiresAt = new Date(Date.now() + sessionLifetimeMs);
  const sessionId = randomUUID();
  await prisma.adminSession.create({
    data: { id: sessionId, userId: user.id, csrfToken: randomBytes(24).toString("base64url"), expiresAt, userAgent: input.userAgent ?? null, ipAddress: input.ipAddress ?? null },
  });
  await prisma.auditLog.create({ data: { action: "admin.login", subject: user.id, details: input.ipAddress ?? "unknown" } });
  return { token: signAdminSession({ sessionId, userId: user.id, username: user.username, expiresAt: expiresAt.getTime() }), expiresAt, username: user.username };
}

export async function currentAdminSession(): Promise<{ username: string; sessionId: string } | null> {
  const store = await cookies();
  const payload = verifyAdminSessionToken(store.get(adminSessionCookie)?.value);
  if (!payload) return null;
  const session = await prisma.adminSession.findUnique({ where: { id: payload.sessionId } });
  if (!session || session.revokedAt || session.expiresAt <= new Date() || session.userId !== payload.userId) return null;
  return { username: payload.username, sessionId: payload.sessionId };
}

export async function revokeAdminSession(token: string | undefined): Promise<void> {
  const payload = verifyAdminSessionToken(token);
  if (!payload) return;
  await prisma.adminSession.updateMany({ where: { id: payload.sessionId }, data: { revokedAt: new Date() } });
  await prisma.auditLog.create({ data: { action: "admin.logout", subject: payload.userId, details: payload.sessionId } });
}
