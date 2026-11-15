import { test, expect, type Page } from "@playwright/test";
import { encode } from "next-auth/jwt";

const credential = {
  id: "11111111-1111-4111-8111-111111111111", provider: "openrouter",
  label: "테스트 개인 연결", model: "test/model:free", upstreams: ["test/bf16"],
  approved: true, priority: 0, status: "valid", checked_at: new Date().toISOString(),
  auth_type: "api_key", auth_status: "authenticated", usage_state: "available",
  quota_snapshot: { source: "official", daily: { limit: 50, used: 23, remaining: 27 } },
};

async function navigate(page: Page, name: string) {
  const menu = page.getByRole("button", { name: "메뉴 열기" });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("navigation", { name: "주요 메뉴" }).getByRole("button", { name }).click();
}

async function login(page: Page, options: { owner?: string; provider?: string; name?: string } = {}) {
  const cookieName = "authjs.session-token";
  const owner = options.owner || "11111111-1111-4111-8111-111111111111";
  const sid = crypto.randomUUID();
  const expires = new Date(Date.now() + 3600000).toISOString();
  await page.request.post("http://127.0.0.1:3199/fixture/session", { data: {
    user_id: owner, session_id: sid, provider: options.provider || "github",
    name: options.name || "테스트 사용자",
    expires_at: expires,
  } });
  const value = await encode({
    token: { sub: `user:${owner}`, sid, accountVersion: 1, name: options.name || "테스트 사용자",
      loginProvider: options.provider || "github", sessionExpires: expires },
    secret: "test-session-secret-only-not-for-production-0123456789",
    salt: cookieName, maxAge: 3600,
  });
  await page.context().addCookies([{
    name: cookieName, value, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax",
  }]);
  return { owner, sid, expires };
}

test("account store errors hide private data without pretending the session expired", async ({ page }) => {
  const session = await login(page);
  await page.route("**/api/gateway/**", (route) => route.fulfill({ json: [] }));
  await page.goto("/");
  const prompt = page.getByRole("textbox", { name: "메시지", exact: true });
  await prompt.fill("private outage draft");
  const refresh = page.waitForResponse((response) => response.url().endsWith("/api/auth/session"));
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await refresh;
  await expect(prompt).toHaveValue("private outage draft");
  const fixture = {
    user_id: session.owner, session_id: session.sid, provider: "github",
    name: "테스트 사용자", expires_at: session.expires,
  };
  await page.request.post("http://127.0.0.1:3199/fixture/session", {
    data: { ...fixture, unavailable: true },
  });
  await page.evaluate(() => {
    const channel = new BroadcastChannel("wagl-site-session");
    channel.postMessage("changed"); channel.close();
  });
  await expect(page.getByText("계정 저장소에 접근할 수 없습니다.", { exact: false })).toBeVisible();
  await expect(prompt).toHaveCount(0);
  expect((await page.request.get("/api/auth/session")).status()).toBe(503);
  await expect(page).toHaveURL("/");
  await page.request.post("http://127.0.0.1:3199/fixture/session", { data: fixture });
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(prompt).toHaveValue("");
});

test("site logout clears personal data in other tabs without deleting the connection", async ({ page }) => {
  await login(page, { provider: "google" });
  await page.route("**/api/gateway/**", (route) => route.fulfill({
    json: route.request().url().endsWith("/credentials") ? [credential] : [],
  }));
  await page.goto("/");
  await expect(page.locator(".account")).toContainText("Google");
  await page.getByRole("textbox", { name: "메시지", exact: true }).fill("logout-private-draft");
  const other = await page.context().newPage();
  await other.route("**/api/gateway/**", (route) => route.fulfill({ json: [] }));
  await other.goto("/");
  await expect(other.locator(".account")).toContainText("Google");
  const menu = page.getByRole("button", { name: "메뉴 열기" });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await expect(page).toHaveURL(/\/login/);
  await expect(other).toHaveURL(/\/login/);
  await expect(page.getByText("logout-private-draft")).toHaveCount(0);
  expect((await page.request.get("/api/gateway/credentials")).status()).toBe(401);
  await login(page, { provider: "google" });
  await page.goto("/");
  await expect(page.locator(".connection-indicator")).toContainText("1개 연결");
  await expect(page.getByRole("textbox", { name: "메시지", exact: true })).toHaveValue("");
  await other.close();
});

