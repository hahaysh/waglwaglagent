import { createHash, randomBytes } from "node:crypto";
import { siteSession, authConfigured } from "@/auth";
import { policyToken } from "@/lib/policy-token";
import { NextResponse } from "next/server";
import { cookies } from "next/headers";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function cookieName(state: string) {
  return `wagl.copilot.${createHash("sha256").update(state).digest("hex").slice(0, 24)}`;
}

function publicOrigin(): string {
  const value = process.env.WAGL_PUBLIC_URL;
  if (!value) throw new Error("Service not configured");
  return new URL(value).origin;
}

async function post(owner: string, sid: string, path: string, body: object) {
  return fetch(new URL(path, process.env.WAGL_API_URL || "http://127.0.0.1:8000"), {
    method: "POST", cache: "no-store", redirect: "error", signal: AbortSignal.timeout(40000),
    headers: { Authorization: `Bearer ${await policyToken(owner, sid)}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function POST(request: Request, context: { params: Promise<{ action: string }> }) {
  if ((await context.params).action !== "start") return new Response(null, { status: 404 });
  if (!authConfigured) return Response.json({ detail: "Authentication not configured" }, { status: 401 });
  let session;
  try { session = await siteSession(); }
  catch { return Response.json({ detail: "account_store_unavailable" }, { status: 503 }); }
  if (!session?.user?.id || !session.sessionId) return Response.json({ detail: "Authentication required" }, { status: 401 });
  if (request.headers.get("origin") !== publicOrigin()) {
    return Response.json({ detail: "Invalid origin" }, { status: 403 });
  }
  if (request.headers.get("x-wagl-session") !== session.sessionId) {
    return Response.json({ detail: "Session changed" }, { status: 409 });
  }
  let approved: boolean;
  try {
    const body = await request.json();
    if (typeof body?.approved !== "boolean") throw new Error("Invalid input");
    approved = body.approved;
  } catch {
    return Response.json({ detail: "Invalid input" }, { status: 422 });
  }
  try {
    const binding = randomBytes(32).toString("base64url");
    const response = await post(session.user.id, session.sessionId, "/connections/copilot/start", { binding, approved });
    if (!response.ok) return Response.json({ detail: response.status === 503 ? "copilot_not_configured" : "oauth_start_failed" }, { status: response.status });
    const payload = await response.json();
    const url = new URL(payload.authorization_url);
    const state = url.searchParams.get("state");
    if (url.origin !== "https://github.com" || url.pathname !== "/login/oauth/authorize" || !state) {
      return Response.json({ detail: "oauth_start_failed" }, { status: 502 });
    }
    const result = NextResponse.json({ authorization_url: url.toString() }, { headers: { "Cache-Control": "no-store" } });
    result.cookies.set(cookieName(state), binding, {
      httpOnly: true, sameSite: "lax", secure: publicOrigin().startsWith("https:"),
      path: "/api/connections/copilot", maxAge: 600,
    });
    return result;
  } catch {
    return Response.json({ detail: "Policy service unavailable" }, { status: 503 });
  }
}

export async function GET(request: Request, context: { params: Promise<{ action: string }> }) {
  if ((await context.params).action !== "callback") return new Response(null, { status: 404 });
  const url = new URL(request.url);
  const state = url.searchParams.get("state") || "";
  const validState = /^[A-Za-z0-9_-]{32,128}$/.test(state);
  const cookie = validState ? cookieName(state) : null;
  const binding = cookie ? (await cookies()).get(cookie)?.value : null;
  let outcome = "oauth_invalid_state";
  let session;
  try { session = authConfigured ? await siteSession() : null; }
  catch { outcome = "service_unavailable"; }
  if (session?.user?.id && session.sessionId && binding && validState) {
    try {
      const response = await post(session.user.id, session.sessionId, "/connections/copilot/complete", {
        state, binding, code: url.searchParams.get("code"), error: url.searchParams.get("error"),
      });
      if (response.ok) outcome = "saved";
      else {
        const error = await response.json();
        outcome = ["oauth_cancelled", "oauth_invalid_state", "oauth_exchange_failed", "copilot_not_configured", "Credential limit reached", "oauth_connection_conflict"].includes(error.detail)
          ? error.detail : "oauth_exchange_failed";
      }
    } catch { outcome = "service_unavailable"; }
  }
  const target = new URL("/", publicOrigin());
  target.searchParams.set("connection", outcome);
  const result = NextResponse.redirect(target, { status: 303 });
  result.headers.set("Cache-Control", "no-store");
  result.headers.set("Referrer-Policy", "no-referrer");
  if (cookie) result.cookies.set(cookie, "", { path: "/api/connections/copilot", maxAge: 0 });
  return result;
}
