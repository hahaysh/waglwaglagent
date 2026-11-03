import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: { baseURL: "http://127.0.0.1:3110", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 900 } } },
    { name: "mobile", use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
  webServer: {
    command: "npm run dev -- --hostname 127.0.0.1 --port 3110",
    url: "http://127.0.0.1:3110", reuseExistingServer: false,
    env: {
      AUTH_SECRET: "test-session-secret-only-not-for-production-0123456789",
      AUTH_GITHUB_ID: process.env.WAGL_TEST_AUTH_DISABLED ? "" : "test-oauth-client",
      AUTH_GITHUB_SECRET: process.env.WAGL_TEST_AUTH_DISABLED ? "" : "test-oauth-secret",
      AUTH_TRUST_HOST: "true",
      WAGL_PUBLIC_URL: "http://127.0.0.1:3110",
      WAGL_API_URL: "http://127.0.0.1:3199",
      WAGL_INTERNAL_SECRET: "test-internal-secret-only-not-for-production",
    },
  },
});