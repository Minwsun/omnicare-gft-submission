import { NextRequest, NextResponse } from "next/server";

export function proxy(request: NextRequest) {
  const protectedPath = request.nextUrl.pathname.startsWith("/admin") || request.nextUrl.pathname.startsWith("/portal");
  if (protectedPath && !request.cookies.has("omnicare_session")) return NextResponse.redirect(new URL("/login", request.url));
  return NextResponse.next();
}

export const config = { matcher: ["/admin/:path*", "/portal/:path*"] };
