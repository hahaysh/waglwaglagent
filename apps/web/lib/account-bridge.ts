import "server-only";
import { SignJWT } from "jose";
import { policyToken } from "./policy-token";
import { microsoftIssuer } from "./identity-token";
export { microsoftIssuer } from "./identity-token";

export type SiteProvider = "github" | "google" | "microsoft-entra-id";
export type AccountSession = {
  user_id: string; session_id: string; name: string; provider: SiteProvider; expires_at: string;
};
export const identityIssuers = {
  github: "https://github.com", google: "https://accounts.google.com",
  "microsoft-entra-id": microsoftIssuer,
} as const;

export function isSiteProvider(value: unknown): value is SiteProvider {
  return typeof value === "string" && Object.hasOwn(identityIssuers, value);
}

function isAccountSession(value: unknown): value is AccountSession {
  if (!value || typeof value !== "object") return false;
  return "user_id" in value && typeof value.user_id === "string"
    && "session_id" in value && typeof value.session_id === "string"
    && "name" in value && typeof value.name === "string"
    && "provider" in value && isSiteProvider(value.provider)
    && "expires_at" in value && typeof value.expires_at === "string";
}

async function accountRequest(path: string, token: string, method = "GET") {
  try {
    return await fetch(new URL(path, process.env.WAGL_API_URL || "http://127.0.0.1:8000"), {
      method, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(10000),
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      ...(method === "POST" ? { body: "{}" } : {}),
    });
  } catch {
    throw new Error("account_store_unavailable");
  }
}

export async function createAccountSession(provider: SiteProvider, subject: string, name: string) {
  const secret = process.env.WAGL_INTERNAL_SECRET;
  if (!secret || secret.length < 32) throw new Error("account_store_not_configured");
  const sid = crypto.randomUUID();
  const token = await new SignJWT({
    sid, provider, identity_issuer: identityIssuers[provider], name,
  }).setProtectedHeader({ alg: "HS256" }).setSubject(subject).setIssuer("wagl-web")
    .setAudience("wagl-login").setIssuedAt().setExpirationTime("60s")
    .sign(new TextEncoder().encode(secret));
  const response = await accountRequest("/auth/bootstrap", token, "POST");
  if (!response.ok) throw new Error("account_creation_failed");
  const account: unknown = await response.json();
  if (!isAccountSession(account) || account.provider !== provider || account.session_id !== sid) {
    throw new Error("invalid_account_response");
  }
  return account;
}

export async function readAccountSession(owner: string, sid: string) {
  const response = await accountRequest("/auth/session", await policyToken(owner, sid));
  if (response.status === 401) return null;
  if (!response.ok) throw new Error("account_store_unavailable");
  const account: unknown = await response.json();
  if (!isAccountSession(account) || `user:${account.user_id}` !== owner || account.session_id !== sid) {
    throw new Error("invalid_account_response");
  }
  return account;
}

export async function revokeAccountSession(owner: string, sid: string) {
  const response = await accountRequest("/auth/logout", await policyToken(owner, sid), "POST");
  if (!response.ok && response.status !== 401) throw new Error("logout_failed");
}
