import { siteSession, authConfigured } from "@/auth";
import { policyToken } from "@/lib/policy-token";
import { boundedBody } from "@/lib/request-body";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const allowedRoutes: [RegExp, string[]][] = [
  [/^(catalog|endpoints|activity)$/, ["GET"]],
  [/^connection-options$/, ["GET"]],
  [/^credentials$/, ["GET", "POST"]],
  [/^credentials\/[a-f0-9-]{36}$/, ["PATCH", "DELETE"]],
  [/^credentials\/[a-f0-9-]{36}\/verify$/, ["POST"]],
  [/^conversations$/, ["GET"]],
  [/^conversations\/[a-f0-9-]{36}$/, ["GET", "DELETE"]],
  [/^(chat|cancel)$/, ["POST"]],
];

async function proxy(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const route = path.join("/");
  if (!allowedRoutes.some(([pattern, methods]) => pattern.test(route) && methods.includes(request.method))) {
    return Response.json({ detail: "Not found" }, { status: 404 });
  }
  if (!authConfigured) return Response.json({ detail: "Authentication not configured" }, { status: 401 });
  let session;
  try { session = await siteSession(); }
  catch {
    return Response.json({ detail: "account_store_unavailable" }, { status: 503 });
  }
  if (!session?.user?.id?.startsWith("user:") || !session.sessionId) {
    return Response.json({ detail: "Authentication required" }, { status: 401 });
  }
  if (request.headers.get("x-wagl-session") !== session.sessionId) {
    return Response.json({ detail: "Session changed" }, { status: 409 });
  }
  if (request.method !== "GET" && request.headers.get("origin") !== process.env.WAGL_PUBLIC_URL) {
    return Response.json({ detail: "Invalid origin" }, { status: 403 });
  }
  const secret = process.env.WAGL_INTERNAL_SECRET;
  if (!secret || secret.length < 32) {
    return Response.json({ detail: "Service not configured" }, { status: 503 });
  }
  let body: string | undefined;
  if (!["GET", "DELETE"].includes(request.method)) {
    try {
      body = await boundedBody(request, route === "chat" ? 6 * 1024 * 1024 : 32768);
    } catch {
      return Response.json({ detail: "Input too large" }, { status: 413 });
    }
  }
  const token = await policyToken(session.user.id, session.sessionId);
  const url = new URL(`/${route}`, process.env.WAGL_API_URL || "http://127.0.0.1:8000");
  if (route === "endpoints") url.searchParams.set("model", new URL(request.url).searchParams.get("model") || "");
  try {
    const upstream = await fetch(url, {
      method: request.method, body, cache: "no-store", redirect: "error",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(
        route === "chat" ? 80000 : route.endsWith("/verify") ? 50000 : 20000,
      )]),
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") || "application/json",
        "Cache-Control": "no-store", "X-Accel-Buffering": "no",
        ...(upstream.headers.has("retry-after") ? { "Retry-After": upstream.headers.get("retry-after")! } : {}),
      },
    });
  } catch {
    return Response.json({ detail: "Policy service unavailable" }, { status: 503 });
  }
}

export { proxy as GET, proxy as POST, proxy as PATCH, proxy as DELETE };