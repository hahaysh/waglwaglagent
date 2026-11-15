# 중앙 설정과 비밀 관리

## 저장 경계

- `waglwaglagent-config` App Configuration: 일반 설정 및 **네이티브 Key Vault 참조**.
  로컬은 `local-api`, `local-web`, Azure 운영은 `production-api`, `production-web` 레이블을 사용합니다.
- `waglwaglagent-kv` Key Vault: 내부 인증 비밀, 기존 AES-256 암호화 키,
  Auth.js 비밀, GitHub 로그인·Copilot OAuth 설정, DB·Redis 인증 정보,
  사용자별 AI API 키와 OAuth access/refresh token 묶음.
- DB: 사용자 연결 비밀은 `kv://이름/버전` 참조만 보관합니다.
  제목·메시지·첨부·연결 이름은 AES-GCM으로 암호화합니다.
  소유자/제공자 ID, 동의, 상태, 사용량 등 조회용 메타데이터는 남습니다.
- PKCE verifier는 10분 수명의 임시 값으로, Key Vault에 버전 이력을 쌓지 않고
  기존 사용자/요청 바인딩 AES-GCM 암호문으로 보관한 뒤 사용 시 제거합니다.
- 이미지·문서 자체를 Key Vault secret으로 저장하지 않습니다.
  응답과 첨부는 인증된 사용자의 브라우저 및 동의한 AI 제공자에게 전송됩니다.

로컬 환경 파일에는 endpoint, 레이블, 환경 이름, 인증 테넌트만 남습니다.
부트스트랩 자체는 중앙 설정에 접근하기 위해 로컬에 있어야 합니다.
비밀은 브라우저 환경 변수나 클라이언트 번들에 주입하지 않습니다.

## 접속과 권한

- 로컬: `az login --tenant <tenant-id>`, 명시적 테넌트의 `AzureCliCredential`.
  기본 구독을 임의 변경하거나 클라이언트 비밀을 Azure 접속에 사용하지 않습니다.
- Azure: `ManagedIdentityCredential`. App Configuration Data Reader와 Key Vault 권한 필요.
- 웹: Key Vault Secrets User (읽기).
- API: 연결 생성·갱신·삭제가 Key Vault에 반영되므로 읽기 전용만으로는 부족합니다.
  현재 IaC는 해당 vault 범위의 Key Vault Secrets Officer를 사용합니다.
  대규모 운영에서는 연결 전용 vault 및 get/set/delete 한정 사용자 정의 역할로
  운영자 비밀과 사용자 연결의 권한을 추가 분리하는 것을 권장합니다.
- 설정 이전 운영자: 해당 store의 App Configuration Data Owner,
  해당 vault의 Key Vault Secrets Officer. 구독 Owner만으로 데이터 접근은 되지 않습니다.

서버 설정은 시작할 때 읽고 메모리에만 유지합니다. 변경 후 API와 웹을 재시작하세요.
Key Vault 네트워크 I/O는 API 이벤트 루프 밖에서 실행하여 조회 지연 중에도 중지 요청을 처리할 수 있습니다.
연결 토큰은 버전 고정 참조로 읽으므로 토큰 갱신 경쟁이 다른 요청의 버전을 바꾸지 않습니다.
설정·비밀 조회 실패는 시작/요청을 차단하며 로컬 평문이나 다른 계정으로 대체하지 않습니다.
Vault의 soft-delete 보존 기간에는 삭제된 secret이 권한 있는 운영자에 의해 복구될 수 있습니다.
연결 삭제는 발급처 API 키 폐기와 같지 않으며 OAuth 철회 실패 안내도 유지합니다.

## 기존 로컬 데이터 이전

API/웹을 중지한 상태에서 루트에서 실행합니다. 인자는 비밀이 아닌 식별 정보입니다.

