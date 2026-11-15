import { siteSession, signOut } from "@/auth";
import { revokeAccountSession } from "@/lib/account-bridge";

export async function POST(request: Request) {
  if (request.headers.get("origin") !== process.env.WAGL_PUBLIC_URL) {
    return Response.json({ detail: "Invalid origin" }, { status: 403 });
  }
  try {
    const session = await siteSession();
    if (session?.user?.id && session.sessionId) {
      if (request.headers.get("x-wagl-session") !== session.sessionId) {
        return Response.json({ detail: "Session changed" }, { status: 409 });
      }
      await revokeAccountSession(session.user.id, session.sessionId);
    }
    await signOut({ redirect: false });
    return Response.json({ status: "signed_out" }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    console.error("Site logout failed");
    return Response.json({ detail: "logout_failed" }, { status: 503 });
  }
}
