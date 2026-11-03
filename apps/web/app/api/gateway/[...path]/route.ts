import { auth, authConfigured } from "@/auth";
import { SignJWT } from "jose";
import { boundedBody } from "@/lib/request-body";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const allowedRoutes: [RegExp, string[]][] = [
  [/^(catalog|endpoints|activity)$/, ["GET"]],
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
  const session = await auth();
  if (!session?.user?.id?.startsWith("github:")) {
    return Response.json({ detail: "Authentication required" }, { status: 401 });
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
      body = await boundedBody(request);
    } catch {
      return Response.json({ detail: "Invalid input" }, { status: 413 });
    }
  }
  const token = await new SignJWT({})
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(session.user.id).setIssuer("wagl-web").setAudience("wagl-api")
    .setIssuedAt().setExpirationTime("60s")
    .sign(new TextEncoder().encode(secret));
  const url = new URL(`/${route}`, process.env.WAGL_API_URL || "http://127.0.0.1:8000");
  if (route === "endpoints") url.searchParams.set("model", new URL(request.url).searchParams.get("model") || "");
  try {
    const upstream = await fetch(url, {
      method: request.method, body, cache: "no-store", redirect: "error",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(route === "chat" ? 80000 : 20000)]),
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