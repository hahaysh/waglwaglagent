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
로컬 SQLite URL을 운영 레이블로 복사하지 마세요. 운영 API에는 PostgreSQL과 Redis가 필요합니다.
App Service에는 환경·App Configuration endpoint/레이블 등 부트스트랩과
컨테이너 실행에 필요한 플랫폼 설정만 둡니다.
기존 전체 호스팅 IaC는 별도 파일럿 리소스 그룹을 생성하므로 **현재 로컬 전환을 위해
전체 배포할 필요가 없습니다**. 실제 호스팅 배포 전 대상·예산·네트워크를 확인하세요.
