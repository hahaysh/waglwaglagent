import Link from "next/link";
import { ArrowLeft, GitBranch, KeyRound, Layers, ShieldCheck } from "lucide-react";
import { SiteLogin } from "./site-login";

export function PublicHome({ providers, error, returnTo }: {
  providers: { id: string; name: string; available: boolean; incomplete: boolean }[];
  error?: string | null; returnTo?: string;
}) {
  return <main className="login-page">
    <section className="login-hero" aria-label="서비스 소개">
      <Link className="brand" href="/" aria-label="waglwaglagent 홈"><span className="brand-mark"><GitBranch size={22} /></span><span>waglwagl<span className="brand-agent">agent</span></span></Link>
      <div className="login-hero-body">
        <h1>나만의 AI 연결,<span> 나만의 작업공간.</span></h1>
        <p className="login-lead">공식적으로 허용된 무료·구독 포함량을 확인하고, 직접 등록한 AI 연결로 한곳에서 대화하세요.</p>
        <ul className="login-points">
          <li><span><Layers size={18} /></span><div><strong>여러 AI를 한곳에서</strong><small>GitHub Copilot·Gemini·OpenRouter를 하나의 대화 화면에서 사용합니다.</small></div></li>
          <li><span><ShieldCheck size={18} /></span><div><strong>내 계정, 내 한도</strong><small>각자 본인 계정과 본인 포함량만 사용하며 유료 AI로 자동 전환하지 않습니다.</small></div></li>
          <li><span><KeyRound size={18} /></span><div><strong>안전한 개인 저장</strong><small>연결·대화·첨부는 로그인한 계정에만 저장하고 키는 암호화합니다.</small></div></li>
        </ul>
      </div>
    </section>
    <section className="login-panel" aria-labelledby="login-title">
      <div className="login-card">
        <span className="eyebrow">SIGN IN</span>
        <h2 id="login-title">로그인</h2>
        <p className="login-sub">로그인하면 나만의 빈 작업공간이 만들어집니다.</p>
        {error && <p className="login-alert" role="alert">{error}</p>}
        <SiteLogin providers={providers} returnTo={returnTo} />
        <div className="login-notes">
          <p><strong>사이트 로그인과 AI 인증은 별개입니다.</strong> 로그인 후 GitHub Copilot이나 지원되는 API 키를 따로 연결하세요. 연결 등록만으로 AI 전송에 동의하거나 무료 자격을 얻는 것은 아닙니다.</p>
          <p>Microsoft는 개인 계정만 지원합니다. 제공자가 다르면 같은 이메일이어도 별개 작업공간이므로, 연결을 다시 불러오려면 처음 사용한 제공자와 계정을 선택해주세요.</p>
        </div>
        <div className="login-links">
          <Link href="/"><ArrowLeft size={14} /> 로그인 없이 둘러보기</Link>
          <Link href="/privacy">개인정보 처리 안내</Link>
        </div>
      </div>
    </section>
  </main>;
}