test("account switches remount workspace and reject legacy site cookies", async ({ page }) => {
  const previous = await login(page, { name: "사용자 A" });
  await page.route("**/api/gateway/**", (route) => route.fulfill({ json: [] }));
  await page.goto("/");
  await page.getByRole("textbox", { name: "메시지", exact: true }).fill("private A draft");
  await login(page, {
    owner: "22222222-2222-4222-8222-222222222222", name: "사용자 B",
    provider: "microsoft-entra-id",
  });
  const stale = await page.request.post("/api/gateway/chat", {
    headers: { Origin: "http://127.0.0.1:3110", "X-Wagl-Session": previous.sid }, data: {},
  });
  expect(stale.status()).toBe(409);
  await page.evaluate(() => {
    const channel = new BroadcastChannel("wagl-site-session");
    channel.postMessage("changed"); channel.close();
  });
  await expect(page.locator(".account")).toContainText("사용자 B");
  await expect(page.locator(".account")).toContainText("Microsoft 개인 계정");
  await expect(page.getByRole("textbox", { name: "메시지", exact: true })).toHaveValue("");
  await page.context().clearCookies();
  const cookieName = "authjs.session-token";
  const value = await encode({
    token: { sub: "github:old-user", name: "Legacy private name" },
    secret: "test-session-secret-only-not-for-production-0123456789",
    salt: cookieName, maxAge: 3600,
  });
  await page.context().addCookies([{
    name: cookieName, value, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax",
  }]);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "생각이 이어지는 곳." })).toBeVisible();
  await expect(page.locator(".account")).toHaveCount(0);
  await expect(page.getByText("Legacy private name")).toHaveCount(0);
});

test("expired server sessions block existing cookies and clear workspace", async ({ page }) => {
  const fixture = await login(page);
  await page.route("**/api/gateway/**", (route) => route.fulfill({ json: [] }));
  const hydrated = page.waitForResponse((response) => response.url().endsWith("/api/gateway/credentials"));
  await page.goto("/");
  await hydrated;
  await expect(page.locator(".account")).toBeVisible();
  await page.request.post("http://127.0.0.1:3199/fixture/session", { data: {
    user_id: fixture.owner, session_id: fixture.sid, name: "테스트 사용자", provider: "github",
    expires_at: new Date(Date.now() - 1000).toISOString(),
  } });
  await page.evaluate(() => {
    const channel = new BroadcastChannel("wagl-site-session");
    channel.postMessage("changed"); channel.close();
  });
  await expect(page).toHaveURL(/\/login\?error=SessionExpired/);
  await expect(page.getByRole("alert").filter({ hasText: "사이트 세션" })).toContainText("만료");
  expect((await page.request.get("/api/gateway/credentials")).status()).toBe(401);
  const expired = await page.request.post("/api/auth/session", {
    headers: { Origin: "http://127.0.0.1:3110" }, data: {},
  });
  expect(await expired.json()).toBeNull();
});

