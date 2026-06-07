import { getToken } from "next-auth/jwt";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export async function middleware(req: NextRequest) {
  // Auth is only enforced when DASHBOARD_SECRET is configured.
  // This preserves zero-config local dev behaviour.
  if (!process.env.DASHBOARD_SECRET) {
    return NextResponse.next();
  }

  const secret = process.env.NEXTAUTH_SECRET || process.env.SECRET_KEY;
  const token = await getToken({ req, secret });

  const pathname = req.nextUrl.pathname;
  const isPublic =
    pathname.startsWith("/login") ||
    pathname.startsWith("/api/auth") ||
    pathname.startsWith("/_next") ||
    pathname === "/favicon.ico";

  if (!token && !isPublic) {
    const loginUrl = new URL("/login", req.url);
    loginUrl.searchParams.set("callbackUrl", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
