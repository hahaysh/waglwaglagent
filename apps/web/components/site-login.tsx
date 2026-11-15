"use client";

import { useState } from "react";
import { signIn } from "next-auth/react";
import { safeReturnPath } from "@/lib/login-policy";

function ProviderMark({ id }: { id: string }) {
  if (id === "microsoft-entra-id") return <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
    <rect x="2" y="2" width="9.5" height="9.5" fill="#F25022" /><rect x="12.5" y="2" width="9.5" height="9.5" fill="#7FBA00" />
    <rect x="2" y="12.5" width="9.5" height="9.5" fill="#00A4EF" /><rect x="12.5" y="12.5" width="9.5" height="9.5" fill="#FFB900" />
  </svg>;
  if (id === "google") return <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
    <path fill="#4285F4" d="M23.52 12.27c0-.85-.08-1.67-.22-2.45H12v4.64h6.46a5.52 5.52 0 0 1-2.4 3.62v3h3.88c2.27-2.09 3.58-5.17 3.58-8.81z" />
    <path fill="#34A853" d="M12 24c3.24 0 5.96-1.07 7.94-2.91l-3.88-3A7.2 7.2 0 0 1 5.34 14.3H1.34v3.1A12 12 0 0 0 12 24z" />
    <path fill="#FBBC05" d="M5.34 14.3a7.2 7.2 0 0 1 0-4.6V6.6H1.34a12 12 0 0 0 0 10.8l4-3.1z" />
    <path fill="#EA4335" d="M12 4.75c1.76 0 3.34.61 4.58 1.8l3.43-3.43A11.5 11.5 0 0 0 12 0 12 12 0 0 0 1.34 6.6l4 3.1A7.15 7.15 0 0 1 12 4.75z" />
  </svg>;
  return <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false" fill="currentColor">
    <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
  </svg>;
}

export function SiteLogin({ providers, returnTo = "/" }: {
  providers: { id: string; name: string; available: boolean; incomplete: boolean }[];
  returnTo?: string;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return <section aria-label="사이트 로그인" className="site-login">
    {error && <p className="login-alert" role="alert">{error}</p>}
    {providers.map((provider) => <div key={provider.id} className="site-login-row">
      <button className={`login-provider ${provider.id}`} disabled={!provider.available || busy} onClick={async () => {
        setBusy(true); setError("");
        try { await signIn(provider.id, { redirectTo: safeReturnPath(returnTo) }); }
        catch { setError("로그인을 시작하지 못했습니다. 다시 시도해주세요."); setBusy(false); }
      }}><ProviderMark id={provider.id} />{provider.id === "microsoft-entra-id" ? "Microsoft 개인 계정으로 로그인" : `${provider.name}로 로그인`}</button>
      {!provider.available && <small>{provider.incomplete ? "로그인 설정 미완료 · 운영자 확인 필요" : "운영자 설정 대기"}</small>}
    </div>)}
  </section>;
}