test("Copilot with an old blocked snapshot can submit for fresh server preflight and streamed chat", async ({ page }) => {
  await login(page);
  const copilot = {
    ...credential, id: "44444444-4444-4444-8444-444444444444", label: "내 구독 Copilot",
    provider: "copilot", model: "auto", upstreams: ["github-copilot"], auth_type: "oauth",
    status: "unverified", usage_state: "copilot_check_required",
    quota_snapshot: { source: "copilot_sdk", plan: "enterprise", reason: "copilot_overage_enabled" },
  };
  let submitted: Record<string, unknown> | null = null;
  await page.route("**/api/gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/gateway/", "");
    if (path === "chat") {
      submitted = route.request().postDataJSON();
      return route.fulfill({ contentType: "text/event-stream", body:
        'event: attempt\ndata: {"provider":"copilot","model":"auto","number":1}\n\n'
        + 'event: delta\ndata: {"text":"Copilot 무료 응답"}\n\n'
        + 'event: model\ndata: {"model":"free-auto-model"}\n\n'
        + 'event: done\ndata: {"usage":{}}\n\n',
      });
    }
    if (path.endsWith("/verify")) return route.fulfill({ json: copilot });
    return route.fulfill({ json: path === "credentials" ? [credential, copilot] : [] });
  });
  await page.goto("/");
  await page.getByRole("combobox", { name: "대화에 사용할 연결" }).selectOption(copilot.id);
  await page.getByRole("textbox", { name: "메시지", exact: true }).fill("한국어로 대답해줘");
  await page.getByRole("button", { name: "메시지 전송" }).click();
  await expect(page.locator(".message.assistant")).toContainText("Copilot 무료 응답");
  await expect(page.locator(".message.assistant .message-author")).toContainText("GitHub Copilot");
  await expect(page.locator(".message.assistant .message-model")).toContainText("free-auto-model");
  expect(submitted).toMatchObject({ credential_id: copilot.id, prompt: "한국어로 대답해줘" });
  await expect(page.getByRole("combobox", { name: "대화에 사용할 연결" })).toHaveValue(copilot.id);
  await expect(page.locator(".free-policy")).toHaveText("무료·구독 포함량 사용");
  await navigate(page, "내 연결");
  await expect(page.locator(".connection-row").filter({ hasText: copilot.label })).toContainText(
    "개인 유료·Business·Enterprise 구독도 추가 요금 없는 포함 사용량은 이용할 수 있습니다.",
  );
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("Copilot already using overage remains blocked without sending a prompt", async ({ page }) => {
  await login(page);
  const copilot = {
    ...credential, label: "내 Copilot", provider: "copilot", model: "auto",
    upstreams: ["github-copilot"], auth_type: "oauth", status: "unverified",
    usage_state: "copilot_overage_in_use",
    quota_snapshot: { source: "copilot_sdk", plan: "enterprise", reason: "copilot_overage_in_use" },
  };
  let checks = 0, sends = 0;
  await page.route("**/api/gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/gateway/", "");
    if (path.endsWith("/verify")) {
      checks++;
      return route.fulfill({ json: copilot });
    }
    if (path === "chat") sends++;
    return route.fulfill({ json: path === "credentials" ? [copilot] : [] });
  });
  await page.goto("/");
  const connectionStatus = page.getByRole("status", { name: "대화 연결 상태" });
  await expect(connectionStatus).toContainText("과금 방지 차단 · 이미 초과 사용 중");
  await expect(connectionStatus).toContainText("GitHub가 이미 초과 사용 중이라고 응답해 전송을 차단했습니다.");
  const input = page.getByRole("textbox", { name: "메시지", exact: true });
  await input.fill("Hi");
  await input.press("Enter");
  await expect(connectionStatus).toBeFocused();
  await expect(input).toHaveValue("Hi");
  await expect(page.getByRole("button", { name: "메시지 전송" })).toBeDisabled();
  await connectionStatus.getByRole("button", { name: "내 Copilot 이용 조건 다시 확인" }).click();
  await expect.poll(() => checks).toBe(2);
  await expect(connectionStatus).toContainText("입력한 메시지는 전송되지 않았습니다");
  await expect(input).toHaveValue("Hi");
  await expect(page.locator(".message")).toHaveCount(0);
  await connectionStatus.getByRole("button", { name: "연결 설정 열기" }).click();
  const row = page.locator(".connection-row");
  await expect(row).toContainText("과금 방지 차단 · 이미 초과 사용 중");
  await expect(row).toContainText("공식 조회 플랜: enterprise");
  await row.getByRole("button", { name: "내 Copilot 이용 조건 다시 확인" }).click();
  await expect.poll(() => checks).toBe(3);
  await expect(row).toContainText("한도 갱신을 기다리거나 다른 연결을 사용하세요.");
  await expect(row).not.toContainText("Copilot Free만 지원");
  expect(sends).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("Copilot connection forwards explicit consent through the authenticated BFF", async ({ page }) => {
  const session = await login(page);
  const malformed = await page.request.post("/api/connections/copilot/start", {
    headers: { Origin: "http://127.0.0.1:3110", "X-Wagl-Session": session.sid }, data: {},
  });
  expect(malformed.status()).toBe(422);
  await page.route("**/api/gateway/**", (route) => route.fulfill({
    json: route.request().url().endsWith("/connection-options") ? { copilot_oauth: true } : [],
  }));
  await page.route("https://github.com/login/oauth/authorize?**", (route) =>
    route.fulfill({ contentType: "text/html", body: "<h1>Mock GitHub approval</h1>" }));
  await page.goto("/");
  await navigate(page, "내 연결");
  await page.getByRole("button", { name: "연결 추가", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "GitHub Copilot" }).click();
  await expect(page.getByRole("dialog")).toContainText("대화·이력·첨부를 GitHub Copilot");
  const response = page.waitForResponse((result) => result.url().endsWith("/api/connections/copilot/start"));
  await page.getByRole("button", { name: "동의하고 Copilot 연결" }).click();
  const started = await response;
  expect(started.status()).toBe(200);
  expect(started.request().postDataJSON()).toEqual({ approved: true });
  await expect(page.getByRole("heading", { name: "Mock GitHub approval" })).toBeVisible();
});

