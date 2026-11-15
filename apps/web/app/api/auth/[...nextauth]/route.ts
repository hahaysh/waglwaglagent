import { handlers, siteSession } from "@/auth";
import type { NextRequest } from "next/server";

export async function GET(request: NextRequest) {
  if (new URL(request.url).pathname === "/api/auth/session") {
    try {
      return Response.json(await siteSession(), { headers: { "Cache-Control": "no-store" } });
    } catch {
      console.error("Site session storage unavailable");
      return Response.json({ detail: "account_store_unavailable" }, { status: 503 });
    }
  }
  return handlers.GET(request);
}

export async function POST(request: NextRequest) {
  if (new URL(request.url).pathname === "/api/auth/session") {
    if (request.headers.get("origin") !== process.env.WAGL_PUBLIC_URL) {
      return Response.json({ detail: "Invalid origin" }, { status: 403 });
    }
    return GET(request);
  }
  return handlers.POST(request);
}