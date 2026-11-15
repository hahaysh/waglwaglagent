# 제공자 정책

검토 기준일: 2026-11-15. 외부 제공자의 가격·약관·카탈로그·상태는 변경될 수 있으며 다음 내용은 영구적인 무과금 보증이 아닙니다.

## OpenRouter

공식 API만 사용합니다. `/api/v1/models`의 명시적 `:free` 모델 중 모든 조회된 가격 항목이 유한한 0이고 출력이 텍스트인 모델을 선택합니다. `/models/{model}/endpoints`에서 무료 가격과 `max_tokens` 지원을 확인하고, 표시 이름이 아닌 실제 `tag`를 전송 동의의 대상으로 저장합니다.

요청의 `provider.only`와 `provider.order`는 허용된 단일 처리업체로 제한합니다. `allow_fallbacks=false`, `require_parameters=true`, 지원되는 가격 상한 0을 적용하며 유료 fallback과 플러그인은 추가하지 않습니다. 처리업체가 없거나 가격 조회가 실패하면 허용 범위를 완화하지 않습니다. 공용 무료 카탈로그 캐시는 최대 60초이며 키나 개인 사용량을 포함하지 않습니다.

`/api/v1/key`의 `free_model_daily_requests`가 제공되는 경우 공식 조회 스냅샷으로만 표시합니다. 고정된 보편적 한도나 잔여량을 계산해 사실처럼 제시하지 않습니다. 키 검증 성공은 다음 요청의 성공이나 결제 상태를 보증하지 않습니다. 제공자의 실제 가격 적용과 무료 태그 보장은 외부 신뢰 경계입니다.