for (const available of [true, false]) {
  test(`Copilot conditions are automatically checked and ${available ? "enable use" : "fail closed"} without granting legacy consent`, async ({ page }) => {
    await login(page);
    const copilot = {
      ...credential, provider: "copilot", label: "자동 확인 연결", model: null,
      upstreams: ["github-copilot"], auth_type: "oauth", status: "unverified",
      usage_state: "copilot_check_required",
    };
    const inactive = { ...copilot, id: "55555555-5555-4555-8555-555555555555",
      label: "기존 미동의 연결", approved: false, usage_state: "consent_required" };
    let checks = 0, sends = 0, writes = 0;
    let release!: () => void;
    const verification = new Promise<void>((resolve) => { release = resolve; });
    await page.route("**/api/gateway/**", async (route) => {
      const path = new URL(route.request().url()).pathname.replace("/api/gateway/", "");
      if (route.request().method() === "PATCH") writes++;
      if (path.endsWith("/verify")) {
        expect(path).toBe(`credentials/${copilot.id}/verify`);
        checks++;
        await verification;
        return available
          ? route.fulfill({ json: { ...copilot, model: "auto", status: "valid", usage_state: "available" } })
          : route.fulfill({ status: 503, json: { detail: "verification_unavailable" } });
      }
      if (path === "chat") sends++;
      return route.fulfill({ json: path === "credentials" ? [copilot, inactive] : [] });
    });
    await page.goto("/");
    const input = page.getByRole("textbox", { name: "메시지", exact: true });
    await input.fill("자동 조회 중 초안");
    await expect.poll(() => checks).toBe(1);
    await expect(page.getByRole("button", { name: "메시지 전송" })).toBeDisabled();
    release();
    if (available) {
      await expect(page.getByRole("button", { name: "메시지 전송" })).toBeEnabled();
    } else {
      await expect(page.getByRole("status", { name: "대화 연결 상태" })).toContainText("이용 조건 자동 확인 실패");
      await expect(page.locator(".alert")).toContainText("자동 확인 연결");
      await expect(page.getByRole("button", { name: "메시지 전송" })).toBeDisabled();
    }
    await expect(input).toHaveValue("자동 조회 중 초안");
    await navigate(page, "내 연결");
    await expect(page.locator(".connection-row").filter({ hasText: "자동 확인 연결" }).getByRole("switch")).toBeChecked();
    await expect(page.locator(".connection-row").filter({ hasText: "기존 미동의 연결" }).getByRole("switch")).not.toBeChecked();
    expect(checks).toBe(1);
    expect(writes).toBe(0);
    expect(sends).toBe(0);
  });
}

