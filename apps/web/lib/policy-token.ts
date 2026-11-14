import "server-only";
import { SignJWT } from "jose";

export async function policyToken(owner: string): Promise<string> {
  const secret = process.env.WAGL_INTERNAL_SECRET;
  if (!secret || secret.length < 32) throw new Error("Service not configured");
  return new SignJWT({}).setProtectedHeader({ alg: "HS256" })
    .setSubject(owner).setIssuer("wagl-web").setAudience("wagl-api")
    .setIssuedAt().setExpirationTime("60s")
    .sign(new TextEncoder().encode(secret));
}
