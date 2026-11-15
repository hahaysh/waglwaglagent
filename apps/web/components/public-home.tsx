import Link from "next/link";
import { SiteLogin } from "./site-login";

export function PublicHome({ providers, error, returnTo }: {
  providers: { id: string; name: string; available: boolean; incomplete: boolean }[];
  error?: string | null; returnTo?: string;
}) {
  return <main className="public-site">
    <Link className="brand" href="/">waglwaglagent</Link>
    <h1>나만의 AI 연결, 나만의 작업공간.</h1>
    <p>공식적으로 허용된 무료·구독 포함량을 확인하고, 직접 등록한 AI 연결로 대화하세요.</p>
    <p>Microsoft 개인 계정, Google 또는 GitHub로 사이트에 로그인하면 빈 개인 작업공간이 만들어집니다.
      대화·첨부·사용 기록과 AI 연결은 로그인한 계정에만 저장됩니다.</p>
    {error && <p className="alert" role="alert">{error}</p>}
    <SiteLogin providers={providers} returnTo={returnTo} />
    <section><h2>사이트 로그인과 AI 인증은 별개입니다.</h2>
      <p>로그인 후 GitHub Copilot이나 지원되는 API 키를 별도로 연결하세요.
        연결 등록만으로 AI 전송에 동의하거나 무료 사용 자격을 얻는 것은 아닙니다.</p>
      <p>서로 다른 로그인 제공자의 계정은 같은 이메일이어도 별개 작업공간입니다.
        개인 연결을 다시 불러오려면 처음 사용한 로그인 제공자와 계정을 선택해주세요.</p>
      <p>유료 AI로 자동 전환하지 않습니다. 기존 구독료와 제공자의 과금·예산 설정은 별도입니다.</p>
    </section>
    <Link href="/privacy">개인정보 처리 안내</Link>
  </main>;
}
