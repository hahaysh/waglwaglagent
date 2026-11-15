import assert from "node:assert/strict";
import test from "node:test";
import { safeReturnPath, loginError } from "../lib/login-policy.ts";

test("Login return paths reject external, encoded, callback and traversal targets", () => {
  for (const path of [
    "https://evil.test", "//evil.test", "/%2fevil.test", "/\\evil.test",
    "/api/auth/callback/google?code=private", "/%61pi/auth/callback/google",
    "/%252f%252fevil.test", "/login?callbackUrl=//evil.test", "/../api/auth/callback/google",
  ]) assert.equal(safeReturnPath(path), "/");
  assert.equal(safeReturnPath("/?connect=copilot"), "/?connect=copilot");
});

test("Login errors are localized without reflecting provider error contents", () => {
  assert.match(loginError("SessionExpired"), /만료/);
  assert.match(loginError("Configuration"), /설정/);
  assert.ok(!loginError("private-upstream-detail").includes("private-upstream-detail"));
});
