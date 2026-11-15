"use client";

import { SessionProvider, useSession } from "next-auth/react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Session } from "next-auth";
import { Workspace } from "./workspace";
import { siteProviderNames } from "@/lib/login-policy";
import type { ConnectionProvider } from "@/lib/connection-providers";

type Props = { session: Session; initialProvider?: ConnectionProvider; connectionResult?: string };

function isSiteSession(value: unknown): value is Session {
  if (!value || typeof value !== "object" || !("user" in value)
    || !("expires" in value) || typeof value.expires !== "string"
    || !Number.isFinite(Date.parse(value.expires))
    || !("sessionId" in value) || typeof value.sessionId !== "string" || !value.sessionId
    || !("loginProvider" in value) || typeof value.loginProvider !== "string"
    || !Object.hasOwn(siteProviderNames, value.loginProvider)) return false;
  const user = value.user;
  if (!user || typeof user !== "object" || !("id" in user)) return false;
  return typeof user.id === "string" && Boolean(user.id)
    && (!("name" in user) || user.name === null || typeof user.name === "string");
}

function SessionWorkspace({ initialSession, initialProvider, connectionResult }: Omit<Props, "session"> & { initialSession: Session }) {
  const { data: authSession, status } = useSession();
  const [session, setSession] = useState(initialSession);
  const currentSession = useRef(initialSession);
  const verification = useRef(0);
  const leaving = useRef(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const verifySession = useCallback(async (protect = true) => {
    if (leaving.current) return false;
    const version = ++verification.current;
    if (protect) setChecking(true);
    try {
      const response = await fetch("/api/auth/session", {
        cache: "no-store", signal: AbortSignal.timeout(10000),
      });
      if (!response.ok) throw new Error("account_store_unavailable");
      const current: unknown = await response.json();
      if (version !== verification.current) return false;
      if (current === null) {
        setChecking(true); window.location.replace("/login?error=SessionExpired");
        return false;
      }
      if (!isSiteSession(current)) throw new Error("invalid_session_response");
      currentSession.current = current;
      setSession(current);
      setError(""); setChecking(false);
      return true;
    } catch {
      if (version !== verification.current) return false;
      setError("계정 저장소에 접근할 수 없습니다. 새로고침하거나 잠시 후 다시 시도해주세요.");
      setChecking(true);
      return false;
    }
  }, []);
  useEffect(() => {
    const channel = new BroadcastChannel("wagl-site-session");
    channel.onmessage = (event) => {
      if (event.data === "signed-out") {
        leaving.current = true; verification.current++;
        setChecking(true); window.location.replace("/login");
      } else {
        void verifySession();
      }
    };
    function restored(event: PageTransitionEvent) {
      if (event.persisted) {
        void verifySession();
      }
    }
    function focused() { if (!document.hidden) void verifySession(false); }
    const poll = window.setInterval(() => { void verifySession(false); }, 60000);
    window.addEventListener("pageshow", restored);
    window.addEventListener("focus", focused);
    return () => {
      channel.close(); window.clearInterval(poll);
      verification.current += 1;
      window.removeEventListener("pageshow", restored); window.removeEventListener("focus", focused);
    };
  }, [verifySession]);
  useEffect(() => {
    if (status === "unauthenticated"
      || (status === "authenticated" && authSession?.sessionId !== currentSession.current.sessionId)) {
      void verifySession();
    }
  }, [authSession?.sessionId, status, verifySession]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void verifySession();
    },
      Math.max(0, Math.min(Date.parse(session.expires) - Date.now(), 2147483647)));
    return () => window.clearTimeout(timer);
  }, [session.expires, verifySession]);
  if (checking || !session?.user?.id || !session.sessionId || !session.loginProvider) {
    return <main className="public-site" role="status"><p role={error ? "alert" : undefined}>
      {error || "사이트 로그인 상태를 확인하고 있습니다."}
    </p></main>;
  }
  const sessionId = session.sessionId;
  return <>{error && <p role="alert" className="alert">{error}</p>}<Workspace key={`${session.user.id}:${session.sessionId}`}
    user={{ id: session.user.id, name: session.user.name || "사용자" }}
    authConfigured sessionId={sessionId} loginProvider={siteProviderNames[session.loginProvider]}
    initialProvider={initialProvider} connectionResult={connectionResult} onLogout={async () => {
      leaving.current = true; verification.current++;
      setChecking(true);
      try {
        const response = await fetch("/api/account/logout", {
          method: "POST", cache: "no-store", headers: { "X-Wagl-Session": sessionId },
        });
        if (!response.ok) throw new Error("logout_failed");
        const channel = new BroadcastChannel("wagl-site-session");
        channel.postMessage("signed-out"); channel.close();
        window.location.replace("/login");
      } catch {
        leaving.current = false;
        if (await verifySession()) setError("로그아웃을 완료하지 못했습니다. 다시 시도해주세요.");
      }
    }} /></>;
}

export function PersonalWorkspace({ session, ...props }: Props) {
  return <SessionProvider session={session} refetchInterval={0} refetchOnWindowFocus={false}>
    <SessionWorkspace initialSession={session} {...props} />
  </SessionProvider>;
}
