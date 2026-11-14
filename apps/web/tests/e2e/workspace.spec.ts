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
  await expect(page.getByText("선택한 연결만 사용", { exact: true })).toBeVisible();
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
  await expect.poll(() => checks).toBe(1);
  await expect(connectionStatus).toContainText("입력한 메시지는 전송되지 않았습니다");
  await expect(input).toHaveValue("Hi");
  await expect(page.locator(".message")).toHaveCount(0);
  await connectionStatus.getByRole("button", { name: "연결 설정 열기" }).click();
  const row = page.locator(".connection-row");
  await expect(row).toContainText("과금 방지 차단 · 이미 초과 사용 중");
  await expect(row).toContainText("공식 조회 플랜: enterprise");
  await row.getByRole("button", { name: "내 Copilot 이용 조건 다시 확인" }).click();
  await expect.poll(() => checks).toBe(2);
  await expect(row).toContainText("한도 갱신을 기다리거나 다른 연결을 사용하세요.");
  await expect(row).not.toContainText("Copilot Free만 지원");
  expect(sends).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("chat recheck enables a retained draft without automatically sending it", async ({ page }) => {
  await login(page);
  let connection = {
    ...credential, provider: "copilot", label: "내 Copilot", model: "auto",
    upstreams: ["github-copilot"], auth_type: "oauth", status: "unverified",
    usage_state: "copilot_overage_in_use",
  };
  let sends = 0, submitted: Record<string, unknown> | null = null;
  let release!: () => void;
  const verification = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/gateway/", "");
    if (path.endsWith("/verify")) {
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

test("app test suggestions populate editable prompts without sending until explicit submission", async ({ page }) => {
  await login(page);
  let sends = 0, submitted: Record<string, unknown> | null = null;
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
    return route.fulfill({ json: path === "credentials" ? [credential] : [] });
  });
  await page.goto("/");
  const input = page.getByRole("textbox", { name: "메시지", exact: true });
  for (const [label, expected] of [
    ["연결 테스트 · 한 줄 응답", "연결 성공"],
    ["스트리밍·중지 테스트", "1부터 30까지"],
    ["서비스 전환·대화 이력 테스트", "와글파랑"],
  ]) {
    await page.getByRole("button", { name: label, exact: true }).click();
    await expect(input).toHaveValue(new RegExp(expected));
    await expect(input).toBeFocused();
    await expect(page.locator(".message")).toHaveCount(0);
    expect(sends).toBe(0);
  }
  await expect(page.locator(".prompt-test-help")).toContainText("전송 시 포함 사용량이 소모될 수 있습니다");
  await expect(page.locator(".prompt-test-help")).toContainText("응답 후 연결을 바꾸고");
  await page.getByRole("button", { name: "연결 테스트 · 한 줄 응답", exact: true }).click();
  await input.fill(`${await input.inputValue()} (수정한 초안)`);
  const draft = await input.inputValue();
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

test("logged-out workspace is responsive and rejects unauthenticated API requests", async ({ page, request }, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "새 대화", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "연결 테스트 · 한 줄 응답" }).click();
  await expect(page.getByRole("textbox", { name: "메시지", exact: true })).toHaveValue("연결 테스트입니다. 다른 설명 없이 '연결 성공'이라고만 답해주세요.");
  await expect(page.getByRole("button", { name: "메시지 전송" })).toBeDisabled();
  expect((await request.get("/api/gateway/credentials")).status()).toBe(401);
  expect((await request.get("/api/gateway/unapproved-route")).status()).toBe(404);
  expect((await request.post("/api/connections/copilot/start")).status()).toBe(401);
  const callback = await request.get("/api/connections/copilot/callback?state=invalid&code=private-test-code&redirect_uri=https://example.invalid", { maxRedirects: 0 });
  expect(callback.status()).toBe(303);
  expect(callback.headers().location).toBe("http://127.0.0.1:3110/?connection=oauth_invalid_state");
  expect(callback.headers()["referrer-policy"]).toBe("no-referrer");
  expect(callback.headers()["cache-control"]).toBe("no-store");
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
  for (const name of ["GitHub Copilot", "ChatGPT", "Gemini", "Claude", "OpenRouter"]) {
    await help.getByRole("button", { name, exact: false }).click();
    await expect(help.locator(".connection-guide > ol > li")).toHaveCount(5);
    await expect(help.locator(".connection-guide h3")).toHaveText(`${name} 처음 연결하는 방법`);
    await expect(help.locator(".provider-doc-link")).toHaveAttribute("target", "_blank");
    const formBox = await help.locator(".connection-form-panel").boundingBox();
    const guideBox = await help.locator(".connection-guide").boundingBox();
    expect(formBox).not.toBeNull();
    expect(guideBox).not.toBeNull();
    if (info.project.name === "desktop") {
      expect(guideBox!.x).toBeGreaterThanOrEqual(formBox!.x + formBox!.width);
    } else {
      expect(guideBox!.y).toBeGreaterThanOrEqual(formBox!.y + formBox!.height);
    }
    await expect(help.getByPlaceholder("API 키", { exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  if (process.env.WAGL_TEST_AUTH_DISABLED) {
    await expect(help).toContainText("사이트 로그인 준비 중");
    await help.getByRole("button", { name: "운영자 설정 안내" }).click();
    await expect(page.getByRole("heading", { name: "GitHub 로그인 설정이 필요합니다" })).toBeVisible();
    await expect(page.getByRole("dialog")).toContainText("AUTH_GITHUB_ID");
    const loginExample = page.getByRole("dialog").getByRole("img", { name: /GitHub 사이트 로그인용 OAuth 앱 등록 예시/ });
    await loginExample.scrollIntoViewIfNeeded();
    await expect.poll(() => loginExample.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
    await page.getByRole("button", { name: "닫기", exact: true }).click();
  } else {
    await expect(help.getByRole("button", { name: "GitHub로 사이트 로그인" })).toBeEnabled();
    await help.getByRole("button", { name: "연결 창 닫기", exact: true }).click();
  }
  await expect(help).not.toBeVisible();
  await navigate(page, "사용 기록");
  await expect(page.getByRole("heading", { name: "아직 사용 기록이 없습니다" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("Copilot setup guide displays both supplied registration screenshots without leaving the form", async ({ page }) => {
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
        approved: false, usage_state: "consent_required" }];
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
  await expect(page.getByRole("button", { name: "GitHub로 Copilot 연결" })).toBeDisabled();
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
  await expect(page.getByRole("dialog")).toContainText("저장 시에는 비활성");
  await page.screenshot({ path: `test-results/${info.project.name}-connection.png`, fullPage: true });
  await page.getByRole("button", { name: "키 확인 후 저장" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  expect(submitted).toMatchObject({ approved: false, upstreams: ["test/bf16"], provider: "openrouter" });
  const savedCard = page.locator(".connection-row").filter({ hasText: "새 개인 연결" });
  await expect(savedCard).toContainText("전송 동의 필요");
  await expect(savedCard.getByRole("switch")).not.toBeChecked();
  await savedCard.getByRole("switch").click();
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