```powershell
$env:PYTHONPATH = "services\api"
.venv\Scripts\python.exe -m app.migrate_secrets `
  --vault-url "https://waglwaglagent-kv.vault.azure.net/" `
  --configuration-endpoint "https://waglwaglagent-config.azconfig.io" `
  --tenant-id "<tenant-id>"
```

도구는 먼저 저장·재조회 결과를 검증하고, 기존 DB·환경 설정·로컬 DB 백업을
기존 키로 암호화해 보관한 뒤 DB migration 0004와 연결 참조 전환을 수행합니다.
마지막으로 두 환경 파일을 부트스트랩으로 교체합니다. 기존 vault 값과 다른 값을
발견하면 자동 덮어쓰지 않습니다. 이전 후 재실행하지 말고 정상 시작·검증 절차를 사용하세요.

이전은 두 Azure 서비스와 DB를 묶는 분산 트랜잭션이 아닙니다.
실패하면 서버를 중지한 채 실패 단계와 암호화 백업을 확인하세요.
이미 이전된 비밀은 남을 수 있지만 검증 전 원본 환경 파일을 제거하지 않습니다.
마스터 키를 새 값으로 임의 변경하면 기존 데이터와 백업을 읽을 수 없습니다.
키 자동 교체·재암호화는 아직 지원하지 않습니다.

암호화 백업은 `.local\*.aesgcm`이며 복구에도 원래 Key Vault 키가 필요합니다.
파일 포맷은 `enc:v1:`과 Base64(nonce + AES-GCM ciphertext/tag)입니다.
DB 백업은 AAD `backup:<원래 파일명>`, 환경 백업은 AAD `backup:environment`를 사용합니다.
`app.encryption.unseal`로 복호화한 DB 백업 문자열은 다시 Base64 디코딩하면 됩니다.
복구 원문을 로그·화면·Git에 출력하지 말고 접근 제한된 경로에서만 다루세요.
기존에 복사·내보내기·업로드한 파일, OS 저장장치의 삭제 흔적, 외부 AI 보관본까지
이 도구가 소급 삭제하거나 암호화하지는 않습니다.

## Azure 운영

일반 설정은 `production-api`, `production-web`에 실제 운영 URL로 별도 설정하세요.
로컬 SQLite URL을 운영 레이블로 복사하지 마세요. 운영 API에는 Azure SQL과 Redis가 필요합니다.
App Service에는 환경·App Configuration endpoint/레이블 등 부트스트랩과
컨테이너 실행에 필요한 플랫폼 설정만 둡니다.
기존 전체 호스팅 IaC는 별도 파일럿 리소스 그룹을 생성하므로 **현재 로컬 전환을 위해
전체 배포할 필요가 없습니다**. 실제 호스팅 배포 전 대상·예산·네트워크를 확인하세요.

### 기존 `waglwaglagent` Web App

배포 대상은 `waglwaglagent_rg/waglwaglagent`이고 운영 주소는
`https://waglwaglagent-echmdef2d8ejb9fb.koreacentral-01.azurewebsites.net`입니다.
앱 코드는 GitHub Actions에서만 업로드합니다. 아래 설정 명령은 코드를 업로드하거나
워크플로를 실행하지 않지만 런타임 설정 변경으로 웹앱이 재시작될 수 있습니다.

```powershell
.venv\Scripts\python.exe scripts\configure_webapp.py `
  --subscription "<subscription-id>" `
  --tenant "<tenant-id>" `
  --resource-group "waglwaglagent_rg"
