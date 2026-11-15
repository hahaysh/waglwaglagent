import assert from "node:assert/strict";
import test from "node:test";
import { generateKeyPair, SignJWT } from "jose";
import { verifySiteIdentityToken } from "../lib/identity-token.ts";

test("Site OIDC tokens require valid signature, exact audience, issuer, subject and expiry", async () => {
  const keys = await generateKeyPair("RS256");
  const impostor = await generateKeyPair("RS256");
  const claims = {
    sub: "verified-subject", aud: "our-client", iss: "https://accounts.google.com",
    iat: Math.floor(Date.now() / 1000), exp: Math.floor(Date.now() / 1000) + 60,
  };
  const sign = (override = {}, key = keys.privateKey) => new SignJWT({ ...claims, ...override })
    .setProtectedHeader({ alg: "RS256" }).sign(key);
  await verifySiteIdentityToken(await sign(), "google", "our-client", "verified-subject", keys.publicKey);
  for (const override of [
    { iss: "https://evil.test" }, { aud: "different-client" }, { sub: "other-user" }, { exp: 0 },
  ]) await assert.rejects(verifySiteIdentityToken(
    await sign(override), "google", "our-client", "verified-subject", keys.publicKey,
  ));
  await assert.rejects(verifySiteIdentityToken(
    await sign({}, impostor.privateKey), "google", "our-client", "verified-subject", keys.publicKey,
  ));
});

test("Microsoft company and school tenants are not accepted as personal accounts", async () => {
  const keys = await generateKeyPair("RS256");
  const claims = {
    sub: "subject", aud: "client",
    iss: "https://login.microsoftonline.com/9188040d-6c67-4c5b-b112-36a304b66dad/v2.0",
    iat: Math.floor(Date.now() / 1000), exp: Math.floor(Date.now() / 1000) + 60,
  };
  const sign = (tid) => new SignJWT({ ...claims, tid }).setProtectedHeader({ alg: "RS256" }).sign(keys.privateKey);
  await verifySiteIdentityToken(await sign("9188040d-6c67-4c5b-b112-36a304b66dad"),
    "microsoft-entra-id", "client", "subject", keys.publicKey);
  await assert.rejects(verifySiteIdentityToken(await sign("company-tenant"),
    "microsoft-entra-id", "client", "subject", keys.publicKey));
});
