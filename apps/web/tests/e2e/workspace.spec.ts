import { test, expect, type Page } from "@playwright/test";
import { encode } from "next-auth/jwt";

const credential = {
  id: "11111111-1111-4111-8111-111111111111", provider: "openrouter",
  label: "테스트 개인 연결", model: "test/model:free", upstreams: ["test/bf16"],
  approved: true, priority: 0, status: "valid", checked_at: new Date().toISOString(),
  quota_snapshot: { source: "official", daily: { limit: 50, used: 23, remaining: 27 } },
};

async function navigate(page: Page, name: string) {
  const menu = page.getByRole("button", { name: "메뉴 열기" });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("navigation", { name: "주요 메뉴" }).getByRole("button", { name }).click();
}

async function login(page: Page) {
  const cookieName = "authjs.session-token";
  const value = await encode({
    token: { sub: "github:test-user", name: "테스트 사용자" },
    secret: "test-session-secret-only-not-for-production-0123456789",
    salt: cookieName, maxAge: 3600,
  });
  await page.context().addCookies([{
    name: cookieName, value, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax",
  }]);
}

test("logged-out workspace is responsive and rejects unauthenticated API requests", async ({ page, request }, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "새 대화", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "복잡한 개념을 쉽게 풀어줘" }).click();
  await expect(page.getByRole("textbox", { name: "메시지", exact: true })).toHaveValue("복잡한 개념을 쉽게 풀어줘");
  await expect(page.getByRole("button", { name: "메시지 전송" })).toBeDisabled();
  expect((await request.get("/api/gateway/credentials")).status()).toBe(401);
  expect((await request.get("/api/gateway/unapproved-route")).status()).toBe(404);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  if (info.project.name === "desktop") {
    expect(await page.locator(".provider-logo img").evaluateAll((images) => images.every((image) => (image as HTMLImageElement).naturalWidth > 0))).toBe(true);
  }
  await page.screenshot({ path: `test-results/${info.project.name}-workspace.png`, fullPage: true });
  await navigate(page, "내 연결");
  await expect(page.getByRole("heading", { name: "로그인 후 연결을 등록하세요" })).toBeVisible();
  const addConnection = page.getByRole("button", { name: "연결 추가", exact: true });
  await expect(addConnection).toBeEnabled();
  await addConnection.click();
  const help = page.getByRole("dialog");
  await expect(help).toBeVisible();
  if (process.env.WAGL_TEST_AUTH_DISABLED) {
    await expect(help.getByRole("heading", { name: "GitHub 로그인 설정이 필요합니다" })).toBeVisible();
    await expect(help).toContainText("AUTH_GITHUB_ID");
    await expect(help.getByRole("button", { name: "GitHub로 로그인" })).toHaveCount(0);
  } else {
    await expect(help.getByRole("button", { name: "GitHub로 로그인" })).toBeEnabled();
  }
  await expect(help.getByPlaceholder("API 키", { exact: true })).toHaveCount(0);
  await help.getByRole("button", { name: "닫기", exact: true }).click();
  await expect(help).not.toBeVisible();
  await navigate(page, "사용 기록");
  await expect(page.getByRole("heading", { name: "아직 사용 기록이 없습니다" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("authenticated personal key consent, streaming, masking and deletion", async ({ page }, info) => {
  await login(page);
  let keys = [credential];
  let chats: { id: string; title: string; created_at: string }[] = [];
  let submitted: Record<string, unknown> | null = null;
  const conversationId = "22222222-2222-4222-8222-222222222222";
  await page.route("**/api/gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/gateway/", "");
    if (path === "chat") {
      chats = [{ id: conversationId, title: "테스트 대화", created_at: new Date().toISOString() }];
      return route.fulfill({ contentType: "text/event-stream", body:
        `event: conversation\ndata: {"id":"${conversationId}"}\n\n`
        + `event: attempt\ndata: {"provider":"openrouter","model":"test/model:free","number":1}\n\n`
        + `event: delta\ndata: {"text":"테스트 응답입니다. ![외부 이미지](https://tracking.invalid/pixel.png)"}\n\n`
        + `event: done\ndata: {"usage":{"total_tokens":8}}\n\n`,
      });
    }
    if (path.startsWith("conversations/") && route.request().method() === "DELETE") {
      chats = []; return route.fulfill({ status: 204 });
    }
    if (path === "credentials" && route.request().method() === "POST") {
      submitted = route.request().postDataJSON();
      keys = [...keys, { ...credential, id: "33333333-3333-4333-8333-333333333333", label: "새 개인 연결" }];
      return route.fulfill({ status: 201, json: keys.at(-1) });
    }
    const payload = path === "credentials" ? keys : path === "conversations" ? chats
      : path === "catalog" ? { models: [{ id: "test/model:free", name: "테스트 무료 모델", context_length: 32000 }] }
      : path === "endpoints" ? { endpoints: [{ id: "test/bf16", name: "테스트 처리업체", context_length: 32000 }] }
      : [];
    return route.fulfill({ json: payload });
  });
  await page.goto("/");
  await expect(page.locator(".connection-indicator")).toContainText("1개 연결");
  await navigate(page, "내 연결");
  await page.getByRole("button", { name: "연결 추가", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("textbox", { name: "연결 이름" }).fill("새 개인 연결");
  await page.getByPlaceholder("API 키", { exact: true }).fill("test-private-key-never-persisted-in-browser");
  await expect(page.getByPlaceholder("API 키", { exact: true })).toHaveAttribute("type", "password");
  await page.getByLabel("무료 모델", { exact: true }).selectOption("test/model:free");
  await page.getByRole("checkbox", { name: "테스트 처리업체" }).check();
  const consent = page.getByRole("checkbox", { name: "이 제공자와 선택한 처리업체" });
  await expect(consent).not.toBeChecked();
  await consent.check();
  await page.screenshot({ path: `test-results/${info.project.name}-connection.png`, fullPage: true });
  await page.getByRole("button", { name: "연결 저장" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  expect(submitted).toMatchObject({ approved: true, upstreams: ["test/bf16"], provider: "openrouter" });
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).not.toContain("test-private-key");
  await navigate(page, "대화");
  await page.getByRole("textbox", { name: "메시지", exact: true }).fill("테스트 요청");
  await page.getByRole("button", { name: "메시지 전송" }).click();
  await expect(page.locator(".message.assistant")).toContainText("테스트 응답입니다.");
  await expect(page.locator(".message.assistant img")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "메시지 전송" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/${info.project.name}-conversation.png`, fullPage: true });
  if (info.project.name === "mobile") await page.getByRole("button", { name: "메뉴 열기" }).click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "테스트 대화 삭제" }).click();
  await expect(page.getByRole("button", { name: "테스트 대화 삭제" })).toHaveCount(0);
});

test("preflight rejection preserves draft and does not invent chat history", async ({ page }) => {
  await login(page);
  await page.route("**/api/gateway/**", async (route) => {
    if (route.request().url().endsWith("/chat")) return route.fulfill({
      status: 409, json: { detail: "No approved verified-free provider is available" },
    });
    return route.fulfill({ json: route.request().url().endsWith("/credentials") ? [credential] : [] });
  });
  await page.goto("/");
  const input = page.getByRole("textbox", { name: "메시지", exact: true });
  await input.fill("보존할 초안");
  await page.getByRole("button", { name: "메시지 전송" }).click();
  await expect(page.locator(".alert[role=alert]")).toContainText("사용 가능한 무료 연결이 없습니다");
  await expect(input).toHaveValue("보존할 초안");
  await expect(page.locator(".message")).toHaveCount(0);
});

test("stop aborts the browser stream and sends authenticated cancellation", async ({ page }) => {
  await login(page);
  let release!: () => void;
  const cancelled = new Promise<void>((resolve) => { release = resolve; });
  let cancelSent = false;
  await page.route("**/api/gateway/**", async (route) => {
    const url = route.request().url();
    if (url.endsWith("/chat")) {
      await cancelled;
      return route.abort().catch(() => undefined);
    }
    if (url.endsWith("/cancel")) {
      cancelSent = true; release();
      return route.fulfill({ status: 204 });
    }
    return route.fulfill({ json: url.endsWith("/credentials") ? [credential] : [] });
  });
  await page.goto("/");
  await page.getByRole("textbox", { name: "메시지", exact: true }).fill("중지할 요청");
  await page.getByRole("button", { name: "메시지 전송" }).click();
  await page.getByRole("button", { name: "응답 중지" }).click();
  await expect(page.getByRole("button", { name: "메시지 전송" })).toBeVisible();
  await expect.poll(() => cancelSent).toBe(true);
});