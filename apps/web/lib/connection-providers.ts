export type ConnectionProvider = "copilot" | "openai" | "gemini" | "anthropic" | "openrouter";

export const connectionProviders: {
  id: ConnectionProvider; name: string; method: string; description: string;
  url: string; linkLabel: string; steps: string[]; warning: string; pending?: boolean;
}[] = [
  {
    id: "copilot", name: "GitHub Copilot", method: "GitHub OAuth",
    description: "전송에 동의하고 GitHub 계정을 승인하여 연결합니다. Copilot 사용 자격은 자동 확인합니다.",
    url: "https://github.com/settings/copilot", linkLabel: "Copilot 계정 설정",
    steps: [
      "먼저 이 사이트에 로그인합니다. 사이트 로그인과 Copilot 연결은 서로 다른 절차입니다.",
      "GitHub의 Copilot 설정에서 사용할 계정의 플랜과 조직 정책을 확인합니다. GitHub 계정만 있다고 Copilot 사용이 보장되지는 않습니다.",
      "전송 대상과 조건을 읽고 ‘동의하고 Copilot 연결’을 선택합니다. GitHub 공식 페이지에서 계정을 확인하고 앱 승인(Authorize)을 진행합니다. 비밀번호를 이 사이트에 입력하지 않습니다.",
      "이 사이트로 돌아오면 본인 연결과 전송 동의가 저장되고 이용 조건을 자동 확인합니다. 승인 취소·만료 시에는 저장하지 않으며 다시 시도할 수 있습니다.",
      "조건이 확인되면 바로 대화 화면에서 선택합니다. Free뿐 아니라 개인 유료·Business·Enterprise 구독도 남은 포함 사용량이 있고 초과 사용 중이 아니면 사용할 수 있습니다. 재로그인·같은 계정 재연결에도 기존 동의를 유지하며, 오류·소진 시 다시 확인할 수 있습니다.",
    ],
    warning: "매 요청 전 남은 포함량을 검사하며 소진·초과 사용·정보 미확인 시 차단합니다. 다른 앱의 동시 사용이나 응답 처리 중 소진에 따른 추가 요금까지 앱이 보장하지는 못합니다. GitHub 예산에서 포함량 소진 시 과금 대신 중지하도록 설정하세요. 기존 구독료는 별도이며 앱이 결제 설정을 바꾸지는 않습니다. 대화와 이력은 GitHub 및 Copilot이 Auto로 선택한 모델 제공자로 전송됩니다.",
  },
  {
    id: "openai", name: "ChatGPT", method: "공식 ChatGPT 로그인 · 승인 대기",
    description: "공식 Sign in with ChatGPT로 본인의 ChatGPT 플랜 사용량을 연결하는 방식을 준비 중입니다. 승인 전에는 연결할 수 없습니다.",
    url: "https://developers.openai.com/siwc/quickstart", linkLabel: "Sign in with ChatGPT 공식 안내",
    steps: [
      "공식 Sign in with ChatGPT는 자격이 되는 ChatGPT Plus·Pro 사용자가 본인 플랜 사용량으로 AI 요청을 보내는 OpenAI의 공식 방식입니다.",
      "이 사이트 같은 원격 호스팅 웹은 OpenAI의 별도 승인이 필요하며, 아직 승인되지 않았습니다.",
      "승인 전에는 OpenAI API 키·ChatGPT 쿠키·세션 토큰을 받지 않습니다. API 키는 ChatGPT 구독과 별개의 유료 결제라 이 앱의 무료 사용 정책과 맞지 않습니다.",
      "승인되면 Copilot과 같은 순서(공식 로그인 → 연결 시 동의 저장 → 이용 조건 자동 확인)로 연결하며, 사용자별 본인 계정만 사용합니다.",
      "지금은 GitHub Copilot 또는 OpenRouter 무료 모델 연결을 사용하세요.",
    ],
    warning: "ChatGPT 플랜 사용량은 사용자 간에 합치거나 공유하지 않습니다. 승인 전까지 ChatGPT 대화는 지원하지 않습니다.",
    pending: true,
  },
  {
    id: "gemini", name: "Gemini", method: "Gemini API 키",
    description: "Google AI Studio의 API 키로 연결합니다.",
    url: "https://aistudio.google.com/apikey", linkLabel: "Google AI Studio API 키 발급",
    steps: [
      "이 사이트에 로그인하고 ‘Google AI Studio API 키 발급’을 새 탭에서 엽니다.",
      "Google 계정으로 로그인하고 AI Studio 이용 조건을 확인합니다. 회사·학교 계정은 관리자가 사용을 제한할 수 있습니다.",
      "API Keys에서 키 만들기(Create API key)를 선택하고 사용할 프로젝트를 선택하거나 만듭니다. 프로젝트의 결제·할당량 상태도 확인합니다.",
      "키를 복사해 이 창에 붙여넣고 연결 이름을 정한 뒤 전송 안내를 읽고 ‘동의하고 연결’을 누릅니다. Gemini 웹 로그인 정보나 Gemini CLI 토큰은 입력하지 않습니다.",
      "키 인증과 동의가 자동 저장됩니다. 무료 자격이 확인되지 않으면 호출하지 않으며 내 연결에서 사유를 확인합니다.",
    ],
    warning: "키만으로 프로젝트의 무료 결제 등급을 확인할 수 없어 호출은 차단됩니다. Google AI Pro/Ultra나 Gemini 웹·CLI의 사용량을 공유하는 연결이 아닙니다.",
  },
  {
    id: "anthropic", name: "Claude", method: "Anthropic API 키",
    description: "Claude Console의 개인 API 키로 연결합니다.",
    url: "https://platform.claude.com/settings/keys", linkLabel: "Claude Console API 키 발급",
    steps: [
      "이 사이트에 로그인하고 ‘Claude Console API 키 발급’을 새 탭에서 엽니다.",
      "Claude Console에 로그인하고 본인이 사용할 조직·워크스페이스를 선택합니다. Claude.ai 구독과 Console API 결제는 별개입니다.",
      "API Keys에서 키 만들기(Create Key)를 선택합니다. 키를 만들 권한이 없으면 조직 관리자에게 문의합니다.",
      "새 키를 복사해 이 창에 붙여넣고 연결 이름을 정한 뒤 전송 안내를 읽고 ‘동의하고 연결’을 누릅니다. Claude.ai 쿠키·세션·Claude Code 로그인 토큰은 입력하지 않습니다.",
      "서버가 추론 없이 모델 목록 조회로 확인하고 암호화해 저장합니다. 동의는 저장되지만 유료 호출 미지원 상태는 유지합니다.",
    ],
    warning: "Claude.ai 로그인·구독 토큰을 제3자 앱에서 중개하는 방식은 제공하지 않습니다. 이번 버전은 유료 호출을 지원하지 않아 API 키 저장 후에도 Claude 추론은 차단됩니다.",
  },
  {
    id: "openrouter", name: "OpenRouter", method: "API 키 · 무료 모델",
    description: "기존 무료 모델 연결입니다. 실제 처리업체를 선택합니다.",
    url: "https://openrouter.ai/settings/keys", linkLabel: "OpenRouter API 키 발급",
    steps: [
      "이 사이트에 로그인하고 ‘OpenRouter API 키 발급’을 새 탭에서 엽니다.",
      "OpenRouter에 로그인한 뒤 키 만들기(Create Key)로 본인 키를 발급합니다. 비용 제한은 제공자 설정에서도 확인합니다.",
      "이 창에 연결 이름과 키를 입력하고 무료 모델을 선택합니다. 목록은 공식 가격 정보를 기준으로 조회합니다.",
      "대화·이력·첨부를 보낼 실제 처리업체를 선택하고 전송 안내를 읽은 뒤 ‘동의하고 연결’을 누릅니다.",
      "전송 동의가 저장되고 키 인증·무료 가격·모델·처리업체가 모두 확인되면 바로 사용 가능으로 표시됩니다. 한도나 제공자 장애가 있으면 호출이 제한될 수 있습니다.",
    ],
    warning: "무료 모델의 가용량은 보장되지 않습니다. 유료 모델로 자동 전환하지 않으며, 전송 동의는 언제든 철회할 수 있습니다.",
  },
];

