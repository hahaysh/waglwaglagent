import NextAuth from "next-auth";
import GitHub from "next-auth/providers/github";
import Google from "next-auth/providers/google";
import MicrosoftEntraID from "next-auth/providers/microsoft-entra-id";
import { verifySiteIdentityToken } from "@/lib/identity-token";
import {
  createAccountSession, isSiteProvider, microsoftIssuer, readAccountSession,
  revokeAccountSession,
} from "@/lib/account-bridge";
import { safeReturnPath, siteProviderNames } from "@/lib/login-policy";

const providerSettings = [
  { id: "microsoft-entra-id", clientId: process.env.AUTH_MICROSOFT_ENTRA_ID_ID,
    clientSecret: process.env.AUTH_MICROSOFT_ENTRA_ID_SECRET },
  { id: "google", clientId: process.env.AUTH_GOOGLE_ID, clientSecret: process.env.AUTH_GOOGLE_SECRET },
  { id: "github", clientId: process.env.AUTH_GITHUB_ID, clientSecret: process.env.AUTH_GITHUB_SECRET },
] as const;
export const loginProviders = providerSettings.map((provider) => ({
  id: provider.id, name: siteProviderNames[provider.id],
  available: Boolean(provider.clientId && provider.clientSecret && process.env.AUTH_SECRET),
  incomplete: Boolean(provider.clientId) !== Boolean(provider.clientSecret),
}));
export const authConfigured = loginProviders.some((provider) => provider.available);

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: providerSettings.filter((provider) => provider.clientId && provider.clientSecret).map((provider) => {
    const credentials = { clientId: provider.clientId, clientSecret: provider.clientSecret };
    if (provider.id === "github") return GitHub({
      ...credentials, authorization: { params: { scope: "read:user" } }, checks: ["state", "pkce"],
      profile(profile) { return { id: String(profile.id), name: profile.name || profile.login }; },
    });
    if (provider.id === "google") return Google({
      ...credentials, checks: ["state", "pkce", "nonce"],
      authorization: { params: { scope: "openid profile email" } },
      profile(profile) { return { id: profile.sub, name: profile.name || "Google 사용자" }; },
    });
    return MicrosoftEntraID({
      ...credentials, issuer: microsoftIssuer, checks: ["state", "pkce", "nonce"],
      authorization: { url: "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize",
        params: { scope: "openid profile email" } },
      profile(profile) { return { id: profile.sub, name: profile.name || "Microsoft 사용자" }; },
    });
  }),
  session: { strategy: "jwt", maxAge: 86400 },
  pages: { signIn: "/login", error: "/login" },
  callbacks: {
    async jwt({ token, account, profile }) {
      if (account) {
        if (!isSiteProvider(account.provider)) throw new Error("Unsupported login provider");
        if (account.provider !== "github") {
          if (!account.id_token) throw new Error("Missing identity token");
          const clientId = providerSettings.find((provider) => provider.id === account.provider)?.clientId;
          if (!clientId) throw new Error("Login provider not configured");
          await verifySiteIdentityToken(
            account.id_token, account.provider, clientId, account.providerAccountId,
          );
        } else if (!profile || String(profile.id) !== account.providerAccountId) {
          throw new Error("Invalid GitHub identity");
        }
        const resolved = await createAccountSession(
          account.provider, account.providerAccountId, (token.name || "사용자").slice(0, 200),
        );
        return { sub: `user:${resolved.user_id}`, sid: resolved.session_id,
          loginProvider: resolved.provider, name: resolved.name, accountVersion: 1,
          sessionExpires: resolved.expires_at };
      }
      if (token.accountVersion !== 1 || !token.sub?.startsWith("user:") || !token.sid) return null;
      return token;
    },
    session({ session, token }) {
      if (session.user && token.accountVersion === 1 && token.sub?.startsWith("user:") && token.sid) {
        session.user.id = token.sub;
        session.user.name = token.name || "사용자";
        session.sessionId = token.sid;
        session.loginProvider = token.loginProvider;
      }
      return { ...session, expires: token.sessionExpires || String(session.expires) };
    },
    redirect({ url, baseUrl }) {
      const path = url.startsWith(baseUrl + "/") ? url.slice(baseUrl.length) : url;
      return new URL(safeReturnPath(path), baseUrl).toString();
    },
  },
  events: {
    async signOut(message) {
      if ("token" in message && message.token?.sub && message.token.sid) {
        await revokeAccountSession(message.token.sub, message.token.sid);
      }
    },
  },
});

export async function siteSession() {
  const session = await auth();
  if (!session?.user?.id || !session.sessionId) return null;
  const account = await readAccountSession(session.user.id, session.sessionId);
  if (!account) return null;
  return { ...session, expires: account.expires_at,
    user: { ...session.user, name: account.name }, loginProvider: account.provider };
}