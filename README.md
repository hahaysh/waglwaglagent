# waglwaglagent

개인 API 키로 공식 무료 AI 모델을 사용하는 웹 작업공간입니다. 각 사용자의 키·대화·사용 기록은 소유자에게만 연결됩니다. 등록한 제공자와 실제 처리업체 중 사전에 전송을 허용한 곳만 사용하며, 유료 모델로 자동 전환하지 않습니다.

**현재 상태: 로컬 검증용 MVP. 공개 서비스 출시 완료가 아닙니다.** GitHub OAuth 로그인과 실키 추론, 컨테이너 실행 및 운영 보안 검증은 별도로 필요합니다.

## 구현 범위

- GitHub 로그인, 서버 AES-GCM 암호화 키 저장, 개인 연결 등록·확인·삭제.
- 무료 OpenRouter 모델과 실제 처리업체 선택, 전송 동의, 연결 우선순위.
- SSE 대화, 중지, 대화 이력 삭제, 요청별 모델·처리업체·토큰 기록.
- 무료 가격·자격·동의 확인 실패 시 차단. 안전 정책 거절과 인증 오류는 자동 전환하지 않음.
- 응답이 일부라도 시작된 뒤에는 다른 모델 응답을 이어 붙이지 않음.
- Gemini는 키만으로 무료 결제 등급을 확인할 수 없어 기본 호출 차단. 소비자 Copilot·ChatGPT·Claude 할당량, 쿠키·HAR·스크래핑·키 공유는 제외.

## 로컬 실행

Windows PowerShell, Python 3.12, Node.js 22.18 이상 또는 24 LTS를 사용합니다. 현재 검증 환경은 Python 3.12와 Node.js 26입니다. 테스트의 직접 TypeScript 실행에는 최신 Node가 필요합니다.

저장소 루트에서 API 의존성과 비밀 설정을 준비합니다. `init-local.ps1`은 기존 환경 파일을 덮어쓰지 않으며 비밀 값을 출력하지 않습니다.

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install --require-hashes -r services/api/requirements.lock
./scripts/init-local.ps1
.venv/Scripts/python -m uvicorn app.main:app --app-dir services/api --host 127.0.0.1 --port 8000
```

별도 터미널에서 웹을 실행합니다.

```powershell
Set-Location apps/web
npm ci
npm run dev -- --hostname 127.0.0.1 --port 3000
```

웹: <http://localhost:3000> · API 상태: <http://127.0.0.1:8000/health>

기본 SQLite 데이터는 루트의 `.local/wagl.db`에 저장됩니다. 로컬 모드는 API 한 프로세스 전용이며 다중 서버 배포에 사용하지 않습니다. 포트가 사용 중이라면 초기화 시 `-Port 3001`을 지정하고 웹 실행 포트도 맞추세요. 이미 설정한 경우 `AUTH_URL`, `WAGL_PUBLIC_URL`, OAuth callback과 실행 포트를 함께 변경합니다.

### GitHub OAuth

GitHub **Settings → Developer settings → OAuth Apps**에서 앱을 등록합니다.

- Homepage URL: `http://localhost:3000`
- Authorization callback URL: `http://localhost:3000/api/auth/callback/github`
- 생성한 Client ID와 Client secret을 `apps/web/.env.local`의 `AUTH_GITHUB_ID`, `AUTH_GITHUB_SECRET`에 직접 입력하고 웹 서버를 재시작합니다.

비밀 값은 채팅으로 전달하지 마세요. OAuth가 설정되지 않아도 화면은 열리지만 로그인·키 등록·AI 전송은 우회되지 않습니다. Auth.js는 버전을 고정한 v5 beta를 사용하므로 공개 출시 전 별도 안정성 검토가 필요합니다.

### 개인 연결

로그인 후 **내 연결 → 연결 추가**에서 개인 OpenRouter 키, 무료 모델, 실제 처리업체를 선택합니다. 메시지와 기존 대화 이력의 전송에 동의해야 호출 후보가 됩니다. 작은 우선순위 값이 먼저 시도됩니다. 무료 카탈로그에 있더라도 처리업체 상태나 한도에 따라 호출이 실패할 수 있습니다.

로그인 전에도 **연결 추가**를 누를 수 있으며 로그인 안내가 열립니다. 서버에 OAuth 설정이 없으면 필요한 설정 절차를 표시합니다. 안내만으로 인증을 우회하거나 키를 저장할 수는 없습니다.

