# waglwaglagent

개인 API 키로 공식 무료 AI 모델을 사용하는 웹 작업공간입니다. 각 사용자의 키·대화·사용 기록은 소유자에게만 연결됩니다. 등록한 제공자와 실제 처리업체 중 사전에 전송을 허용한 곳만 사용하며, 유료 모델로 자동 전환하지 않습니다.

**현재 상태: 로컬 검증용 MVP. 공개 서비스 출시 완료가 아닙니다.** GitHub OAuth 로그인과 실키 추론, 컨테이너 실행 및 운영 보안 검증은 별도로 필요합니다.

## 구현 범위

- GitHub 사이트 로그인, 제공자 선택, Copilot OAuth·개인 API 키 연결 자동 저장·재확인·해제.
- 무료 OpenRouter 모델과 실제 처리업체 선택, 전송 동의, 연결 우선순위.
- SSE 대화, 중지, 대화 이력 삭제, 요청별 모델·처리업체·토큰 기록.
- 무료 가격·자격·동의 확인 실패 시 차단. 안전 정책 거절과 인증 오류는 자동 전환하지 않음.
- 응답이 일부라도 시작된 뒤에는 다른 모델 응답을 이어 붙이지 않음.
- Copilot은 Free·개인 유료·Business·Enterprise 등 플랜 이름과 관계없이 공식 SDK로 **남은 구독 포함량·초과 사용 0**이 확인된 계정으로 실제 대화합니다. 소진 후 초과 사용 허용 설정만으로 현재 포함량을 차단하지 않습니다. 계정 전체의 추가 과금 차단은 제공자의 예산 설정이 필요하며 기존 구독료는 별도입니다. OpenAI·Anthropic은 인증·저장까지만 지원하며 Gemini도 무료 결제 등급 미확인 시 차단합니다. 쿠키·HAR·스크래핑·키 공유는 제외합니다.

## 로컬 실행

Windows PowerShell, Python 3.12, Node.js 22.18 이상 또는 24 LTS를 사용합니다. 현재 검증 환경은 Python 3.12와 Node.js 26입니다. 테스트의 직접 TypeScript 실행에는 최신 Node가 필요합니다.

운영 비밀은 Key Vault, 일반 설정은 `waglwaglagent-config` App Configuration에서 읽습니다.
초기 운영자 설정·기존 데이터 이전은 [중앙 설정 안내](docs/central-configuration.md)를 따르세요.
`init-local.ps1`은 이미 준비된 중앙 설정에 접근하는 부트스트랩만 생성하며 기존 환경 파일을 덮어쓰지 않습니다.

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install --require-hashes -r services/api/requirements.lock
az login --tenant "<tenant-id>"
.\scripts\init-local.ps1 -TenantId "<tenant-id>"
.venv/Scripts/python -m uvicorn app.main:app --app-dir services/api --host 127.0.0.1 --port 8000
```

별도 터미널에서 웹을 실행합니다.

```powershell
Set-Location apps/web
npm ci
npm run dev -- --hostname 127.0.0.1 --port 3000
```

웹: <http://localhost:3000> · API 상태: <http://127.0.0.1:8000/health>

기본 SQLite 데이터는 루트의 `.local/wagl.db`에 저장됩니다. 제목·메시지·첨부·연결 이름은 암호화하고, 연결 토큰은 Key Vault 참조로 저장합니다. 로컬 모드는 API 한 프로세스 전용이며 다중 서버 배포에 사용하지 않습니다. 포트를 변경하면 App Configuration의 `AUTH_URL`, `WAGL_PUBLIC_URL`, OAuth callback과 실행 포트를 함께 변경하고 서버를 재시작합니다.

### GitHub OAuth

GitHub **Settings → Developer settings → OAuth Apps**에서 앱을 등록합니다.

- Homepage URL: `http://localhost:3000`
- Authorization callback URL: `http://localhost:3000/api/auth/callback/github`
- 생성한 Client ID와 Client secret을 Key Vault에 등록하고 App Configuration `local-web`의 `AUTH_GITHUB_ID`, `AUTH_GITHUB_SECRET`을 해당 비밀의 네이티브 참조로 설정한 뒤 웹을 재시작합니다. 환경 파일에 비밀을 직접 넣지 않습니다.

비밀 값은 채팅으로 전달하지 마세요. OAuth가 설정되지 않아도 화면은 열리지만 로그인·키 등록·AI 전송은 우회되지 않습니다. Auth.js는 버전을 고정한 v5 beta를 사용하므로 공개 출시 전 별도 안정성 검토가 필요합니다.

### 개인 연결

