export const siteProviderNames = {
  "microsoft-entra-id": "Microsoft 개인 계정", google: "Google", github: "GitHub",
} as const;

export function safeReturnPath(value: unknown): string {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")
    || /[\\\r\n]/.test(value) || value.startsWith("/api/") || value.startsWith("/login")) return "/";
  try {
    const decoded = decodeURIComponent(value);
    if (decoded.startsWith("//") || /[\\\r\n]/.test(decoded) || decoded.startsWith("/api/")
      || decoded.startsWith("/login") || /%[0-9a-f]{2}/i.test(decoded)) return "/";
    const url = new URL(value, "https://wagl.invalid");
    if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/login")) return "/";
    return url.origin === "https://wagl.invalid" ? `${url.pathname}${url.search}` : "/";
  } catch {
    return "/";
  }
}

export function loginError(code: unknown): string | null {
  if (!code) return null;
  if (code === "AccessDenied") return "로그인 승인이 취소되었거나 이 계정을 지원하지 않습니다.";
  if (code === "SessionExpired") return "사이트 세션이 만료되었습니다. 다시 로그인해주세요.";
  if (code === "LogoutFailed") return "서버에서 로그아웃을 완료하지 못했습니다. 다시 시도해주세요.";
  if (code === "Configuration") return "로그인 서비스 설정 또는 계정 저장소에 문제가 있습니다. 운영자에게 문의해주세요.";
  return "로그인을 완료하지 못했습니다. 다시 시도하거나 운영자에게 문의해주세요.";
}
