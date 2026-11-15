import "next-auth";
import "next-auth/jwt";
import type { SiteProvider } from "../lib/account-bridge";

declare module "next-auth" {
  interface Session {
    sessionId?: string;
    loginProvider?: SiteProvider;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    sid?: string;
    loginProvider?: SiteProvider;
    accountVersion?: number;
    sessionExpires?: string;
  }
}
