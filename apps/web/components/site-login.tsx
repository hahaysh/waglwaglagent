"use client";

import { useState } from "react";
import { signIn } from "next-auth/react";
import { safeReturnPath } from "@/lib/login-policy";

export function SiteLogin({ providers, returnTo = "/" }: {
  providers: { id: string; name: string; available: boolean; incomplete: boolean }[];
  returnTo?: string;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return <section aria-label="사이트 로그인" className="site-login">
    {error && <p role="alert">{error}</p>}
    {providers.map((provider) => <div key={provider.id}>
      <button className="primary-button" disabled={!provider.available || busy} onClick={async () => {
        setBusy(true); setError("");
        try { await signIn(provider.id, { redirectTo: safeReturnPath(returnTo) }); }
        catch { setError("로그인을 시작하지 못했습니다. 다시 시도해주세요."); setBusy(false); }
      }}>{provider.id === "microsoft-entra-id" ? "Microsoft 개인 계정으로 로그인" : `${provider.name}로 로그인`}</button>
      {!provider.available && <small>{provider.incomplete ? "로그인 설정 미완료 · 운영자 확인 필요" : "운영자 설정 대기"}</small>}
    </div>)}
  </section>;
}
