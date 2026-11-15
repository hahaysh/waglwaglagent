export type Credential = {
  id: string; provider: "openrouter" | "gemini" | "copilot" | "openai" | "anthropic"; label: string; model: string | null;
  auth_type?: "api_key" | "oauth"; auth_status?: string; usage_state?: string;
  upstreams: string[]; approved: boolean; priority: number; status: string;
  checked_at: string | null;
  quota_snapshot: {
    source?: string; checked_at?: string; reason?: string; plan?: string; overage_allowed?: boolean;
    quotas?: Record<string, { remaining_percentage: number; reset_at: string | null }>;
    daily?: { used: number; limit: number; remaining: number } | null;
  };
};
export type Conversation = { id: string; title: string; created_at: string };
export type ChatAttachment = { name: string; mime_type: string; data: string };
export type ChatMessage = {
  id: string; role: "user" | "assistant"; content: string; status: string;
  attachments?: ChatAttachment[];
  provider?: string | null; model?: string | null;
};
export type Activity = {
  id: string; provider: string; model: string; upstreams: string[]; status: string;
  usage: { total_tokens?: number }; created_at: string;
};
export type Model = { id: string; name: string; context_length: number };
export type Endpoint = { id: string; name: string; context_length: number };

const errors: Record<string, string> = {
  "Authentication required": "로그인이 필요합니다.",
  "Authentication not configured": "사이트 로그인 설정이 필요합니다.",
  "Session expired": "사이트 세션이 만료되었습니다. 다시 로그인해주세요.",
  "Session changed": "사이트 로그인 계정이 변경되었습니다. 새 작업공간을 확인해주세요.",
  account_store_unavailable: "계정 저장소에 접근할 수 없습니다. 잠시 후 다시 시도해주세요.",
  maintenance: "개인 작업공간 점검 중입니다. 잠시 후 다시 로그인해주세요.",
  "Policy service unavailable": "API 서버에 연결할 수 없습니다.",
  "Provider preflight timed out": "제공자 사전 확인 시간이 초과됐습니다.",
  "Service not configured": "서버 설정이 필요합니다.",
  secret_store_unavailable: "Key Vault에 접근할 수 없어 요청을 중지했습니다. 운영자에게 로그인·권한·연결 상태 확인을 요청해주세요.",
  "Invalid input": "입력값을 확인해주세요.",
  attachment_invalid: "첨부를 읽을 수 없습니다. 이미지는 PNG·JPEG·WebP(16MP 이하), 텍스트는 UTF-8(32KB 이하)인지 확인해주세요.",
  attachment_too_large: "첨부는 파일당 2MB, 한 메시지 합계 4MB 이하여야 합니다.",
  attachment_unsupported: "지원하지 않는 첨부 형식입니다. PNG·JPEG·WebP 또는 UTF-8 텍스트·코드 파일을 사용해주세요.",
  attachment_provider_unsupported: "이미지 분석은 현재 GitHub Copilot 연결만 지원합니다. Copilot을 선택하거나 이미지 없는 새 대화를 시작해주세요.",
  "Input too large": "요청 크기가 너무 큽니다. 첨부 개수나 파일 크기를 줄여주세요.",
  "Another request is running": "진행 중인 요청을 먼저 중지해주세요.",
  "No approved verified-free provider is available": "사용 가능한 무료 연결이 없습니다. 연결과 전송 동의를 확인해주세요.",
  "Conversation context limit reached; start a new conversation": "대화 길이 제한에 도달했습니다. 새 대화를 시작해주세요.",
  "Request already submitted": "이미 처리한 요청입니다.",
  "Approved inference provider required": "허용할 실제 처리업체를 선택해주세요.",
  "Application rate limit reached": "요청이 많습니다. 잠시 후 다시 시도해주세요.",
  "Credential limit reached": "연결은 최대 5개까지 등록할 수 있습니다.",
  invalid_key: "키를 확인할 수 없습니다. 발급한 서비스에서 키 상태를 확인해주세요.",
  verification_unavailable: "제공자의 키 확인 서비스에 연결할 수 없습니다.",
  catalog_unavailable: "무료 모델 목록을 확인할 수 없습니다.",
  endpoints_unavailable: "실제 처리업체 목록을 확인할 수 없습니다.",
  model_not_free: "현재 무료로 확인된 모델이 아닙니다.",
  provider_unavailable: "제공자에 일시적인 장애가 발생했습니다.",
  rate_limited: "제공자의 사용 한도에 도달했습니다.",
  policy_refusal: "제공자의 안전 정책에 따라 요청이 거절됐습니다.",
  consent_changed: "연결 또는 전송 동의가 변경되어 요청을 중지했습니다.",
  request_timeout: "요청 시간이 초과됐습니다.",
  free_eligibility_unknown: "무료 사용 자격을 확인할 수 없습니다.",
  empty_response: "제공자가 빈 응답을 반환했습니다.",
  copilot_not_configured: "Copilot 연결 준비 중입니다. 운영자가 OAuth 설정을 완료해야 합니다.",
  oauth_start_failed: "인증을 시작할 수 없습니다. 잠시 후 다시 시도해주세요.",
  duplicate_connection: "이미 저장한 키입니다. 기존 연결에서 다시 확인해주세요.",
  provider_permission_denied: "모델 목록 조회 권한이 없습니다. 키의 권한과 조직 정책을 확인해주세요.",
  oauth_account_mismatch: "연결된 계정과 인증 계정이 다릅니다. 다시 연결해주세요.",
  reauth_required: "GitHub 인증이 만료되거나 철회됐습니다. Copilot을 다시 연결해주세요.",
  copilot_plan_not_free: "구독 포함 사용량을 지원하도록 정책이 변경됐습니다. 내 연결에서 이용 조건을 다시 확인해주세요.",
  copilot_overage_enabled: "이전 판정입니다. 전송하면 남은 포함 사용량을 다시 확인합니다.",
  copilot_overage_in_use: "Copilot이 이미 포함량을 넘겨 초과 사용 중이므로 전송하지 않았습니다. 다른 연결을 사용하거나 한도 갱신을 기다리세요.",
  copilot_free_eligibility_unknown: "공식 SDK에서 남은 구독 포함 사용량을 확인할 수 없어 호출하지 않았습니다.",
  copilot_quota_exhausted: "Copilot 포함 사용량을 소진했습니다. 추가 요금 없는 다른 연결을 선택하거나 한도 갱신을 기다리세요.",
  copilot_unavailable: "Copilot 자격·한도 조회 또는 런타임에 일시적인 문제가 있습니다. 다시 확인해주세요.",
  copilot_access_denied: "GitHub에서 Copilot 사용을 허용하지 않았습니다. 계정 자격과 조직 정책을 확인하세요.",
  copilot_request_failed: "Copilot 요청을 완료하지 못했습니다. 자격을 다시 확인해주세요. 유료 경로로 전환하지 않았습니다.",
  copilot_cleanup_failed: "Copilot 런타임 정리를 완료하지 못했습니다. 운영자에게 문의하세요.",
};