- [공식 한도](https://openrouter.ai/docs/api/reference/limits)
- [무료 모델](https://openrouter.ai/docs/guides/routing/model-variants/free)
- [처리업체 선택](https://openrouter.ai/docs/guides/routing/provider-selection)
- [약관](https://openrouter.ai/terms)
- [개인정보](https://openrouter.ai/privacy)

## Gemini Developer API

API 키로 모델 조회를 인증할 수 있어도 프로젝트의 무료 결제 등급을 지속 검증할 수 있는 것은 아닙니다. 기본 상태는 `unverified`이며 엄격한 무료 경로에서 차단합니다. 소비자 Gemini 웹 세션이나 구독은 API 권한으로 취급하지 않습니다.

로컬 테스트용 운영자 검토는 키 SHA-256 지문별 허용 모델과 만료 시각으로 제한됩니다. 사용자가 임의로 적은 프로젝트 이름을 무료 자격의 증거로 사용하지 않습니다. 이 검토 경로는 기본 비활성이며 production 설정에서 금지됩니다. 현재 웹에서도 검증되지 않은 Gemini는 활성 대화 연결로 표시하지 않습니다.

Gemini 한도는 키가 아닌 프로젝트·모델에 적용되므로 동일 프로젝트 키를 추가해 할당량이 늘어난다고 간주하지 않습니다. 무료 계층의 데이터 이용 정책을 확인해야 하며 민감한 정보를 보내지 않도록 안내해야 합니다.

- [공식 가격](https://ai.google.dev/gemini-api/docs/pricing)
- [공식 한도](https://ai.google.dev/gemini-api/docs/rate-limits)
- [추가 약관](https://ai.google.dev/gemini-api/terms)

## 로그인 연결과 API 키

사이트 GitHub 로그인은 작업공간 소유자를 확인하며 Copilot 연결과 구별합니다. 별도 Copilot OAuth App의 `read:user`·PKCE S256·일회성 state·소유자/브라우저 바인딩·10분 만료를 적용합니다. 중앙 설정 모드에서 사용자 토큰은 Key Vault에 저장하고 DB에는 버전 고정 참조만 남기며 서버의 GitHub CLI·다른 사용자 자격으로 대체하지 않습니다. 발급된 경우에만 refresh token을 처리하며 새 토큰/만료/버전을 함께 갱신합니다.

Copilot은 `github-copilot-sdk==1.0.34`와 SDK 지정 런타임 `1.0.112`를 사용합니다. 각 요청에서 공식 `session.gitHubAuth.getStatus`와 `account.getQuota`를 조회합니다. 인증됨·`chat` 및 `premium_interactions` quota 존재·잔여량·초과 사용 0을 모두 확인해야 Auto 대화를 허용합니다. 유한 quota는 잔여 비율뿐 아니라 `usedRequests < entitlementRequests`도 만족해야 합니다. Free·개인 유료·Business·Enterprise 등 플랜 이름은 표시 정보이며 허용/차단 근거가 아닙니다. `overageAllowedWithExhaustedQuota`는 소진 후 정책이므로 이 설정만으로 남은 포함량을 차단하지 않습니다. 현재 초과 사용이 기록되거나 포함량이 소진되거나 정보가 미확인인 경우에는 차단합니다. 기존 구독료는 별도입니다.

내부 `usage_policy="free_only"`는 기존 저장 형식을 유지하되, Copilot에서는 위의 **현재 남은 포함량으로만 호출**한다는 의미입니다. OpenAI·Anthropic API의 유료 호출을 활성화하지 않습니다. 이전 `copilot_plan_not_free`·`copilot_overage_enabled` 판정은 재확인 필요로 표시하고, 동의된 OAuth 연결은 전송 시 서버에서 공식 조회 후 갱신합니다. 과거 차단 스냅샷만으로 웹 전송 버튼을 영구 비활성화하지 않습니다.

전송 동의에는 GitHub Copilot 및 Copilot이 선택한 모델 제공자 경유를 명시합니다. 과거 인증 전용 연결의 빈 처리업체 동의는 추론 동의로 승격하지 않습니다. 매 요청 직전과 실제 SDK 메시지 전송 직전에 무료 조건을 다시 조회하며, 동의 철회·연결 삭제 시 중지합니다. 응답 시작 전 한도 소진은 자동 모드에서만 다른 동의된 무료 서비스로 전환합니다. 수동으로 선택한 연결은 다른 제공자로 fallback하지 않습니다. 일부 응답 이후에는 합치지 않습니다.

확인·추론 모두 명시적 사용자 토큰, `use_logged_in_user=False`, 격리된 임시 홈/작업 디렉터리, stdio 자식 프로세스, `mode="empty"`, 빈 도구 허용목록과 권한 거절을 사용합니다. 호스트의 토큰·홈·MCP·스킬·사용자 설정·파일/셸 도구를 상속하지 않습니다. 프로세스 종료 후 임시 이력을 삭제하며 SDK 예외 원문·계정 전체 응답·토큰을 사용자에게 반환하지 않습니다.

현재 Copilot은 AI credits 기반 과금이므로 오래된 모델 배율이나 SDK 세션 예산의 soft cap을 무과금 근거로 쓰지 않습니다. 잔여량 검사는 계정 전체의 원자적 예산 예약이 아니며, 다른 앱·조직 구성원의 동시 사용과 한 응답 처리 중 소진으로 인한 추가 요금까지 보증하지 않습니다. 이를 차단하려면 제공자에서 포함량 소진 시 과금 대신 중지하도록 예산을 설정해야 합니다. 앱은 예산 변경·초과 과금 활성화·소진 후 유료 API 전환을 하지 않으며, 단순히 사용자별 소비 한도를 `$0`으로 설정하라고 안내하지 않습니다. 실제 응답 검증과 모의 SDK 테스트는 구별해야 하며, OAuth 승인만으로 대화 성공을 주장하지 않습니다.

OpenAI 공식 Sign in with ChatGPT는 존재합니다. 공개 OSS의 로컬 흐름은 이용할 수 있으나 원격 호스팅 앱은 OpenAI의 별도 승인이 필요합니다. 따라서 승인 전에는 연결 화면에 승인 대기 안내만 표시하고 OpenAI API 키를 새로 받지 않으며, ChatGPT 구독·무료 웹 할당량을 가져오지 않습니다. 승인되면 사용자별 본인 계정 OAuth 어댑터로 추가하며 플랜 사용량을 합치거나 공유하지 않습니다. Gemini CLI OAuth를 제3자 앱의 Code Assist 호출에 재사용하지 않으며 Claude.ai 소비자·Claude Code 로그인 토큰도 수집·중개하지 않습니다.

OpenAI·Anthropic 키는(기존 API 호환용 및 Anthropic) 공식 모델 목록 GET으로만 확인합니다. Gemini도 기존 모델 목록 조회를 사용합니다. 인증 확인 중 추론을 발생시키지 않으며 인증 성공을 무료 결제 등급의 증거로 사용하지 않습니다. OpenAI/Anthropic 유료 추론은 서버의 후보 허용목록에서 제외합니다.

모든 새 연결은 요청이 동의를 주장해도 전송 미동의로 저장합니다. 같은 OAuth 계정 재인증 시 기존 연결을 갱신하고 동의를 다시 받습니다. 로컬 해제와 원격 토큰 철회는 별개이며 원격 철회 실패를 사용자에게 알립니다. API 키는 다른 앱에서 사용될 수 있어 발급처에서 임의 폐기하지 않습니다.

- [Copilot SDK의 GitHub OAuth](https://github.com/github/copilot-sdk/blob/main/docs/setup/github-oauth.md)
- [Copilot 개인 플랜 과금](https://docs.github.com/en/copilot/concepts/billing-and-usage/individuals/billing)
- [Copilot 조직·Enterprise 예산](https://docs.github.com/en/copilot/concepts/billing-and-usage/organizations-and-enterprises/budgets)
- [공식 SDK 사용량·과금 조회](https://github.com/github/copilot-sdk/blob/v1.0.34/docs/features/usage-and-billing.md)
- [GitHub OAuth와 토큰 갱신](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps)
- [Sign in with ChatGPT](https://developers.openai.com/siwc/quickstart)
- [OpenAI 모델 목록](https://developers.openai.com/api/reference/resources/models/methods/list)
- [Gemini CLI 약관 안내](https://geminicli.com/docs/resources/tos-privacy/)
- [Claude 인증·준수 정책](https://code.claude.com/docs/en/legal-and-compliance)
- [Anthropic 모델 목록](https://platform.claude.com/docs/en/api/models/list)

## 전환·중지·데이터

한 요청은 사전 검사 최대 15초와 이를 포함하는 API 처리 기한 60초, 후보 최대 3개로 제한됩니다. 429는 할당량 그룹, 일시적인 장애는 해당 연결·엔드포인트를 잠시 차단합니다. 알려지지 않은 reset을 계산하지 않습니다. 현재 Retry-After는 숫자 초 단위만 처리하며 HTTP-date 형식 지원은 남은 작업입니다.

전환은 첫 텍스트 출력 전의 일시 장애·한도 소진에만 허용됩니다. 안전 정책 거절·인증 오류·잘못된 요청·응답 시작 뒤에는 전환하지 않습니다. 실제 시도 직전에 소유권·동의·무료 증거·처리업체·차단 상태를 다시 확인합니다. 동의 철회는 제공자 목록 조회 장애와 무관하게 가능하며 진행 중 요청을 취소합니다.

중앙 설정 모드에서 API 키와 OAuth 토큰 묶음은 Key Vault에 저장하고 DB에는 사용자/레코드에서 유도한 이름과 고정 버전의 참조만 보관합니다. 비밀 조회·쓰기 실패 시 차단하며 원문 조회·내보내기·브라우저 저장 기능을 제공하지 않습니다. PKCE 임시 verifier와 이전 호환 비밀은 사용자/레코드 바인딩 AES-GCM을 사용합니다. 제목·대화·첨부·연결 이름도 Key Vault의 기존 키를 참조해 AES-GCM으로 암호화합니다. 각 시도의 모델·처리업체·동의 버전·상태·관측 토큰 수 등 조회 메타데이터는 DB에 남습니다. 토큰 수가 없으면 비용이나 사용량을 0으로 추정하지 않습니다. [운영 설정과 백업 제한](central-configuration.md)을 참고하세요.

첨부는 PNG·JPEG·WebP 정지 이미지와 UTF-8 텍스트·코드만 허용합니다. 서버가 base64·파일명·실제 이미지 형식·디코딩·픽셀 수·문자 인코딩과 크기를 검사합니다. 요청당 3개·합계 4MB, 이미지당 2MB·16MP, 텍스트당 32KB이며 대화 전체 텍스트 40KB·이미지 8MB를 초과하면 호출하지 않습니다. 이미지는 현재 Copilot으로만 라우팅하고 공식 SDK `blob`으로 보내며 파일/셸 도구를 켜거나 사용자 지정 경로를 읽지 않습니다. 이미지 base64를 일반 프롬프트에 넣어 이미지 분석을 가장하지 않습니다. 문서 텍스트와 이전 첨부는 해당 역할의 대화 문맥으로 다시 전달합니다.

첨부는 기존 대화와 같은 DB에 암호화해 저장하고 인증된 소유자의 조회에서만 복호화해 반환합니다. 외부 공개 URL을 발급하지 않으며 대화를 삭제하면 첨부도 삭제됩니다. PDF·Office·압축 파일·애니메이션·도구 실행은 지원하지 않습니다.

 소유자가 확인된 대화 조회에서만 반환하고 외부 공개 URL을 발급하지 않으며, 사용자 요청의 전송 동의·제공자 선택·대화 삭제 정책을 따릅니다. 브라우저는 서버를 거치지 않은 외부 이미지 URL을 표시하지 않으며 첨부한 검증 이미지의 data URL만 미리보기로 표시합니다. PDF·Office·압축 파일·애니메이션·도구 실행은 지원하지 않습니다.

중지는 스트림을 닫고 잠금을 해제하지만 이미 전송한 내용이나 제공자의 처리를 회수할 수 없습니다. 실패·취소 요청도 할당량을 소비할 수 있습니다. 앱의 중복 request ID 차단은 업스트림 exactly-once 실행 보증이 아니며, 네트워크 단절 후 결과가 불명확할 수 있습니다. 계정별 키나 무료 허용량의 공유·풀링은 금지됩니다.

## 사용한 기반

LiteLLM MIT core SDK를 요청별 키로 호출합니다. 별도 LiteLLM Proxy·공유 Router pool은 사용하지 않습니다. SDK의 키·허용 처리업체 전달은 실제 설치 버전의 HTTP 경계를 모의하여 검사했고 외부 추론은 수행하지 않았습니다. LibreChat 등은 기능 비교 참고였으며 해당 프로젝트의 UI/코드를 복사하지 않았습니다. 로컬 Manrope·Noto Sans KR 폰트와 제공자 사이트 favicon을 식별용으로 사용합니다.

공개 서비스는 각 제공자 및 실제 처리업체의 약관·데이터 보관/학습·상업적 사용·지역·연령 조건을 별도로 검토해야 합니다. 유료 API·프로모션 크레딧·소비자 브라우저 세션 중개·키 재판매·새 계정 자동 생성은 이 구현에 포함되지 않습니다.
