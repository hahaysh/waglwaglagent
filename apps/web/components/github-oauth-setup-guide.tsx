import Image from "next/image";

const examples = {
  login: {
    title: "1. 사이트 로그인용 OAuth 앱",
    name: "waglwaglagent-local-login",
    callback: "/api/auth/callback/github",
    image: "/guides/github-oauth-login.png",
    width: 776,
    alt: "GitHub 사이트 로그인용 OAuth 앱 등록 예시: Redirect URI가 /api/auth/callback/github인 화면",
    environment: "apps/web/.env.local",
    clientId: "AUTH_GITHUB_ID",
    clientSecret: "AUTH_GITHUB_SECRET",
  },
  copilot: {
    title: "2. Copilot 연결용 OAuth 앱",
    name: "waglwaglagent-local-copilot",
    callback: "/api/connections/copilot/callback",
    image: "/guides/github-oauth-copilot.png",
    width: 823,
    alt: "GitHub Copilot 연결용 OAuth 앱 등록 예시: Redirect URI가 /api/connections/copilot/callback인 화면",
    environment: ".env",
    clientId: "WAGL_COPILOT_CLIENT_ID",
    clientSecret: "WAGL_COPILOT_CLIENT_SECRET",
  },
};

export function GitHubOAuthSetupGuide({ kind }: { kind: keyof typeof examples }) {
  const example = examples[kind];
  return <section className="oauth-setup-example" aria-label={example.title}>
    <h4>{example.title}</h4>
    <figure>
      <a className="oauth-screenshot-link" href={example.image} target="_blank" rel="noopener noreferrer" aria-label={`${example.title} 스크린샷 크게 보기 (새 탭)`}>
        <Image src={example.image} width={example.width} height={768} alt={example.alt} unoptimized />
      </a>
      <figcaption>로컬 실행 기준 등록 예시입니다. 이미지를 누르면 새 탭에서 크게 볼 수 있습니다.</figcaption>
    </figure>
    <ol>
      <li><a href="https://github.com/settings/applications/new" target="_blank" rel="noopener noreferrer">GitHub OAuth 앱 등록 (새 탭)</a>을 엽니다.</li>
      <li><strong>Application name</strong>에 <code>{example.name}</code>, <strong>Homepage URL</strong>에 <code>http://localhost:3000</code>을 입력합니다. Description은 선택 사항입니다.</li>
      <li><strong>Redirect URIs → Redirect URI</strong>에 <code>http://localhost:3000{example.callback}</code>을 입력합니다. 화면에 Authorization callback URL로 표시되면 같은 주소를 입력합니다.</li>
      <li><strong>Allow wildcard matching</strong>과 <strong>Enable Device Flow</strong>는 켜지 않습니다. 스크린샷의 <strong>Expire user access tokens</strong>는 만료형 토큰 설정이며, Copilot 연결은 발급된 refresh token으로 갱신을 지원합니다.</li>
      <li><strong>Register application</strong>을 누릅니다. 등록 후 표시되는 <strong>Client ID</strong>와 <strong>Generate a new client secret</strong>으로 만든 비밀을 서버의 <code>{example.environment}</code>에 각각 <code>{example.clientId}</code>, <code>{example.clientSecret}</code>로 설정합니다.</li>
    </ol>
  </section>;
}