export function errorMessage(code: string): string {
  return errors[code] || "요청을 완료하지 못했습니다. 연결 상태를 확인해주세요.";
}

export function notifySessionChange() {
  const channel = new BroadcastChannel("wagl-site-session");
  channel.postMessage("changed"); channel.close();
}

export async function api<T>(path: string, options?: RequestInit, sessionId?: string): Promise<T> {
  const response = await fetch(`/api/gateway/${path}`, {
    ...options, headers: { "Content-Type": "application/json", ...options?.headers,
      ...(sessionId ? { "X-Wagl-Session": sessionId } : {}) }, cache: "no-store",
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401 || payload.detail === "Session changed") notifySessionChange();
    throw new Error(errorMessage(typeof payload.detail === "string" ? payload.detail : "unknown"));
  }
  return response.status === 204 ? undefined as T : response.json();
}

export async function consumeStream(
  response: Response, onEvent: (event: string, payload: Record<string, unknown>) => void,
): Promise<void> {
  if (!response.body) throw new Error("응답 스트림이 없습니다.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let boundary: RegExpExecArray | null;
      while ((boundary = /\r?\n\r?\n/.exec(buffer)) !== null) {
        const block = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const lines = block.split(/\r?\n/);
        const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
        const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
        if (event && data) onEvent(event, JSON.parse(data));
      }
      if (buffer.length > 1048576) throw new Error("응답 크기 제한을 초과했습니다.");
      if (done) break;
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}