잔여량은 공식 조회가 제공되는 경우에만 조회 시각과 함께 표시합니다. 다른 앱이 같은 계정의 한도를 소비할 수 있으며, 앱의 사용 기록은 제공자 전체 잔여량이 아닙니다. 같은 할당량 그룹의 429 이후 다른 키로 자동 우회하지 않습니다. 기본 그룹은 제공자별 `account`이며 프로젝트/계정 식별을 자동 확인한다고 주장하지 않습니다.

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

검사 범위: 사용자 격리·서명 토큰·암호화 바인딩, 무료 가격·동의·429/안전 거절, 부분 응답·취소·잠금 해제, 실제 LiteLLM SDK의 모의 HTTP 계약, SQLite 마이그레이션 비교·롤백, 한글 분할 SSE, 데스크톱·모바일 키 마스킹·전송·중지·삭제·초안 복구. E2E는 테스트 전용 서명 세션과 모의 API를 사용하며 실키 추론이나 실제 GitHub OAuth 성공을 증명하지 않습니다. 스크린샷은 `apps/web/test-results/`에 생성됩니다.

API 테스트 24개, 웹 단위 테스트 5개, 데스크톱·모바일 E2E 8개와 웹 빌드가 통과했습니다. Compose 문법·환경 치환도 검사했으며 컨테이너 실행은 검증하지 못했습니다.

Python 의존성은 `services/api/requirements.lock`의 버전·해시로 고정합니다. LiteLLM은 `filelock` 보안 수정과 호환되는 1.100.4로 고정했으며 설치 환경의 `pip-audit`은 알려진 취약점 0건입니다. 직접 작성한 API 패키지는 PyPI에 없어 감사 대상에서 제외됩니다. 웹은 `package-lock.json`과 `npm ci`를 사용합니다. Next.js 15.5.28의 하위 PostCSS는 보안 수정 버전 8.5.32로 고정했습니다. 런타임 npm 보안 검사는 0건이며, 개발용 ESLint/minimatch 계열 중간 심각도 경고 14건은 공개 출시 전 해결해야 합니다.

## PostgreSQL·Redis 구성

Docker Desktop의 Linux 엔진이 실행 중일 때 루트에서 다음 명령을 사용합니다. 현재 환경에서는 엔진이 꺼져 있어 Compose 컨테이너 실행을 검증하지 못했습니다.

```powershell
docker compose config --quiet
docker compose up --build
```

Compose는 DB·Redis·API 포트를 호스트에 노출하지 않고 웹만 `127.0.0.1:3000`에 바인딩합니다. API는 시작 전에 Alembic 마이그레이션을 적용합니다. 로컬 서버를 먼저 중지해 포트 충돌을 피하세요. 수동 마이그레이션은 루트에서 `.venv/Scripts/python -m alembic -c services/api/alembic.ini upgrade head`로 실행합니다. 기존 `create_all` SQLite DB를 옮기려면 백업 후 스키마 일치를 확인한 다음 `stamp head` 여부를 판단해야 하며, 기존 테이블에 무조건 `upgrade head`를 적용하지 마세요.

## 공개 출시 전

HTTPS·신뢰된 프록시/호스트 설정, 요청 크기·SSE 제한, PostgreSQL/Redis 실제 실행과 장애 테스트, 이미지 digest 및 의존성 검토, 개인정보·제공자 약관·연령/지역·악용 대응 정책, 보관 기간·계정 전체 삭제·백업 복원, 암호화 키 회전, 실키 단일 제공자/중지/전환 파일럿이 필요합니다. 인증·암호화 비밀은 저장소 밖의 비밀 관리 체계에 두세요. DB만 백업하면 키를 복호화할 수 없으므로 암호화 키도 별도로 보호·백업해야 합니다.

현재 취소 작업 레지스트리는 프로세스 로컬입니다. Redis가 있어도 **API 한 worker·한 replica**로만 운영 후보를 검증하세요. 다중 replica 취소 전파, 프로세스 종료 후 미완료 요청 복구, 보관 기간 자동 정리, 계정 전체 삭제·암호화 키 자동 회전은 구현되지 않았습니다. 운영자가 서버 복호화를 통제하므로 zero-knowledge 서비스가 아닙니다. 무료 API 할당량은 호스팅·DB·네트워크 비용이 무료라는 의미가 아닙니다.

정책과 제공자 근거는 [docs/provider-policy.md](docs/provider-policy.md)를 참고하세요.
