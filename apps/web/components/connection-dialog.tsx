"use client";

import { useEffect, useRef, useState } from "react";
import { ExternalLink, KeyRound, LoaderCircle, ShieldCheck, X } from "lucide-react";
import { api, type Endpoint, type Model } from "@/lib/api";

export function ConnectionDialog({ onClose, onSaved }: { onClose: () => void; onSaved: () => Promise<void> }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [provider, setProvider] = useState<"openrouter" | "gemini">("openrouter");
  const [models, setModels] = useState<Model[]>([]);
  const [model, setModel] = useState("");
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [upstreams, setUpstreams] = useState<string[]>([]);
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [approved, setApproved] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { dialog.current?.showModal(); }, []);
  useEffect(() => {
    if (provider !== "openrouter") return;
    let active = true;
    api<{ models: Model[] }>("catalog").then((catalog) => { if (active) setModels(catalog.models); })
      .catch((reason: Error) => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [provider]);

  useEffect(() => {
    if (provider !== "openrouter" || !model) return;
    let active = true;
    api<{ endpoints: Endpoint[] }>(`endpoints?model=${encodeURIComponent(model)}`)
      .then((result) => { if (active) { setEndpoints(result.endpoints); setLoading(false); } })
      .catch((reason: Error) => { if (active) { setError(reason.message); setLoading(false); } });
    return () => { active = false; };
  }, [provider, model]);

  async function save(event: React.FormEvent) {
    event.preventDefault(); setSaving(true); setError("");
    try {
      await api("credentials", { method: "POST", body: JSON.stringify({ provider, label, api_key: apiKey, model, upstreams, approved }) });
      setApiKey("");
      await onSaved();
    } catch (reason) { setError((reason as Error).message); }
    finally { setSaving(false); }
  }

  function chooseProvider(next: "openrouter" | "gemini") {
    setProvider(next); setModel(""); setEndpoints([]); setUpstreams([]); setApproved(false); setError(""); setLoading(false);
  }

  return <dialog ref={dialog} className="connection-dialog" onCancel={onClose} onClick={(event) => { if (event.target === dialog.current) onClose(); }}>
    <form onSubmit={save}><div className="dialog-heading"><div><span className="eyebrow">NEW CONNECTION</span><h2>개인 연결 추가</h2></div><button type="button" className="icon-button" aria-label="연결 창 닫기" title="닫기" onClick={onClose}><X size={20} /></button></div>
      <div className="segmented" role="group" aria-label="제공자"><button type="button" className={provider === "openrouter" ? "selected" : ""} onClick={() => chooseProvider("openrouter")}>OpenRouter</button><button type="button" className={provider === "gemini" ? "selected" : ""} onClick={() => chooseProvider("gemini")}>Gemini</button></div>
      {error && <div className="dialog-alert" role="alert">{error}</div>}
      <label className="field-label">연결 이름<input autoFocus required maxLength={80} placeholder="내 OpenRouter" value={label} onChange={(event) => setLabel(event.target.value)} /></label>
      <label className="field-label"><span>API 키 <a href={provider === "openrouter" ? "https://openrouter.ai/settings/keys" : "https://aistudio.google.com/apikey"} target="_blank" rel="noopener noreferrer">발급 페이지 <ExternalLink size={12} /></a></span><div className="key-input"><KeyRound size={16} /><input type="password" autoComplete="off" required minLength={8} maxLength={500} placeholder="API 키" value={apiKey} onChange={(event) => setApiKey(event.target.value)} /></div></label>
      {provider === "openrouter" ? <>
        <label className="field-label">무료 모델<select aria-label="무료 모델" required value={model} onChange={(event) => { setModel(event.target.value); setUpstreams([]); setEndpoints([]); setApproved(false); setLoading(Boolean(event.target.value)); setError(""); }}><option value="">모델 선택</option>{models.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}</select></label>
        <fieldset className="upstream-field"><legend>허용할 실제 처리업체</legend>{loading && <span className="thinking"><LoaderCircle size={14} className="spin" /> 조회 중</span>}{!loading && model && endpoints.length === 0 && <span className="muted">현재 무료 처리업체를 확인할 수 없습니다.</span>}
          {endpoints.map((endpoint) => <label key={endpoint.id} className="checkbox-row"><input type="checkbox" aria-label={endpoint.name} checked={upstreams.includes(endpoint.id)} onChange={(event) => setUpstreams(event.target.checked ? [...upstreams, endpoint.id] : upstreams.filter((item) => item !== endpoint.id))} /><span>{endpoint.name}<small>{endpoint.id}</small></span></label>)}
        </fieldset>
      </> : <><label className="field-label">모델 ID<input required maxLength={200} placeholder="발급 서비스의 모델 ID" value={model} onChange={(event) => setModel(event.target.value)} /></label><div className="gemini-warning">API 키만으로 무료 결제 등급을 확인할 수 없어 등록 후 호출은 차단됩니다.</div></>}
      <label className="consent-checkbox"><input type="checkbox" checked={approved} disabled={provider === "gemini" || upstreams.length === 0} onChange={(event) => setApproved(event.target.checked)} /><span>이 제공자와 선택한 처리업체에 메시지 및 대화 이력을 전송하는 데 동의합니다.</span></label>
      <div className="dialog-privacy"><ShieldCheck size={15} /><span>본인 요청에만 사용 · 암호화 저장<br />제공자의 보관·학습 정책이 적용됩니다.</span></div>
      <div className="dialog-footer"><button type="button" className="secondary-button" onClick={onClose}>취소</button><button type="submit" className="primary-button" disabled={saving || loading || !model || (provider === "openrouter" && models.length === 0)}>{saving ? <LoaderCircle size={16} className="spin" /> : <KeyRound size={16} />} 연결 저장</button></div>
    </form>
  </dialog>;
}