test("chat recheck enables a retained draft without automatically sending it", async ({ page }) => {
  await login(page);
  let connection = {
    ...credential, provider: "copilot", label: "내 Copilot", model: "auto",
    upstreams: ["github-copilot"], auth_type: "oauth", status: "unverified",
    usage_state: "copilot_overage_in_use",
  };
  let sends = 0, checks = 0, submitted: Record<string, unknown> | null = null;
  let release!: () => void;
  const verification = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/gateway/", "");
    if (path.endsWith("/verify")) {
      if (++checks === 1) return route.fulfill({ json: connection });
      await verification;
      connection = { ...connection, status: "valid", usage_state: "available" };
      return route.fulfill({ json: connection });
    }
    if (path === "chat") {
      sends++;
      submitted = route.request().postDataJSON();
      return route.fulfill({ contentType: "text/event-stream", body:
        'event: attempt\ndata: {"provider":"copilot","model":"auto","number":1}\n\n'
        + 'event: delta\ndata: {"text":"안녕하세요"}\n\n'
        + 'event: done\ndata: {"usage":{}}\n\n',
      });
    }
    return route.fulfill({ json: path === "credentials" ? [connection] : [] });
  });
  await page.goto("/");
  const input = page.getByRole("textbox", { name: "메시지", exact: true });
  await input.fill("Hi");
  const connectionStatus = page.getByRole("status", { name: "대화 연결 상태" });
  await connectionStatus.getByRole("button", { name: "내 Copilot 이용 조건 다시 확인" }).click();
  await expect(connectionStatus.getByRole("button", { name: "이용 조건 확인 중…" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "메시지 전송" })).toBeDisabled();
  expect(sends).toBe(0);
  release();
  await expect(connectionStatus).not.toBeVisible();
  await expect(input).toHaveValue("Hi");
  await expect(page.getByRole("button", { name: "메시지 전송" })).toBeEnabled();
  expect(sends).toBe(0);
  await page.getByRole("button", { name: "메시지 전송" }).click();
  await expect(page.locator(".message.assistant")).toContainText("안녕하세요");
  expect(sends).toBe(1);
  expect(submitted).toMatchObject({ prompt: "Hi" });
});

test("connection lookup failure can be retried from the composer without losing the draft", async ({ page }) => {
  await login(page);
  let available = false, sends = 0;
  await page.route("**/api/gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/gateway/", "");
    if (path === "credentials" && !available) return route.fulfill({
      status: 503, json: { detail: "Policy service unavailable" },
    });
    if (path === "chat") sends++;
    return route.fulfill({ json: path === "credentials" ? [credential] : [] });
  });
  await page.goto("/");
  const connectionStatus = page.getByRole("status", { name: "대화 연결 상태" });
  await expect(connectionStatus).toContainText("연결 상태를 불러오지 못했습니다");
  const input = page.getByRole("textbox", { name: "메시지", exact: true });
  await input.fill("Hi");
  available = true;
  await connectionStatus.getByRole("button", { name: "연결 상태 새로고침" }).click();
  await expect(connectionStatus).not.toBeVisible();
  await expect(input).toHaveValue("Hi");
  await expect(page.getByRole("button", { name: "메시지 전송" })).toBeEnabled();
  expect(sends).toBe(0);
});

test("suggestions populate editable prompts without sending until explicit submission", async ({ page }) => {
  await login(page);
  let sends = 0, submitted: Record<string, unknown> | null = null;
  const conversations = [
    { id: "55555555-5555-4555-8555-555555555555", title: "회의 안건 정리해줘", created_at: new Date().toISOString() },
    { id: "66666666-6666-4666-8666-666666666666", title: "여행 계획을 세워줘", created_at: new Date().toISOString() },
  ];
  await page.route("**/api/gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/gateway/", "");
    if (path === "chat") {
      sends++;
      submitted = route.request().postDataJSON();
      return route.fulfill({ contentType: "text/event-stream", body:
        'event: delta\ndata: {"text":"연결 성공"}\n\n'
        + 'event: done\ndata: {"usage":{}}\n\n',
      });
    }
    return route.fulfill({ json: path === "credentials" ? [credential]
      : path === "conversations" ? conversations : [] });
  });
  await page.goto("/");
  const input = page.getByRole("textbox", { name: "메시지", exact: true });
  const suggestions = page.locator(".prompt-suggestions").getByRole("button");
  await expect(suggestions).toHaveCount(3);
  await expect(suggestions.nth(0)).toHaveAttribute("title", conversations[0].title);
  await expect(suggestions.nth(1)).toHaveAttribute("title", conversations[1].title);
  await expect(suggestions.nth(0)).toContainText("이전 질문");
  await expect(suggestions.nth(1)).toContainText("이전 질문");
  await expect(suggestions.nth(2)).not.toContainText("이전 질문");
  for (let index = 0; index < 3; index++) {
    const suggestion = suggestions.nth(index);
    const expected = await suggestion.getAttribute("title");
    if (!expected) throw new Error("Suggestion has no prompt");
    await suggestion.click();
    await expect(input).toHaveValue(expected);
    await expect(input).toBeFocused();
    await expect(page.locator(".message")).toHaveCount(0);
    expect(sends).toBe(0);
  }
  await expect(page.locator(".prompt-test-help")).toContainText("전송 시 포함 사용량이 소모될 수 있습니다");
  await suggestions.first().click();
  await input.fill(`${await input.inputValue()} (수정한 초안)`);
  const draft = await input.inputValue();
  await expect(page.getByRole("button", { name: "메시지 전송" })).toBeEnabled();
  await page.getByRole("button", { name: "메시지 전송" }).click();
  await expect(page.locator(".message.assistant")).toContainText("연결 성공");
  expect(sends).toBe(1);
  expect(submitted).toMatchObject({ prompt: draft });
});

