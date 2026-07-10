import { NextRequest, NextResponse } from "next/server";
import { adminSessionCookie, verifyAdminSessionToken } from "@/lib/auth-token";

const publicPaths = new Set(["/login", "/api/auth/login", "/api/health/summary", "/api/version"]);
const safeMethods = new Set(["GET", "HEAD", "OPTIONS"]);

function securityHeaders(response: NextResponse): NextResponse {
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("Referrer-Policy", "no-referrer");
  response.headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  return response;
}

function sameOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return false;
  try {
    const expectedHost = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
    return new URL(origin).host === expectedHost;
  } catch {
    return false;
  }
}

export function proxy(request: NextRequest): NextResponse {
  if (process.env.GPU45_E2E_AUTH_BYPASS === "true") return securityHeaders(NextResponse.next());
  const path = request.nextUrl.pathname;
  const session = verifyAdminSessionToken(request.cookies.get(adminSessionCookie)?.value);
  const isPublic = publicPaths.has(path);

  if (!safeMethods.has(request.method) && !sameOrigin(request)) {
    return securityHeaders(NextResponse.json({ error: "Cross-site request rejected." }, { status: 403 }));
  }
  if (path === "/login" && session) return securityHeaders(NextResponse.redirect(new URL("/", request.url)));
  if (!isPublic && !session) {
    if (path.startsWith("/api/")) return securityHeaders(NextResponse.json({ error: "Authentication required." }, { status: 401 }));
    const login = new URL("/login", request.url);
    login.searchParams.set("next", path);
    return securityHeaders(NextResponse.redirect(login));
  }
  return securityHeaders(NextResponse.next());
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
};