**내 연결 → 연결 추가**에서 GitHub Copilot / ChatGPT / Gemini / Claude / OpenRouter를 선택합니다. 서비스를 선택할 때마다 해당 인증의 5단계 설명과 공식 발급 링크가 **입력 폼 오른쪽 안내 패널에 자동으로 표시**됩니다. 안내를 옆에 두고 입력할 수 있으며, 작은 화면에서는 폼 아래에 표시합니다. 공식 페이지는 새 탭으로 열려 입력 창을 유지합니다. 로그인 전에도 안내를 볼 수 있으며, 인증·저장에는 사이트 로그인이 필요합니다. 사이트 로그인 후에는 선택한 제공자로 돌아옵니다.

**연결 저장 ≠ 메시지 전송 동의 ≠ 무료 사용 보장**입니다. 모든 새 연결은 서버가 비활성으로 저장합니다. 저장 후 **내 연결 → 해당 연결의 전송 동의**를 켜더라도 인증·무료 자격·모델·처리업체가 확인되지 않으면 호출하지 않습니다.

| 선택 항목 | 연결 방식 | 이번 버전의 실제 AI 대화 |
|---|---|---|
| GitHub Copilot | GitHub 공식 OAuth 승인 후 자동 저장 | 공식 SDK Auto: 남은 구독 포함량 확인 시 지원 (유료·조직 플랜 포함), 소진·초과 사용 중이면 차단 |
| ChatGPT | OpenAI API 키 | 미지원: 유료 호출 비활성 |
| Gemini | Google AI Studio API 키 | 무료 등급 미확인 시 차단 |
| Claude | Anthropic API 키 | 미지원: 유료 호출 비활성 |
| OpenRouter | API 키 + 무료 모델 + 실제 처리업체 | 동의·무료 검증 통과 시 사용 가능 |

#### 처음 이용할 때: 사이트 로그인

1. **연결 추가**에서 서비스를 선택하고 단계별 안내를 읽습니다.
2. **GitHub로 사이트 로그인**을 누르고 GitHub 공식 페이지에서 로그인·승인합니다. 이 로그인은 개인 작업공간의 소유자를 확인하는 절차이지 Copilot 연결이 아닙니다.
3. 돌아온 연결 창에서 아래 제공자별 절차를 진행합니다.
4. **사이트 로그인 준비 중**이면 일반 사용자가 해결할 수 있는 API 키 문제가 아닙니다. 운영자가 위의 GitHub OAuth 설정을 완료해야 합니다. 비밀번호·일회용 인증 코드·Client secret을 채팅에 보내지 마세요.

#### GitHub Copilot: 로그인으로 연결

