import NextAuth from "next-auth";
import GitHub from "next-auth/providers/github";

export const authConfigured = Boolean(
  process.env.AUTH_GITHUB_ID && process.env.AUTH_GITHUB_SECRET && process.env.AUTH_SECRET,
);

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [GitHub({ authorization: { params: { scope: "read:user" } } })],
  session: { strategy: "jwt", maxAge: 86400 },
  callbacks: {
    jwt({ token, account }) {
      if (account?.provider === "github") token.sub = `github:${account.providerAccountId}`;
      return token;
    },
    session({ session, token }) {
      if (session.user && token.sub?.startsWith("github:")) session.user.id = token.sub;
      return session;
    },
  },
});