test("image paste and text upload are previewed, sent, and reopened with chat history", async ({ page }) => {
  await login(page);
  const imageData = "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAIUlEQVR4nGP8z0AaYCJRPcOoBmIAE1GqkMCoBmIAyaEEAEAuAR9UPEsJAAAAAElFTkSuQmCC";
  const copilot = { ...credential, provider: "copilot", model: "auto", upstreams: ["github-copilot"], auth_type: "oauth" };
  let submitted: Record<string, unknown> | null = null;
  const chat = { id: "55555555-5555-4555-8555-555555555555", title: "첨부를 설명해줘", created_at: new Date().toISOString() };
  let saved: { role: string; content: string; attachments?: unknown }[] = [];
  await page.route("**/api/gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/gateway/", "");
    if (path === "chat") {
      submitted = route.request().postDataJSON();
      saved = [
        { role: "user", content: "첨부를 설명해줘", attachments: submitted?.attachments },
        { role: "assistant", content: "이미지와 문서를 확인했어요" },
      ];
      return route.fulfill({ contentType: "text/event-stream", body:
        `event: conversation\ndata: {"id":"${chat.id}"}\n\n`
        + 'event: delta\ndata: {"text":"이미지와 문서를 확인했어요"}\n\n'
        + 'event: done\ndata: {"usage":{}}\n\n',
      });
    }
    if (path.endsWith("/verify")) return route.fulfill({ json: copilot });
    return route.fulfill({ json: path === "credentials" ? [copilot]
      : path === "conversations" ? saved.length ? [chat] : []
      : path === `conversations/${chat.id}` ? { messages: saved.map((message, index) => ({ id: String(index), status: "complete", ...message })) } : [] });
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.locator('input[type="file"]').setInputFiles({
    name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("테스트 단어: 와글"),
  });
  await expect(page.locator(".composer .chat-attachments")).toContainText("notes.txt");
  await page.evaluate((data) => {
    const clipboard = new DataTransfer();
    clipboard.items.add(new File([Uint8Array.from(atob(data), (character) => character.charCodeAt(0))], "screenshot.png", { type: "image/png" }));
    document.querySelector("textarea")!.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData: clipboard }));
  }, imageData);
  await expect(page.locator(".composer .chat-attachments img")).toBeVisible();
  await expect(page.locator(".composer .chat-attachments li")).toHaveCount(2);
  expect(submitted).toBeNull();
  await page.getByRole("textbox", { name: "메시지", exact: true }).fill("첨부를 설명해줘");
  await page.getByRole("button", { name: "메시지 전송" }).click();
  await expect(page.locator(".message.assistant")).toContainText("이미지와 문서를 확인했어요");
  expect(submitted).toMatchObject({ attachments: [
    { name: "notes.txt", mime_type: "text/plain", data: Buffer.from("테스트 단어: 와글").toString("base64") },
    { name: "screenshot.png", mime_type: "image/png", data: imageData },
  ] });
  await expect(page.locator(".composer .chat-attachments")).toHaveCount(0);
  await page.reload({ waitUntil: "domcontentloaded" });
  const menu = page.getByRole("button", { name: "메뉴 열기" });
  if (await menu.isVisible()) await menu.click();
  await page.locator(".history-row > button").filter({ hasText: chat.title }).click();
  await expect(page.locator(".message.user .chat-attachments li")).toHaveCount(2);
  await expect(page.locator(".message.user .chat-attachments a").first()).toHaveAttribute("download", "notes.txt");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("rejected attachments stay editable and unsupported files are explained", async ({ page }) => {
  await login(page);
  await page.route("**/api/gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/gateway/", "");
    if (path === "chat") return route.fulfill({ status: 422, json: { detail: "attachment_provider_unsupported" } });
    return route.fulfill({ json: path === "credentials" ? [credential] : [] });
  });
  await page.goto("/");
  const input = page.locator('input[type="file"]');
  await input.setInputFiles({ name: "document.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-test") });
  await expect(page.locator(".alert")).toContainText("PDF·Word·압축 파일은 아직 지원하지 않습니다");
  await input.setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("hello") });
  await expect(page.locator(".composer .chat-attachments")).toContainText("notes.txt");
  await page.getByRole("button", { name: "notes.txt 첨부 삭제" }).click();
  await expect(page.locator(".composer .chat-attachments")).toHaveCount(0);
  await input.setInputFiles({ name: "big.png", mimeType: "image/png", buffer: Buffer.alloc(2 * 1024 * 1024 + 1) });
  await expect(page.locator(".alert")).toContainText("이미지는 파일당 2MB");
  await input.setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("hello") });
  await page.getByRole("textbox", { name: "메시지", exact: true }).fill("초안 유지");
  await page.getByRole("button", { name: "메시지 전송" }).click();
  await expect(page.locator(".alert")).toContainText("이미지 분석은 현재 GitHub Copilot 연결만 지원합니다");
  await expect(page.getByRole("textbox", { name: "메시지", exact: true })).toHaveValue("초안 유지");
  await expect(page.locator(".composer .chat-attachments")).toContainText("notes.txt");
  await expect(page.locator(".message")).toHaveCount(0);
});

