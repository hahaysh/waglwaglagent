import assert from "node:assert/strict";
import test from "node:test";
import { resolveVaultEnvironment } from "../lib/key-vault.ts";

test("Key Vault resolves server secrets without mutating environment on partial failure", async () => {
  const env = {
    AUTH_SECRET: "kv://auth",
    AUTH_GITHUB_ID: `kv://github-id/${"a".repeat(32)}`,
    AUTH_GITHUB_SECRET: "kv://github-secret",
    WAGL_INTERNAL_SECRET: "kv://internal",
  };
  const resolved = await resolveVaultEnvironment(env, {
    async getSecret(name) { return { value: `value-${name}` }; },
  });
  assert.equal(resolved.AUTH_SECRET, "value-auth");
  assert.equal(env.AUTH_SECRET, "kv://auth");
  await assert.rejects(resolveVaultEnvironment(env, {
    async getSecret() { throw new Error("private-upstream-detail"); },
  }), (error) => error.message.includes("Key Vault read failed")
    && !error.message.includes("private-upstream-detail"));
});

test("Plaintext or missing required secrets cannot bypass the vault", async () => {
  const client = { async getSecret() { throw new Error("Should not be reached"); } };
  await assert.rejects(resolveVaultEnvironment({ AUTH_SECRET: "plaintext" }, client), /reference/);
  await assert.rejects(resolveVaultEnvironment({}, client), /Missing required/);
});