1. [GitHub Copilot 설정](https://github.com/settings/copilot)에서 사용할 계정·플랜·조직 정책을 확인합니다. GitHub 계정 보유만으로 Copilot 사용 자격이 생기지는 않습니다.
2. 이 사이트의 **연결 추가 → GitHub Copilot**을 선택합니다.
3. **GitHub로 Copilot 연결**을 누릅니다. **서비스 연결 준비 중**이면 운영자가 아래의 별도 Copilot OAuth 앱 설정을 해야 하며 버튼은 활성화되지 않습니다.
4. GitHub 공식 페이지에서 사용할 계정과 요청 권한을 확인하고 **Authorize**로 승인합니다. 비밀번호를 이 사이트에 입력하지 않습니다.
5. 사이트로 돌아오면 연결이 자동 저장됩니다. **내 연결**에서 GitHub Copilot 경유 전송 동의를 켜고 **이용 조건 다시 확인**을 누릅니다. 확인 시 대화 프롬프트는 보내지 않습니다.
6. **대화 → 대화에 사용할 연결**에서 해당 연결을 선택하고 메시지를 전송합니다. 이전 플랜·초과 사용 허용 설정 때문에 차단된 연결도 재등록 없이 전송 시 현재 포함량을 재확인합니다. **자동**은 동의한 무료 모델·포함량 연결 사이에서만 전환하며, 특정 연결을 고르면 다른 서비스로 넘어가지 않습니다. 매 전송 전 남은 포함량과 초과 사용 여부를 다시 확인합니다.

승인을 취소하거나 인증 흐름이 만료되면 새 연결을 저장하지 않습니다. **Copilot 다시 연결**은 같은 계정이면 기존 연결을 갱신하고 전송 동의를 다시 받습니다. **이용 조건 다시 확인**은 계정 인증과 공식 SDK의 플랜·한도를 조회하며, 제공자가 refresh token을 발급한 만료형 토큰만 갱신합니다. 갱신 권한이 없거나 철회됐으면 다시 연결하세요. 과거 인증 전용 연결도 새로운 GitHub Copilot 경유 전송 동의가 필요합니다. 플랜만으로 차단됐던 연결은 재등록 없이 이용 조건을 다시 확인하면 됩니다.

상태별 조치:

대화 입력창 위에도 전송할 수 없는 연결의 상태·이유·해결 방법이 표시됩니다. **이용 조건 다시 확인**으로 대화창에서 직접 상태를 조회하거나 **연결 설정 열기**로 동의·인증을 확인할 수 있습니다. 상태 조회는 대화를 보내지 않으며 입력한 초안도 지우지 않습니다. 조건이 확인되면 전송 버튼이 활성화되며 메시지는 직접 전송해야 합니다. 연결 조회 장애도 별도로 표시하고 다시 불러올 수 있습니다.

새 대화의 제안은 앱 검증용입니다. **연결 테스트**는 짧은 응답, **스트리밍·중지 테스트**는 여러 줄의 한글 출력과 중지, **서비스 전환·대화 이력 테스트**는 테스트 단어를 기억시킨 뒤 연결을 바꾸어 이전 이력이 전달되는지 확인합니다. 마지막 테스트의 응답 후 “테스트 단어가 뭐였지?”를 직접 전송하세요. 제안을 선택하는 것만으로는 호출하지 않으며, 전송 시 포함 사용량이 소모될 수 있습니다. 모델이 말하는 한도·모델명은 공식 조회나 앱 기록을 대신하지 않습니다.

#### 스크린샷·파일 첨부

- 입력창의 **클립 버튼**으로 파일을 선택하거나 입력창에 끌어놓습니다. 스크린샷은 복사 후 입력창에서 **Ctrl+V**로 붙여넣을 수 있습니다.
- **이미지:** PNG·JPEG·WebP, 파일당 2MB·16메가픽셀 이하의 정지 이미지. 현재 이미지 분석은 GitHub Copilot 연결만 지원하며 이미지가 포함된 이력을 다른 텍스트 전용 제공자로 몰래 전송하지 않습니다.
- **문서:** UTF-8 인코딩의 TXT·Markdown·CSV·JSON·로그·일반 코드 파일, 파일당 32KB 이하. PDF·Word·Excel·압축 파일은 아직 지원하지 않습니다.
- 한 메시지에 **최대 3개·합계 4MB**입니다. 전송 전 미리보기·파일명을 확인하고 X로 제거할 수 있습니다. 첨부만으로도 전송할 수 있지만 원하는 작업을 함께 적는 것을 권장합니다. 선택·붙여넣기만으로는 AI를 호출하지 않습니다.
- 거절된 요청은 입력과 첨부를 유지합니다. 첨부는 메시지와 함께 서버 DB에 저장되며 소유자만 이력에서 열고 다운로드할 수 있습니다. 대화를 삭제하면 첨부도 삭제됩니다. 이후 질문에도 기존 첨부를 다시 전달하며 대화의 텍스트 40KB·이미지 합계 8MB 한도를 넘으면 새 대화를 시작해야 합니다.
- 파일은 실행하지 않습니다. Copilot에는 이미지 내용을 공식 SDK의 inline blob으로 보내며 서버 경로·파일 읽기 도구를 허용하지 않습니다. 텍스트 문서는 대화 문맥으로 전달합니다. 대화 전송 동의는 첨부에도 적용되므로 개인정보·비밀이 포함된 파일은 전송하지 마세요. 이미지·문서 처리에도 구독 사용량이 소모될 수 있습니다.
- 기존 설치는 API 재시작 전에 `python -m alembic -c services/api/alembic.ini upgrade head`로 첨부 컬럼 마이그레이션을 적용합니다. 운영 환경은 기존 시작 명령에서 자동 적용합니다.

- **이용 조건 다시 확인 필요**: 포함량 이용 조건을 다시 조회해야 합니다. 유료·조직 플랜이라는 이유만으로는 차단하지 않습니다.
- **이전 판정 · 전송 시 포함량 재확인**: `overageAllowedWithExhaustedQuota`는 소진 후 추가 사용 설정이지 현재 초과 과금 중이라는 뜻이 아닙니다. 이 설정만으로 차단하지 않으며 실제 잔여량이 있고 초과 사용이 0이면 전송합니다.
- **과금 방지 차단 · 이미 초과 사용 중**: 공식 quota에 초과 사용이 기록되어 있어 호출하지 않습니다. 다른 연결을 사용하거나 한도 갱신을 기다리세요.
- **포함 사용량 미확인**: 공식 응답에 필수 정보가 없거나 형식이 바뀌었습니다. 추측한 잔액으로 대체하지 않습니다.
- **포함 사용량 소진**: 추가 요금 없는 다른 연결을 수동 선택하거나 갱신을 기다립니다. 응답 일부가 출력된 경우에는 다른 서비스의 답을 이어 붙이지 않습니다.

Copilot은 플랜 종류에 관계없이 공식 **Auto 모델 선택**을 사용합니다. 대화와 기존 이력을 GitHub 및 Copilot이 선택한 모델 제공자로 보내는 경로이며, Claude/Gemini 소비자 계정의 무료 한도를 직접 합치는 기능은 아닙니다. 다른 서비스의 소비자 구독 연결은 아직 지원하지 않습니다.

**과금 보호의 범위:** 앱은 전송 직전 포함량을 확인하고 소진·초과 사용·조회 실패 시 중지하지만, 다른 앱·조직 구성원의 동시 사용이나 한 응답 처리 중 소진까지 원자적으로 예약하지는 못합니다. 따라서 앱의 잔여량 검사만으로 추가 과금 0을 보증하지 않습니다. 이를 확실히 차단하려면 [GitHub 예산](https://github.com/settings/billing/budgets)에서 포함량 소진 후 과금 대신 중지하도록 설정하세요. 조직의 사용자별 소비 한도와 추가 과금 예산은 다르며, 사용자별 한도를 무조건 `$0`으로 설정하면 포함량까지 차단될 수 있습니다. 앱은 결제·조직 정책을 변경하거나 유료 API로 우회하지 않습니다. [조직·Enterprise 예산의 공식 설명](https://docs.github.com/en/copilot/concepts/billing-and-usage/organizations-and-enterprises/budgets)을 참고하세요.

#### 운영자: 공식 Copilot 런타임

Python 의존성에 `github-copilot-sdk==1.0.34`가 고정되어 있으며 이 SDK가 지정하는 런타임은 `1.0.112`입니다. API 의존성을 설치한 환경에서 최초 한 번 `python -m copilot download-runtime`을 실행합니다. Docker 이미지는 빌드 시 다운로드합니다. 런타임 다운로드에는 GitHub에 대한 네트워크 접근과 캐시 디렉터리 쓰기 권한이 필요합니다. 공용 `copilot login`이나 서버 운영자의 토큰은 사용하지 않습니다.

각 확인·대화 요청마다 별도 stdio 프로세스와 임시 저장소를 사용합니다. `mode="empty"`, 빈 도구 허용목록, 모든 권한 거절, 설정/파일 훅/셸/스킬 발견 비활성화, 명시적 사용자 OAuth 토큰을 적용합니다. 종료·중지 시 소유한 프로세스를 정리하고 임시 이력을 삭제합니다. 장기 대화 이력은 기존 앱 DB에서 관리합니다. SDK 세션 예산은 soft cap이므로 무료 근거로 사용하지 않습니다.

#### ChatGPT: OpenAI API 키로 연결

1. [OpenAI Platform API Keys](https://platform.openai.com/api-keys)를 열고 로그인합니다. ChatGPT 웹 계정의 무료 사용량이나 Plus/Pro 구독과 API 결제는 별개입니다.
2. 사용할 조직·프로젝트를 선택하고 **Create new secret key**로 본인 키를 만듭니다.
3. 제한된 키를 사용하는 경우 모델 목록 조회 권한이 있어야 합니다. 키가 한 번만 표시되면 본인의 안전한 비밀 저장소에 보관하세요.
4. 이 사이트의 **연결 추가 → ChatGPT**에서 연결 이름과 키를 입력하고 **키 확인 후 저장**을 누릅니다.
5. 모델 목록 조회로 인증이 확인되면 암호화해 자동 저장합니다. 저장 후 전송 동의 및 **유료 호출 미지원** 상태를 확인합니다. 확인용 프롬프트나 유료 추론은 보내지 않습니다.

공식 **Sign in with ChatGPT**는 존재하지만 로컬 OSS 연결과 원격 호스팅 승인은 별도입니다. 이번 원격 호스팅용 구현에는 승인되지 않은 ChatGPT 로그인 버튼이나 구독 토큰 우회 연결을 제공하지 않습니다.

#### Gemini: Google AI Studio API 키로 연결

1. [Google AI Studio API Keys](https://aistudio.google.com/apikey)에 Google 계정으로 로그인하고 이용 조건을 확인합니다. 회사·학교 계정은 관리자가 제한할 수 있습니다.
2. **Create API key**에서 사용할 프로젝트를 선택하거나 만듭니다. 프로젝트의 결제·할당량·무료 등급 조건도 확인합니다.
3. 발급한 키를 복사합니다. Gemini 웹의 쿠키·비밀번호·Gemini CLI OAuth 토큰을 복사하는 절차가 아닙니다.
4. 이 사이트의 **연결 추가 → Gemini**에서 연결 이름과 API 키를 입력하고 **키 확인 후 저장**을 누릅니다.
5. 저장된 연결에서 별도로 전송 동의를 설정합니다. 키 인증이 성공해도 **무료 자격 미확인**이면 대화는 차단됩니다.

Google AI Pro/Ultra 구독이나 Gemini 웹·CLI 사용량을 가져오지 않습니다. 현재 일반 키만으로 프로젝트 무료 결제 등급을 확인할 수 없으므로 등록만으로 무료 호출을 보장하지 않습니다.

#### Claude: Anthropic API 키로 연결

1. [Claude Console API Keys](https://platform.claude.com/settings/keys)에 로그인합니다. Claude.ai Free/Pro/Max 구독과 Console API 결제는 별개입니다.
2. 사용할 조직·워크스페이스를 선택합니다. 키 생성 메뉴가 없거나 권한 오류가 나면 조직 관리자에게 문의합니다.
3. **Create Key**로 본인 API 키를 발급합니다. Claude.ai 세션·쿠키·Claude Code 로그인 토큰을 대신 사용하지 않습니다.
4. 이 사이트의 **연결 추가 → Claude**에서 연결 이름과 키를 입력하고 **키 확인 후 저장**을 누릅니다.
5. 서버가 추론 없이 모델 목록 조회로 확인한 뒤 암호화해 자동 저장합니다. **유료 호출 미지원** 상태를 확인합니다. 현재는 키를 저장해도 Claude 대화를 실행하지 않습니다.

Claude.ai 소비자 로그인·구독 토큰을 제3자 앱에서 수집·중개하는 연결은 제공하지 않습니다.

#### OpenRouter: 지금 사용할 무료 모델 연결

1. [OpenRouter API Keys](https://openrouter.ai/settings/keys)에 로그인하고 **Create Key**로 본인 키를 만듭니다. 제공자 측 비용 제한과 이용 조건도 확인합니다.
2. 이 사이트의 **연결 추가 → OpenRouter**에서 연결 이름과 키를 입력합니다.
3. **무료 모델**에서 모델을 선택하고 무료 가격이 확인된 **실제 처리업체**를 선택합니다. 모델·처리업체 조회가 실패하면 임의 값으로 우회하지 말고 다시 시도합니다.
4. **키 확인 후 저장**을 누릅니다. 연결은 전송 동의 없이 저장됩니다.
5. **내 연결**에서 해당 연결의 **전송 동의**를 켭니다. 메시지와 대화 이력이 선택한 처리업체로 전송됨을 확인하세요. **사용 가능**으로 표시되면 대화 화면에서 전송합니다.

작은 우선순위 값부터 시도하며, 무료 카탈로그에 있더라도 한도·장애로 호출이 실패할 수 있습니다. 유료 모델로 자동 전환하지 않습니다.

#### 오류·해제와 저장 위치

- **키 확인 불가**: 키를 발급한 서비스와 선택한 카드가 같은지, 복사한 값에 공백이 없는지 확인합니다.
- **모델 목록 조회 권한 없음**: 조직·프로젝트·키 권한을 확인합니다. 유료 결제를 켜거나 제한을 무조건 해제하라는 의미가 아닙니다.
- **확인 서비스에 연결 불가**: 잠시 후 재시도합니다. 장애 중인 새 키를 정상 연결로 저장하지 않습니다.
- **재인증 필요**: Copilot은 다시 연결하고, API 키는 발급처 상태를 확인합니다. 필요하면 기존 연결을 삭제한 후 새 키를 등록합니다.
- **연결 삭제**: 이 사이트의 암호화 비밀과 연결을 삭제하며 대화 이력 삭제와는 별개입니다. Copilot은 GitHub 토큰 철회도 시도합니다. 철회 실패 안내가 나오면 GitHub **Settings → Applications → Authorized OAuth Apps**에서 직접 철회하세요.
- API 키는 다른 앱에서도 쓰일 수 있으므로 이 사이트에서 삭제해도 발급처의 키 자체를 폐기하지 않습니다. 완전 폐기가 필요하면 발급처 API Keys에서 직접 삭제하세요.

연결 메타데이터와 버전 고정 Key Vault 참조는 DB에 저장합니다. 로컬은 SQLite, 운영은 PostgreSQL이며 제목·메시지·첨부·연결 이름은 AES-GCM으로 암호화합니다. 브라우저 저장소·사이트 세션 JWT·API 응답에는 키/제공자 토큰을 넣지 않습니다. 운영 비밀과 사용자 연결 비밀은 Key Vault, 일반 설정은 App Configuration에서 읽습니다. 현재는 API 단일 worker에서 연결 생성·갱신·해제를 직렬화하고 버전 비교로 토큰 교체를 보호합니다.

잔여량은 공식 조회가 제공되는 경우에만 조회 시각과 함께 표시합니다. 다른 앱이 같은 계정의 한도를 소비할 수 있으며, 앱의 사용 기록은 제공자 전체 잔여량이 아닙니다. 같은 할당량 그룹의 429 이후 다른 키로 자동 우회하지 않습니다. 기본 그룹은 제공자별 `account`이며 프로젝트/계정 식별을 자동 확인한다고 주장하지 않습니다.

### 운영자: Copilot 연결용 OAuth 설정

사이트 로그인용 OAuth App과 **별도** GitHub OAuth App을 등록합니다. 한 앱의 callback을 다른 용도로 덮어쓰지 마세요.

앱의 **연결 추가 → GitHub Copilot → 오른쪽 안내 → 운영자 최초 설정: OAuth 앱 등록 화면 2개 보기**에서 사이트 로그인용·Copilot 연결용 등록 스크린샷을 비교할 수 있습니다. 이미지를 누르면 원본을 새 탭에서 크게 볼 수 있습니다. 사이트 로그인 미설정 안내에도 로그인용 스크린샷이 표시됩니다. 두 스크린샷은 로컬 예시이며 공개 호스팅에서는 실제 HTTPS 사이트 주소로 바꿔야 합니다.

1. GitHub **Settings → Developer settings → OAuth Apps → New OAuth App**을 엽니다.
2. Homepage URL에 실제 웹 주소를 입력하고 callback은 `http://localhost:3000/api/connections/copilot/callback`으로 지정합니다. HTTPS 호스팅에서는 실제 HTTPS 주소를 사용합니다. 사이트 로그인용 `/api/auth/callback/github`와 다릅니다.
3. Client ID·Client secret을 Key Vault에 등록하고 App Configuration `local-api`의 `WAGL_COPILOT_CLIENT_ID`, `WAGL_COPILOT_CLIENT_SECRET`을 네이티브 Key Vault 참조로 설정합니다. 비밀은 로컬 환경 파일·웹 브라우저용 환경 변수·Git에 넣지 않습니다.
4. API와 웹 양쪽의 `WAGL_PUBLIC_URL`을 동일한 외부 origin으로 설정합니다. 로컬 기본값은 `http://localhost:3000`이며 `localhost`와 `127.0.0.1`을 섞지 않습니다. 웹의 사이트 로그인 설정도 먼저 완료해야 합니다.
5. 서버를 재시작한 뒤 **연결 추가 → GitHub Copilot**에서 승인 흐름을 실제 계정으로 검증합니다. 앱 비밀이나 사용자 토큰을 로그·스크린샷·채팅으로 공유하지 않습니다.

기본 권한은 `read:user`이며 PKCE S256·state·로그인 소유자·브라우저 바인딩·10분 만료를 검증합니다. access/refresh 토큰은 서버에서만 교환합니다. 제공자가 만료·refresh 정보를 반환한 경우에만 저장·갱신하며 가짜 만료일은 만들지 않습니다. 원격 프록시·호스팅 접근 로그에서도 OAuth callback의 query string을 기록하지 않도록 별도로 설정하세요. Next.js 개발 요청 로그는 인증 코드 기록을 막기 위해 비활성화했습니다.

## 검증

```powershell
.venv/Scripts/python -m pytest services/api/tests -q
.venv/Scripts/python -m ruff check services/api
Set-Location apps/web
npm test
npx playwright install chromium
npm run test:e2e
npm run build
npm audit --omit=dev
```

검사 범위: 사용자 격리·서명 토큰·암호화 바인딩, Key Vault 참조·실패 차단·이전·백업 보호, 무료 가격·동의·429/안전 거절, 부분 응답·취소·잠금 해제, 실제 LiteLLM SDK의 모의 HTTP 계약, SQLite 마이그레이션 비교·암호화 역변환 차단, 한글 분할 SSE, 데스크톱·모바일 키 마스킹·전송·중지·삭제·초안 복구. E2E는 테스트 전용 서명 세션과 모의 API를 사용하며 실키 추론이나 실제 GitHub OAuth 성공을 증명하지 않습니다. 스크린샷은 `apps/web/test-results/`에 생성됩니다.

연결 검증에는 OAuth 소유자·브라우저 바인딩·만료·중복 콜백·재연결·토큰 갱신·해제, 무료 전용 차단, 기존 암호문 보존과 제공자별 단계별 안내를 포함합니다. Compose 문법·환경 치환 검증과 실제 컨테이너 실행 검증은 구별해야 합니다.

Python 의존성은 `services/api/requirements.lock`의 버전·해시로 고정합니다. LiteLLM은 `filelock` 보안 수정과 호환되는 1.100.4로 고정했으며 설치 환경의 `pip-audit`은 알려진 취약점 0건입니다. 직접 작성한 API 패키지는 PyPI에 없어 감사 대상에서 제외됩니다. 웹은 `package-lock.json`과 `npm ci`를 사용합니다. Next.js 15.5.28의 하위 PostCSS는 보안 수정 버전 8.5.32로 고정했습니다. 런타임 npm 보안 검사는 0건이며, 개발용 ESLint/minimatch 계열 중간 심각도 경고 14건은 공개 출시 전 해결해야 합니다.

## PostgreSQL·Redis 구성

위의 로컬 SQLite 실행에는 Docker나 WSL이 필요하지 않습니다. 기존 `compose.yaml`은 중앙 설정 도입 전의 참고 구성으로, 현재 부트스트랩 파일만으로 실행할 수 없습니다. 일반 로컬 컨테이너에는 Azure Managed Identity가 없으므로 Azure 인증과 별도 DB/Redis 레이블을 설계하기 전에는 사용하지 마세요. 비밀을 환경 파일에 다시 복사하는 우회는 권장하지 않습니다. Azure 운영 컨테이너는 Managed Identity와 별도의 production 설정을 사용합니다.

연결 기능 추가 전의 기존 SQLite DB는 반드시 백업합니다. Alembic 버전이 있으면 루트에서 `.venv\Scripts\python -m alembic -c services\api\alembic.ini upgrade head`를 실행합니다. 버전 없이 `create_all`로 만들어진 **기존 0001 스키마와 일치하는지 확인한 DB만** `stamp 0001` 후 `upgrade head`를 실행합니다. `stamp head`로 0002의 실제 변경을 건너뛰거나 테이블을 삭제하지 마세요. 새 빈 DB에는 바로 `upgrade head`를 적용할 수 있습니다. `0002`는 기존 API 키 암호문과 동의를 보존합니다. OAuth 연결이 생긴 이후에는 구버전으로의 역마이그레이션을 거부합니다.

## GitHub Actions 배포

- `Validate`: `main` 대상 PR과 수동 실행에서 API lint/테스트, 웹 lint/단위/E2E/빌드 및 런타임 의존성 감사를 수행합니다.
- `Deploy waglwaglagent`: `main`의 모든 push(직접 push·PR 병합)와 `main`에서의 수동 실행으로 시작합니다. 검증 후 Ubuntu/Node 24에서 Next.js standalone을 빌드하고 ZIP을 기존 **`waglwaglagent_rg/waglwaglagent`** Linux Web App에 배포합니다. 이 워크플로는 웹 프런트만 배포하며 Docker·ACR을 사용하지 않습니다.
- GitHub의 `azure-production` Environment는 `main` 브랜치만 허용합니다. `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, `AZURE_WEB_APP`, `AZURE_WEB_APP_URL`, `WAGL_APP_CONFIG_ENDPOINT`는 **비밀이 아닌 변수**입니다. 클라이언트 비밀·publish profile은 사용하지 않습니다.
- OIDC subject는 `repo:hahaysh/waglwaglagent:environment:azure-production`, issuer는 `https://token.actions.githubusercontent.com`, audience는 `api://AzureADTokenExchange`입니다. 전용 배포 ID는 대상 Web App의 Website Contributor와 App Configuration Data Reader만 가지며 Key Vault secret을 직접 조회하지 않습니다.
- Web App는 Node 24 LTS·`node server.js`로 실행합니다. 런타임 Managed Identity가 `production-web` 레이블과 운영용 Key Vault secret을 읽습니다. 운영 비밀은 빌드·ZIP·Actions 변수에 포함하지 않습니다.
- **첫 배포 전제:** 운영 FastAPI/PostgreSQL/Redis, 실제 `WAGL_API_URL`, 운영 GitHub OAuth 앱·callback이 필요합니다. 업로드 전 사전 검사가 운영 URL·네이티브 Key Vault 참조·OAuth 확인 플래그·API `/health`를 검사합니다. 준비되지 않으면 명시적으로 실패하고 ZIP을 업로드하지 않습니다.
- 동시 배포는 직렬화하고 진행 중인 배포를 취소하지 않습니다. 배포 후 웹 `/`와 미인증 BFF 401 응답을 검사합니다. 자동 롤백은 없으며 이 검사가 실제 OAuth 로그인·AI 추론까지 증명하지는 않습니다.
- 기존 리소스 설정 재적용은 [설정 도구](scripts/configure_webapp.py), 값·권한과 최초 활성화 절차는 [중앙 설정 문서](docs/central-configuration.md)를 참고하세요. 설정 도구는 앱 코드를 배포하거나 Actions를 실행하지 않습니다.

이번 구성은 배포를 시작하지 않고 별도 브랜치에서 검증합니다. `main`에 병합된 뒤 자동 배포가 시작되며, 운영 준비 조건이 부족하면 사전 검사에서 중단됩니다.

### 별도 전체 인프라 템플릿

[인프라 템플릿](infra/main.bicep)은 별도 컨테이너 기반 파일럿 설계입니다. 위의 기존 `waglwaglagent` Web App용 ZIP 워크플로와 대상·배포 방식이 다릅니다. 현재 웹앱을 설정하기 위해 실행하지 마세요. 템플릿은 구독 범위에서 `waglwaglagent-6d0f-rg`와 Web App·PostgreSQL·Managed Redis·ACR·Key Vault·모니터링·배포 ID를 생성하도록 작성했습니다. [공개 매개변수](infra/main.parameters.json)에는 비밀 값을 넣지 않습니다. 실제 리소스 생성은 별도 승인 전입니다.

- 최초 단계는 존재가 확인된 공개 정적 이미지의 고정 digest를 사용합니다. 이 화면은 AI 앱이 아닌 부트스트랩용 임시 화면입니다.
- 비밀 값은 배포 시 secure 매개변수로 전달합니다. 내부 서명 비밀, 암호화 키, Auth.js 비밀과 DB 암호를 한 번 생성해 안전하게 보관하고 재배포 때 재사용해야 합니다. 암호화 키가 바뀌면 기존 개인 키를 복호화할 수 없습니다.
- Key Vault는 RBAC 역할 할당 후 별도 모듈에서 비밀 값을 저장합니다. 모든 앱 참조는 `waglwaglagent-`로 시작하는 secret 이름을 사용합니다. PostgreSQL URL은 `sslmode=require`, Redis URL은 `rediss`와 URL-인코딩한 자격 증명을 사용하며 값을 출력하지 않습니다.
- PostgreSQL에는 `waglwaglagent` DB를 만듭니다. 최초 방화벽은 닫혀 있으며, 배포 출력의 API outbound IP를 `postgresOutboundIpRanges`로 전달해 다시 적용해야 합니다. IP 변경 시 새 허용목록을 검증하고 이전 규칙도 정리해야 합니다.
- GitHub OAuth 설정이 아직 없으면 OAuth secret과 해당 참조를 만들지 않으며 로그인은 비활성 상태입니다. 웹의 실제 HTTPS 주소로 앱을 등록한 후 `authGithubId`와 secure `authGithubSecret`을 전달해 다시 적용합니다.
- 이 별도 설계를 사용하려면 이미지 빌드·API/웹 배포 파이프라인도 따로 준비해야 합니다. 현재 Actions는 이 파일럿의 ACR·API·웹을 배포하지 않습니다.
- `enableDiagnostics`는 초기에는 `false`입니다. 실제 앱을 배포한 뒤 필요한 로그만 활성화하세요. 워크스페이스 일일 한도는 비용 완화 장치이며 초과 과금을 완전히 방지하는 보장은 아닙니다.
- OIDC subject는 `repo:hahaysh/waglwaglagent:environment:azure-pilot`입니다. 템플릿 출력의 `deploymentClientId`, Azure tenant와 구독 ID를 GitHub Environment 변수로 설정하고, 해당 Environment의 허용 브랜치를 `main`으로 제한해야 합니다.

첫 배포에는 ARM 검증·what-if, 생성된 비밀 보관, IP 방화벽 설정, GitHub Environment 연결, 최초 컨테이너 실행과 실제 OAuth 검증이 추가로 필요합니다. 현재 문법 검증은 이 작업들이 성공했다는 의미가 아닙니다.

## 공개 출시 전 점검

HTTPS·신뢰된 프록시/호스트 설정, 요청 크기·SSE 제한, PostgreSQL/Redis 실제 실행과 장애 테스트, 이미지 digest 및 의존성 검토, 개인정보·제공자 약관·연령/지역·악용 대응 정책, 보관 기간·계정 전체 삭제·백업 복원, 암호화 키 회전, 실키 단일 제공자/중지/전환 파일럿이 필요합니다. 인증·암호화 비밀은 저장소 밖의 비밀 관리 체계에 두세요. DB만 백업하면 키를 복호화할 수 없으므로 암호화 키도 별도로 보호·백업해야 합니다.

현재 취소 작업 레지스트리는 프로세스 로컬입니다. Redis가 있어도 **API 한 worker·한 replica**로만 운영 후보를 검증하세요. 다중 replica 취소 전파, 프로세스 종료 후 미완료 요청 복구, 보관 기간 자동 정리, 계정 전체 삭제·암호화 키 자동 회전은 구현되지 않았습니다. 운영자가 서버 복호화를 통제하므로 zero-knowledge 서비스가 아닙니다. 무료 API 할당량은 호스팅·DB·네트워크 비용이 무료라는 의미가 아닙니다.

정책과 제공자 근거는 [docs/provider-policy.md](docs/provider-policy.md)를 참고하세요.
