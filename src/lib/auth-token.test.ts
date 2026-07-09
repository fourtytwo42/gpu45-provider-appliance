import { afterEach, describe, expect, it } from "vitest";
import { signAdminSession, verifyAdminSessionToken } from "./auth-token";

const originalSecret = process.env.GPU45_SESSION_SECRET;

afterEach(() => { process.env.GPU45_SESSION_SECRET = originalSecret; });

describe("admin session token", () => {
  it("accepts a valid signed session and rejects tampering", () => {
    process.env.GPU45_SESSION_SECRET = "test-session-secret-with-at-least-32-characters";
    const token = signAdminSession({ sessionId: "s1", userId: "u1", username: "hendo420", expiresAt: Date.now() + 60_000 });
    expect(verifyAdminSessionToken(token)?.username).toBe("hendo420");
    expect(verifyAdminSessionToken(`${token}x`)).toBeNull();
  });

  it("rejects expired sessions", () => {
    process.env.GPU45_SESSION_SECRET = "test-session-secret-with-at-least-32-characters";
    const token = signAdminSession({ sessionId: "s1", userId: "u1", username: "hendo420", expiresAt: Date.now() - 1 });
    expect(verifyAdminSessionToken(token)).toBeNull();
  });
});