export function isConnectionProvider(value: string): value is ConnectionProvider {
  return connectionProviders.some((entry) => entry.id === value);
}

export const connectionStateLabels: Record<string, string> = {
  reauth_required: "재인증 필요", consent_required: "전송 동의 필요",
  copilot_eligibility_unknown: "이용 조건 다시 확인 필요",
  copilot_check_required: "이용 조건 다시 확인 필요",
  copilot_consent_required: "GitHub Copilot 경유 전송 동의 필요",
  copilot_plan_not_free: "정책 업데이트됨 · 이용 조건 다시 확인 필요",
  copilot_overage_enabled: "이전 판정 · 전송 시 포함량 재확인",
  copilot_overage_in_use: "과금 방지 차단 · 이미 초과 사용 중",
  copilot_free_eligibility_unknown: "포함 사용량 미확인",
  copilot_quota_exhausted: "Copilot 포함 사용량 소진",
  copilot_unavailable: "Copilot 확인 서비스 연결 불가",
  copilot_access_denied: "Copilot 사용 권한 없음",
  copilot_request_failed: "Copilot 요청 실패 · 다시 확인 필요",
  verification_unavailable: "이용 조건 자동 확인 실패",
  paid_calls_disabled: "유료 호출 미지원", free_eligibility_unknown: "무료 자격 미확인",
  available: "사용 가능",
};