test("logged-out visitors see the workspace first and are sent to login only when they try to chat", { tag: "@oauth-disabled-guidance" }, async ({ page, request }, info) => {
  const errors: string[] = [];
  const gateway: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (call) => { if (call.url().includes("/api/gateway/")) gateway.push(call.url()); });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "생각이 이어지는 곳." })).toBeVisible();
  await expect(page.getByRole("heading", { name: "나만의 AI 연결, 나만의 작업공간." })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "로그인", exact: true }).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/${info.project.name}-guest-workspace.png`, fullPage: true });
  await page.getByRole("textbox", { name: "메시지", exact: true }).fill("로그인 전 입력");
  expect(gateway).toEqual([]);
  await page.getByRole("button", { name: "메시지 전송" }).click();
  await expect(page).toHaveURL(/\/login\?callbackUrl=%2F$/);
  expect(gateway).toEqual([]);
  await expect(page.getByRole("heading", { name: "나만의 AI 연결, 나만의 작업공간." })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "메시지", exact: true })).toHaveCount(0);
  for (const name of ["Microsoft 개인 계정으로 로그인", "Google로 로그인", "GitHub로 로그인"]) {
    const button = page.getByRole("button", { name, exact: true });
    if (process.env.WAGL_TEST_AUTH_DISABLED) {
      await expect(button).toBeDisabled();
      await expect(button.locator("..")).toContainText("운영자 설정 대기");
    } else await expect(button).toBeEnabled();
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/${info.project.name}-login.png`, fullPage: true });
  expect((await request.get("/api/gateway/credentials")).status()).toBe(401);
  expect((await request.get("/api/gateway/unapproved-route")).status()).toBe(404);
  expect((await request.post("/api/connections/copilot/start")).status()).toBe(401);
  const callback = await request.get("/api/connections/copilot/callback?state=invalid&code=private-test-code&redirect_uri=https://example.invalid", { maxRedirects: 0 });
  expect(callback.status()).toBe(303);
  expect(callback.headers().location).toBe("http://127.0.0.1:3110/?connection=oauth_invalid_state");
  expect(callback.headers()["referrer-policy"]).toBe("no-referrer");
  expect(callback.headers()["cache-control"]).toBe("no-store");
  await page.getByRole("link", { name: "개인정보 처리 안내" }).click();
  await expect(page.getByRole("heading", { name: "개인정보 처리 안내", exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("ChatGPT shows the official sign-in approval state without accepting an API key", async ({ page }) => {
  await login(page);
  await page.goto("/");
  await navigate(page, "내 연결");
  await page.getByRole("button", { name: "연결 추가", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "AI 서비스 연결" });
  await dialog.getByRole("button", { name: "ChatGPT" }).click();
  await expect(dialog).toContainText("승인 대기 중 · 아직 연결할 수 없습니다");
  await expect(dialog).toContainText("원격 호스팅 웹은 OpenAI의 별도 승인이 필요");
  await expect(dialog.getByPlaceholder("API 키")).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "동의하고 연결" })).toHaveCount(0);
});

