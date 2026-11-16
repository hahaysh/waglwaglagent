"use client";

import { useEffect, useRef, useState } from "react";
import { ExternalLink, KeyRound, LoaderCircle, ShieldCheck, X } from "lucide-react";
import { api, errorMessage, notifySessionChange, type Endpoint, type Model } from "@/lib/api";
import { connectionProviders, type ConnectionProvider } from "@/lib/connection-providers";
import { GitHubOAuthSetupGuide } from "@/components/github-oauth-setup-guide";

type Props = {
  authenticated: boolean;
  authConfigured: boolean;
  initialProvider?: ConnectionProvider;
  onLogin: (provider: ConnectionProvider) => void;
  onClose: () => void;
  onSaved: () => Promise<void>;
  signal?: AbortSignal;
  sessionId: string;
};

export function ConnectionDialog({ authenticated, authConfigured, initialProvider, onLogin, onClose, onSaved, signal, sessionId }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [provider, setProvider] = useState<ConnectionProvider | null>(initialProvider ?? null);
  const [models, setModels] = useState<Model[]>([]);
  const [model, setModel] = useState("");
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [upstreams, setUpstreams] = useState<string[]>([]);
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [oauthReady, setOauthReady] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const selected = connectionProviders.find((entry) => entry.id === provider);

  useEffect(() => { dialog.current?.showModal(); }, []);
  useEffect(() => {
    if (!authenticated || !provider) return;
    let active = true;
    if (provider === "copilot") {
      api<{ copilot_oauth: boolean }>("connection-options", { signal }, sessionId)
        .then((options) => { if (active) setOauthReady(options.copilot_oauth); })
        .catch((reason: Error) => { if (active) setError(reason.message); });
    } else if (provider === "openrouter") {
      api<{ models: Model[] }>("catalog", { signal }, sessionId)
        .then((catalog) => { if (active) setModels(catalog.models); })
        .catch((reason: Error) => { if (active) setError(reason.message); });
    }
    return () => { active = false; };
  }, [provider, authenticated, signal, sessionId]);

  useEffect(() => {
    if (provider !== "openrouter" || !model || !authenticated) return;
    let active = true;
    api<{ endpoints: Endpoint[] }>(`endpoints?model=${encodeURIComponent(model)}`, { signal }, sessionId)
      .then((result) => { if (active) { setEndpoints(result.endpoints); setLoading(false); } })
      .catch((reason: Error) => { if (active) { setError(reason.message); setLoading(false); } });
    return () => { active = false; };
  }, [provider, model, authenticated, signal, sessionId]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!provider || provider === "copilot") return;
    setSaving(true); setError("");
    try {
      await api("credentials", { method: "POST", body: JSON.stringify({
        provider, label, api_key: apiKey, model: model || null, upstreams, approved: true,
      }), signal }, sessionId);
      setApiKey("");
      await onSaved();
    } catch (reason) { setError((reason as Error).message); }
    finally { setSaving(false); }
  }

  async function connectCopilot() {
    setSaving(true); setError("");
    try {
      const response = await fetch("/api/connections/copilot/start", {
        method: "POST", signal, headers: { "X-Wagl-Session": sessionId, "Content-Type": "application/json" },
        body: JSON.stringify({ approved: true }),
      });
      const payload = await response.json();
      if (response.status === 401 || payload.detail === "Session changed") notifySessionChange();
      if (!response.ok) throw new Error(errorMessage(payload.detail));
      if (!signal?.aborted) window.location.assign(payload.authorization_url);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "연결을 시작할 수 없습니다."); setSaving(false); }
  }

  function chooseProvider(next: ConnectionProvider) {
    if (next === provider) return;
    setProvider(next); setModel(""); setEndpoints([]); setUpstreams([]); setApiKey("");
    setLabel(""); setError(""); setLoading(false); setOauthReady(false);
  }

  return <dialog ref={dialog} className={`connection-dialog${selected ? " connection-dialog-with-guide" : ""}`} aria-labelledby="connection-title" onCancel={onClose} onClick={(event) => { if (event.target === dialog.current) onClose(); }}>
    <div className="dialog-heading"><div><span className="eyebrow">NEW CONNECTION</span><h2 id="connection-title">AI 서비스 연결</h2></div><button type="button" className="icon-button" aria-label="연결 창 닫기" onClick={onClose}><X size={20} /></button></div>
    <div className="connection-layout">
    <div className="connection-form-panel">
    <div className="provider-picker" role="group" aria-label="연결할 AI 서비스">
      {connectionProviders.map((entry) => <button type="button" key={entry.id} className={`provider-choice ${provider === entry.id ? "selected" : ""}`} onClick={() => chooseProvider(entry.id)} disabled={saving} aria-pressed={provider === entry.id}>
        <strong>{entry.name}</strong><small>{entry.method}</small>
      </button>)}
    </div>
    {!selected && <p>연결할 서비스를 선택하면 처음 연결하는 순서와 지원 조건을 확인할 수 있습니다. 사이트 로그인과 AI 서비스 연결은 별개입니다.</p>}
    {selected && <>
      <p>{selected.description}</p>
      {selected.pending ? <div className="dialog-footer" role="status">
        <span>승인 대기 중 · 아직 연결할 수 없습니다</span>
        <p>공식 ChatGPT 로그인 승인 후 이 창에서 연결할 수 있습니다. 그때까지 API 키나 ChatGPT 계정 정보를 입력받지 않습니다.</p>
      </div> : !authenticated ? <div className="dialog-footer">
        <span>{authConfigured ? "안전한 저장을 위해 먼저 이 사이트에 로그인해주세요." : "사이트 로그인 준비 중입니다. 운영자 설정이 필요합니다."}</span>
        <button className="primary-button" onClick={() => onLogin(selected.id)}>{authConfigured ? "사이트 로그인 선택" : "운영자 설정 안내"}</button>
      </div> : provider === "copilot" ? <div className="dialog-footer">
        <span>{oauthReady ? "인증 성공 후 동의 저장 · 이용 조건 자동 확인" : "서비스 연결 준비 중 · 운영자 OAuth 설정 필요"}</span>
        <p>‘동의하고 Copilot 연결’을 누르면 대화·이력·첨부를 GitHub Copilot 및 Copilot이 선택한 모델 제공자로 전송하는 데 동의합니다. 동의는 본인 연결에 저장되며 언제든 철회할 수 있습니다. 남은 포함량이 확인될 때만 전송하고, 추가 과금 차단은 GitHub 예산 설정이 필요합니다.</p>
        <button className="primary-button" disabled={!oauthReady || saving} onClick={connectCopilot}>{saving && <LoaderCircle size={16} className="spin" />} 동의하고 Copilot 연결</button>
      </div> : <form onSubmit={save}>
        <label className="field-label">연결 이름<input required maxLength={80} placeholder={`내 ${selected.name}`} value={label} onChange={(event) => setLabel(event.target.value)} /></label>
        <label className="field-label">API 키<div className="key-input"><KeyRound size={16} /><input type="password" autoComplete="off" required minLength={8} maxLength={500} placeholder="API 키" value={apiKey} onChange={(event) => setApiKey(event.target.value)} /></div></label>
        {provider === "openrouter" && <>
          <label className="field-label">무료 모델<select aria-label="무료 모델" required value={model} onChange={(event) => { setModel(event.target.value); setUpstreams([]); setEndpoints([]); setLoading(Boolean(event.target.value)); setError(""); }}><option value="">모델 선택</option>{models.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}</select></label>
          <fieldset className="upstream-field"><legend>전송 동의 전에 검토할 실제 처리업체</legend>
            {loading && <span className="thinking"><LoaderCircle size={14} className="spin" /> 조회 중</span>}
            {!loading && model && endpoints.length === 0 && <span className="muted">현재 무료 처리업체를 확인할 수 없습니다.</span>}
            {endpoints.map((endpoint) => <label key={endpoint.id} className="checkbox-row"><input type="checkbox" aria-label={endpoint.name} checked={upstreams.includes(endpoint.id)} onChange={(event) => setUpstreams(event.target.checked ? [...upstreams, endpoint.id] : upstreams.filter((item) => item !== endpoint.id))} /><span>{endpoint.name}<small>{endpoint.id}</small></span></label>)}
          </fieldset>
        </>}
        <p>‘동의하고 연결’을 누르면 대화·이력·첨부를 {selected.name}{provider === "openrouter" ? " 및 선택한 실제 처리업체" : ""}에 전송하는 데 동의합니다. 동의는 본인 연결에 저장되며 내 연결에서 언제든 철회할 수 있습니다. 이용 조건은 자동 확인하며, 무료 자격이 확인되지 않거나 유료 호출인 경우 전송하지 않습니다.</p>
        <div className="dialog-footer"><button type="button" className="secondary-button" onClick={onClose}>취소</button><button type="submit" className="primary-button" disabled={saving || loading || (provider === "openrouter" && (!model || !upstreams.length))}>{saving ? <LoaderCircle size={16} className="spin" /> : <KeyRound size={16} />} 동의하고 연결</button></div>
      </form>}
    </>}
    {saving && <p className="stream-notice" role="status"><LoaderCircle size={14} className="spin" /> 연결을 처리하고 있습니다. 이용 조건 확인에 30초~1분 정도 걸릴 수 있습니다.</p>}
    {error && <div className="dialog-alert" role="alert">{error}</div>}
    <div className="dialog-privacy"><ShieldCheck size={15} /><span>서버에 암호화 저장 · 본인 요청에만 사용 · 유료 호출 비활성<br />API 키와 인증 토큰은 채팅에 보내지 마세요.</span></div>
    </div>
    {selected && <aside className="connection-guide" aria-labelledby="connection-guide-title" tabIndex={0}>
      <span className="eyebrow">CONNECTION GUIDE</span>
      <h3 id="connection-guide-title">{selected.name} 처음 연결하는 방법</h3>
      <p className="connection-guide-hint">이 안내를 보면서 왼쪽에서 연결하세요. 작은 화면에서는 위쪽에 입력 폼이 있습니다.</p>
      <ol>{selected.steps.map((step) => <li key={step}>{step}</li>)}</ol>
      <a className="provider-doc-link" href={selected.url} target="_blank" rel="noopener noreferrer">{selected.linkLabel} (새 탭) <ExternalLink size={12} /></a>
      <div className="gemini-warning">{selected.warning}</div>
      {provider === "copilot" && <details className="oauth-setup-guide">
        <summary>운영자 최초 설정: OAuth 앱 등록 화면 2개 보기</summary>
        <p>일반 사용자는 OAuth 앱을 만들 필요가 없습니다. 사이트 로그인 또는 Copilot 연결이 준비 중일 때만 운영자가 아래 두 앱을 각각 등록합니다. Copilot 플랜·기능 설정 화면과는 다릅니다.</p>
        <p>아래는 localhost 예시입니다. 호스팅 환경에서는 Homepage URL과 Redirect URI의 <code>http://localhost:3000</code>을 실제 HTTPS 사이트 주소로 바꿉니다. 두 앱의 Redirect URI를 혼동하지 마세요.</p>
        <GitHubOAuthSetupGuide kind="login" />
        <GitHubOAuthSetupGuide kind="copilot" />
        <p>설정을 마치면 API와 웹의 <code>WAGL_PUBLIC_URL</code>을 같은 사이트 주소로 맞추고 두 서버를 재시작합니다. 사이트 로그인 → Copilot 연결 → GitHub 승인 순서로 진행하세요. Client secret은 채팅·스크린샷·Git에 공유하지 마세요.</p>
        <p>이 설정은 인증·연결 저장을 위한 것입니다. 대화에는 별도 전송 동의와 남은 구독 포함 사용량 확인이 필요합니다. 유료·조직 플랜도 포함량을 지원하며, 전체 추가 과금 차단은 GitHub의 예산 설정이 필요합니다.</p>
      </details>}
    </aside>}
    </div>
  </dialog>;
}
