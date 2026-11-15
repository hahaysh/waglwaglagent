import { createRemoteJWKSet, jwtVerify, type JWTVerifyGetKey } from "jose";

export const microsoftIssuer = "https://login.microsoftonline.com/9188040d-6c67-4c5b-b112-36a304b66dad/v2.0";
const googleKeys = createRemoteJWKSet(new URL("https://www.googleapis.com/oauth2/v3/certs"));
const microsoftKeys = createRemoteJWKSet(new URL("https://login.microsoftonline.com/consumers/discovery/v2.0/keys"));

export async function verifySiteIdentityToken(
  token: string,
  provider: "google" | "microsoft-entra-id",
  clientId: string,
  expectedSubject: string,
  verificationKey?: CryptoKey | JWTVerifyGetKey,
) {
  const { payload } = await jwtVerify(token, verificationKey
    || (provider === "google" ? googleKeys : microsoftKeys), {
    issuer: provider === "google" ? "https://accounts.google.com" : microsoftIssuer,
    audience: clientId, algorithms: ["RS256"], requiredClaims: ["sub", "exp", "iat"],
  });
  if (payload.sub !== expectedSubject
    || (provider === "microsoft-entra-id"
      && payload.tid !== "9188040d-6c67-4c5b-b112-36a304b66dad")) {
    throw new Error("Invalid identity token");
  }
}