export const connectionStateDescriptions: Record<string, string> = {
  reauth_required: "인증이 만료되거나 철회됐습니다. 연결 설정에서 다시 인증해주세요.",
  consent_required: "연결은 저장됐지만 메시지 전송에 동의하지 않았습니다. 연결 설정에서 전송 동의를 켜주세요.",
  copilot_consent_required: "GitHub Copilot 및 Copilot이 선택한 모델 제공자로 대화를 보내는 데 별도 동의가 필요합니다. 연결 설정에서 전송 동의를 확인해주세요.",
  copilot_check_required: "연결 설정은 저장돼 있습니다. 메시지를 전송하면 남은 포함 사용량을 다시 확인합니다. 이용 조건만 먼저 확인할 수도 있습니다.",
  copilot_plan_not_free: "플랜 이름으로 차단하던 정책을 변경했습니다. 앱을 다시 등록할 필요 없이 이용 조건을 다시 확인해주세요.",
  copilot_overage_enabled: "소진 후 초과 사용 허용 설정만으로 차단하던 이전 판정입니다. 메시지를 전송하면 현재 포함량을 다시 확인합니다. 앱을 다시 등록할 필요는 없습니다.",
  copilot_overage_in_use: "GitHub가 이미 초과 사용 중이라고 응답해 전송을 차단했습니다. 포함량이 남았다는 표시만으로 초과 사용 기록을 무시하지 않습니다. 한도 갱신을 기다리거나 다른 연결을 사용하세요.",
  copilot_free_eligibility_unknown: "남은 포함 사용량을 확인할 수 없습니다. 이용 조건을 다시 확인해주세요. 정보가 확인되기 전에는 대화를 보내지 않습니다.",
  copilot_quota_exhausted: "포함 사용량을 소진했습니다. 한도 갱신 후 다시 확인하거나 추가 요금 없는 다른 연결을 사용하세요.",
  copilot_unavailable: "Copilot 이용 조건 조회에 실패했습니다. 잠시 후 다시 확인해주세요.",
  copilot_access_denied: "GitHub가 Copilot 사용을 허용하지 않았습니다. 계정 자격과 조직 정책을 확인해주세요.",
  copilot_request_failed: "Copilot 요청을 완료하지 못했습니다. 이용 조건을 다시 확인해주세요.",
  verification_unavailable: "이용 조건 자동 조회에 실패해 전송을 차단했습니다. 잠시 후 다시 확인해주세요.",
  paid_calls_disabled: "이 제공자는 현재 인증·연결 저장만 지원하며 유료 API 대화는 허용하지 않습니다. 대화 가능한 다른 연결을 추가해주세요.",
  free_eligibility_unknown: "이 연결의 무료 사용 조건을 확인할 수 없습니다. 연결 설정과 제공자의 무료 등급을 확인해주세요.",
};