test("Copilot setup guide displays both supplied registration screenshots without leaving the form", async ({ page }) => {
  await login(page);
  await page.goto("/?connect=copilot");
  const dialog = page.getByRole("dialog", { name: "AI 서비스 연결" });
  const guide = dialog.locator(".oauth-setup-guide");
  await guide.getByText("운영자 최초 설정: OAuth 앱 등록 화면 2개 보기", { exact: true }).click();
  await expect(guide).toContainText("일반 사용자는 OAuth 앱을 만들 필요가 없습니다");
  const examples = guide.locator(".oauth-setup-example");
  await expect(examples).toHaveCount(2);
  await expect(examples.nth(0)).toContainText("http://localhost:3000/api/auth/callback/github");
  await expect(examples.nth(1)).toContainText("http://localhost:3000/api/connections/copilot/callback");
  for (const example of await examples.all()) {
    const image = example.getByRole("img");
    await image.scrollIntoViewIfNeeded();
    await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
    expect(await example.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    const originalLink = example.getByRole("link", { name: /스크린샷 크게 보기/ });
    const popupPromise = page.waitForEvent("popup");
    await originalLink.click();
    const popup = await popupPromise;
    await expect(popup).toHaveURL(/\/guides\/github-oauth-(login|copilot)\.png$/);
    await popup.close();
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("button", { name: "GitHub Copilot", exact: false })).toHaveAttribute("aria-pressed", "true");
  }
});

test("authenticated personal key consent, streaming, masking and deletion", async ({ page }, info) => {
  await login(page);
  const denied = await page.request.post("/api/connections/copilot/start", { headers: { origin: "https://example.invalid" } });
  expect(denied.status()).toBe(403);
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
      keys = [...keys, { ...credential, id: "33333333-3333-4333-8333-333333333333", label: "새 개인 연결",
        approved: true, usage_state: "available" }];
      return route.fulfill({ status: 201, json: keys.at(-1) });
    }
    if (path.startsWith("credentials/") && route.request().method() === "PATCH") {
      keys = keys.map((key) => key.id === path.split("/")[1]
        ? { ...key, approved: true, usage_state: "available" } : key);
      return route.fulfill({ json: keys.find((key) => key.id === path.split("/")[1]) });
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
  await page.getByRole("dialog").getByRole("button", { name: "GitHub Copilot" }).click();
  await expect(page.getByRole("button", { name: "동의하고 Copilot 연결" })).toBeDisabled();
  await expect(page.getByRole("dialog")).toContainText("운영자 OAuth 설정 필요");
  await page.getByRole("dialog").getByRole("button", { name: "OpenRouter" }).click();
  await page.getByRole("textbox", { name: "연결 이름" }).fill("새 개인 연결");
  await page.getByPlaceholder("API 키", { exact: true }).fill("test-private-key-never-persisted-in-browser");
  if (info.project.name === "desktop") {
    await expect(page.getByRole("complementary", { name: "OpenRouter 처음 연결하는 방법" })).toBeInViewport();
  }
  await expect(page.getByPlaceholder("API 키", { exact: true })).toHaveAttribute("type", "password");
  await page.getByLabel("무료 모델", { exact: true }).selectOption("test/model:free");
  await page.getByRole("checkbox", { name: "테스트 처리업체" }).check();
  await expect(page.getByRole("dialog")).toContainText("대화·이력·첨부를 OpenRouter 및 선택한 실제 처리업체");
  await page.screenshot({ path: `test-results/${info.project.name}-connection.png`, fullPage: true });
  await page.getByRole("button", { name: "동의하고 연결" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  expect(submitted).toMatchObject({ approved: true, upstreams: ["test/bf16"], provider: "openrouter" });
  const savedCard = page.locator(".connection-row").filter({ hasText: "새 개인 연결" });
  await expect(savedCard.getByRole("switch")).toBeChecked();
  await expect(savedCard).toContainText("사용 가능");
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