```

- Web App는 Node 24 LTS를 사용하고, 런타임 호스트를 `0.0.0.0`으로 둡니다.
  설정 도구는 기존 시작 명령을 바꾸지 않습니다. Actions가 ZIP 업로드를 성공적으로
  마친 뒤에만 `node server.js`를 적용하고 재시작합니다. 앱 파일 없이 이 명령을
  미리 지정하면 503이 발생합니다. GitHub에서 완성한 ZIP을 사용하므로 Oryx/SCM 원격 빌드는 끕니다.
- App settings에는 `WAGL_ENVIRONMENT=production`, 기존 store endpoint,
  `WAGL_APP_CONFIG_LABEL=production-web`과 실행 플랫폼 설정만 둡니다.
- 웹의 시스템 할당 Managed Identity에는 해당 store의 App Configuration Data Reader,
  아래 네 개 운영 secret **각각의 범위에만** Key Vault Secrets User를 부여합니다.
  사용자 Copilot 토큰·로컬 비밀 전체를 읽을 권한은 부여하지 않습니다.
- 전용 `waglwaglagent-github-deploy` Managed Identity에는 웹·API 각각의 범위 Website Contributor와
  store 범위 App Configuration Data Reader만 부여합니다. GitHub `azure-production`
  환경은 `main`만 허용하며 암호 없는 OIDC를 사용합니다.
  subject는 GitHub OIDC 설정 API의 `sub_claim_prefix`를 사용하므로 저장소의 불변 ID를
  포함한 형식도 지원합니다. 실제 prefix를 조회할 수 없거나 사용자 지정 템플릿이면
  예전 이름 형식으로 추측하지 않고 설정을 중단합니다.

`production-web`은 다음 네이티브 Key Vault 참조를 사용합니다.

| 설정 | Key Vault secret |
|---|---|
| `AUTH_SECRET` | `waglwaglagent-production-auth-secret` |
| `WAGL_INTERNAL_SECRET` | `waglwaglagent-production-internal-secret` |
| `AUTH_GITHUB_ID` | `waglwaglagent-production-github-id` |
| `AUTH_GITHUB_SECRET` | `waglwaglagent-production-github-secret` |

설정 도구는 처음 두 비밀만 없을 때 생성하고 재실행 시 보존합니다.
GitHub 앱 ID·비밀은 추측하거나 로컬 OAuth 앱에서 복사하지 않습니다.
로컬 레이블·비밀·암호화 키·DB는 변경하지 않습니다.

### 최초 자동 배포 활성화 전

1. 별도로 승인한 운영 FastAPI/Azure SQL/Redis를 준비합니다. API의 운영 설정은
   `production-api`에 두고, 웹과 같은 운영 `WAGL_INTERNAL_SECRET`을 참조합니다.
   실제 HTTPS API origin을 `production-web`의 `WAGL_API_URL`에 설정합니다.
   웹 자기 자신이나 localhost를 입력하지 않습니다.
2. 운영 전용 GitHub OAuth 앱의 callback을
   `<운영 웹 주소>/api/auth/callback/github`로 등록합니다. 해당 앱의 실제 ID·비밀을
   위의 production secret 두 개에 저장합니다. 브라우저·명령 인자·Git에 노출하지 마세요.
   Copilot 연결 앱도 `<운영 웹 주소>/api/connections/copilot/callback`에 맞게
   별도 준비하고 그 설정은 운영 API 레이블에서 참조합니다.
3. 실제 등록과 secret 저장을 확인한 뒤에만 `production-web`의
   `WAGL_OAUTH_CALLBACK_CONFIRMED`를 `true`로 변경합니다. 기본값은 `false`입니다.
4. `main`을 변경하면 검증 → 웹/API 빌드 → API 사전 검사·업로드·migration·준비 확인 →
   웹 사전 검사·업로드·시작 명령 적용 순으로 진행합니다.
   API URL·OAuth 확인이 없으면 업로드 전에 실패합니다. Key Vault 실제 조회 권한과
   로그인·대화의 최종 검증은 첫 배포 이후 별도로 수행합니다.

### 공유 플랜 백엔드와 운영 참조

기존 API는 Python 3.12·한 worker로 웹과 B1 플랜을 공유하며 Redis는 B0·TLS·HA 비활성입니다.
PostgreSQL 초기 템플릿 `infra/backend.bicep`은 실제 할당 실패 후 운영에 재실행하지 않습니다.
대신 `infra/sql.bicep`으로 Korea Central SQL Basic(5 DTU/2GB·Local 백업 7일)을 생성합니다.
Entra-only 인증과 API의 system Managed Identity를 사용하며 SQL 암호를 생성하지 않습니다.
API outbound IP만 허용하고 임시 운영자 규칙은 설정·검증 후 제거합니다.
유료 SKU 또는 리전은 자동 변경하지 않습니다. DB가 없으면 배포 준비 검사를 통과시키지 않습니다.

운영 Copilot OAuth 앱은 사이트 로그인과 별도로 등록했으며 callback은
`<운영 웹 주소>/api/connections/copilot/callback`입니다. 로컬 앱·레이블은 유지합니다.
`production-api`가 사용하는 참조는 다음과 같습니다. DB URL은 실제 생성 성공 후에만 저장합니다.

| 설정 | Key Vault secret |
|---|---|
| `WAGL_INTERNAL_SECRET` | `waglwaglagent-production-internal-secret` |
| `WAGL_ENCRYPTION_KEY` | `waglwaglagent-production-encryption-key` |
| `WAGL_DATABASE_URL` | `waglwaglagent-production-database-url` |
| `WAGL_REDIS_URL` | `waglwaglagent-production-redis-url` |
| `WAGL_COPILOT_CLIENT_ID` | `waglwaglagent-production-copilot-id` |
| `WAGL_COPILOT_CLIENT_SECRET` | `waglwaglagent-production-copilot-secret` |

DB 생성 후 `scripts/configure_sql_database.py`에 실제 SQL 호스트·API principal ID·tenant를
전달해 contained identity의 SID와 reader/writer/DDL 역할을 검증합니다.
그 다음 준비된 Python 환경에서 `scripts/configure_backend.py`를
명시적 `--subscription`, `--tenant`와 함께 실행합니다. 이 도구는 실제 호스트·공유 플랜·SKU를
검사하고 DB/Redis URL을 Key Vault에 저장·재조회합니다. App Configuration에는 네이티브
참조와 일반 URL만 넣고 GitHub Environment에 API 대상 변수를 설정합니다.
SQL URL은 `mssql+mssqlpython`과 `authentication=ActiveDirectoryMSI&encrypt=yes&trustservercertificate=no`,
Redis는 `rediss`와 인증서 검증을 사용합니다. 암호 없는 SQL URL도 기존 네이티브
Key Vault 참조 계약을 유지합니다. 비밀은 명령 인자·GitHub 변수·ZIP에 넣지 않습니다.

운영 암호화 키는 새 DB용으로 생성하며 로컬 데이터의 기존 키를 바꾸지 않습니다.
API는 서버 관리자나 `db_owner`가 아닌 contained Managed Identity입니다.
현재 시작 시 migration 때문에 `db_ddladmin`이 필요합니다. migration을 배포 전용 ID로 분리한
후에는 이 역할을 제거할 수 있습니다. 원래 운영 암호화 키를 재생성하지 않습니다.
백업 복원에는 DB뿐 아니라 원래 암호화 키도 필요합니다. 보존 7일 설정은 복원 시험 완료를
뜻하지 않습니다. API·웹의 CPU/RAM은 공유하므로 우선 scale-up을 검토하고,
API의 분산 취소·재시작 복구를 구현하기 전에는 scale-out하지 않습니다.

### 미배포 상태의 503 확인

`server.js`가 없는 웹앱에 `node server.js`가 지정되면 프로세스가 반복 종료됩니다.
Azure의 `Running` 표시는 리소스 상태이지 앱 요청 성공을 의미하지 않습니다.
배포 이력과 시작 로그, 실제 배포 디렉터리를 먼저 확인하세요.
처음 배포하지 않은 앱에 잘못 지정한 시작 명령만 해제하면 Azure 기본 안내 페이지로
돌아갈 수 있지만, 이는 waglwaglagent가 배포되었다는 뜻이 아닙니다.
실제 배포는 위 운영 준비 조건을 충족한 뒤 Actions로 진행합니다.
