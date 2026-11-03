"use client";

import { useEffect, useRef, useState } from "react";
import { signIn, signOut } from "next-auth/react";
import Image from "next/image";
import Link from "next/link";
import {
  Activity as ActivityIcon, ArrowUp, Check, ChevronRight, Copy,
  GitBranch, LogIn, KeyRound, LoaderCircle, LogOut, Menu, MessageSquare,
  Plus, RefreshCw, Search, ShieldCheck, Square, Trash2, X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, consumeStream, errorMessage, type Activity, type ChatMessage, type Conversation, type Credential } from "@/lib/api";
import { ConnectionDialog } from "@/components/connection-dialog";

type View = "chat" | "connections" | "activity";
type Props = { user: { id: string; name: string } | null; authConfigured: boolean };

export function Workspace({ user, authConfigured }: Props) {
  const [view, setView] = useState<View>("chat");
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activity, setActivity] = useState<Activity[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState(false);
  const [loginHelp, setLoginHelp] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState("");
  const controller = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const approved = credentials.filter((credential) => credential.approved && credential.status === "valid");

  function addConnection() {
    if (!user) { setLoginHelp(true); return; }
    setDialog(true);
  }

  async function refresh() {
    if (!user) return;
    const [keys, chats] = await Promise.all([api<Credential[]>("credentials"), api<Conversation[]>("conversations")]);
    setCredentials(keys); setConversations(chats);
  }

  useEffect(() => {
    if (!user) return;
    let active = true;
    Promise.all([api<Credential[]>("credentials"), api<Conversation[]>("conversations")])
      .then(([keys, chats]) => { if (active) { setCredentials(keys); setConversations(chats); } })
      .catch((reason: Error) => { if (active) setError(reason.message); });
    return () => { active = false; controller.current?.abort(); };
  }, [user]);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: busy ? "instant" : "smooth", block: "end" }); }, [messages, busy]);

  async function navigate(next: View) {
    setView(next); setSidebarOpen(false); setError("");
    if (next === "activity" && user) {
      setLoading(true);
      try { setActivity(await api<Activity[]>("activity")); } catch (reason) { setError((reason as Error).message); }
      finally { setLoading(false); }
    }
  }

  async function openConversation(id: string) {
    if (busy) return;
    setLoading(true);
    try {
      const chat = await api<{ messages: ChatMessage[] }>(`conversations/${id}`);
      setMessages(chat.messages); setConversationId(id); setView("chat"); setSidebarOpen(false); setError("");
    } catch (reason) { setError((reason as Error).message); }
    finally { setLoading(false); }
  }

  function newChat() {
    if (busy) return;
    setMessages([]); setConversationId(null); setPrompt(""); setError(""); setView("chat"); setSidebarOpen(false);
    textarea.current?.focus();
  }

  async function stop() {
    controller.current?.abort();
    try { await api("cancel", { method: "POST", body: "{}" }); } catch { setNotice("응답 연결을 중지했습니다."); }
  }

  async function send() {
    if (!prompt.trim() || busy || !user || approved.length === 0) return;
    const content = prompt;
    const userMessageId = crypto.randomUUID();
    const assistantId = crypto.randomUUID();
    setPrompt(""); setBusy(true); setError(""); setNotice("");
    setMessages((previous) => [...previous,
      { id: userMessageId, role: "user", content, status: "complete" },
      { id: assistantId, role: "assistant", content: "", status: "streaming" },
    ]);
    const abort = new AbortController();
    controller.current = abort;
    let terminal = false;
    try {
      const response = await fetch("/api/gateway/chat", {
        method: "POST", headers: { "Content-Type": "application/json" }, signal: abort.signal,
        body: JSON.stringify({ prompt: content, conversation_id: conversationId, request_id: crypto.randomUUID() }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        setPrompt(content);
        setMessages((previous) => previous.filter((message) => message.id !== userMessageId && message.id !== assistantId));
        throw new Error(errorMessage(payload.detail || "unknown"));
      }
      await consumeStream(response, (event, payload) => {
        if (event === "conversation") setConversationId(String(payload.id));
        if (event === "attempt") {
          setMessages((previous) => previous.map((message) => message.id === assistantId
            ? { ...message, provider: String(payload.provider), model: String(payload.model) } : message));
          setNotice(Number(payload.number) > 1 ? `허용된 연결로 전환됨 · ${payload.model}` : "");
        }
        if (event === "delta") setMessages((previous) => previous.map((message) => message.id === assistantId
          ? { ...message, content: message.content + String(payload.text) } : message));
        if (event === "error") { terminal = true; setError(errorMessage(String(payload.code))); }
        if (event === "done") { terminal = true; setMessages((previous) => previous.map((message) => message.id === assistantId
          ? { ...message, status: "complete" } : message)); }
      });
      if (!terminal) setError("연결이 끊겨 응답이 중단됐습니다.");
    } catch (reason) {
      if ((reason as Error).name !== "AbortError") setError((reason as Error).message);
    } finally {
      setMessages((previous) => previous.map((message) => message.id === assistantId && message.status === "streaming"
        ? { ...message, status: "interrupted" } : message));
      setBusy(false); controller.current = null;
      await refresh().catch(() => undefined);
    }
  }

  async function removeConversation(id: string) {
    if (!confirm("이 대화와 사용 기록을 삭제할까요?")) return;
    try {
      await api(`conversations/${id}`, { method: "DELETE" });
      if (conversationId === id) newChat();
      await refresh();
    } catch (reason) { setError((reason as Error).message); }
  }

  async function keyAction(credential: Credential, action: "delete" | "verify" | "toggle", priority?: number) {
    if (action === "delete" && !confirm(`‘${credential.label}’ 연결을 삭제할까요?`)) return;
    setLoading(true); setError("");
    try {
      if (action === "delete") await api(`credentials/${credential.id}`, { method: "DELETE" });
      if (action === "verify") await api(`credentials/${credential.id}/verify`, { method: "POST", body: "{}" });
      if (action === "toggle") await api(`credentials/${credential.id}`, {
        method: "PATCH", body: JSON.stringify({ approved: priority === undefined ? !credential.approved : credential.approved,
          priority: priority ?? credential.priority, upstreams: credential.upstreams }),
      });
      await refresh();
    } catch (reason) { setError((reason as Error).message); }
    finally { setLoading(false); }
  }

  async function copy(content: string) {
    try { await navigator.clipboard.writeText(content); setNotice("응답을 복사했습니다."); }
    catch { setError("클립보드에 접근할 수 없습니다."); }
  }

  return (
    <div className="app-shell">
      {sidebarOpen && <button className="sidebar-scrim" aria-label="메뉴 닫기" onClick={() => setSidebarOpen(false)} />}
      <aside className={`sidebar ${sidebarOpen ? "is-open" : ""}`}>
        <Link className="brand" href="/" aria-label="waglwaglagent 홈"><span className="brand-mark"><GitBranch size={22} /></span><span>waglwagl<span className="brand-agent">agent</span></span></Link>
        <span className="workspace-label">MY WORKSPACE</span>
        <button className="new-chat" onClick={newChat} disabled={busy}><Plus size={17} /> 새 대화 <span className="key-hint"><MessageSquare size={13} /></span></button>
        <nav aria-label="주요 메뉴">
          <button className={view === "chat" ? "nav-item active" : "nav-item"} onClick={() => navigate("chat")}><MessageSquare size={17} /> 대화</button>
          <button className={view === "connections" ? "nav-item active" : "nav-item"} onClick={() => navigate("connections")}><KeyRound size={17} /> 내 연결 <span className="nav-count">{credentials.length}</span></button>
          <button className={view === "activity" ? "nav-item active" : "nav-item"} onClick={() => navigate("activity")}><ActivityIcon size={17} /> 사용 기록</button>
        </nav>
        <div className="history-heading"><span>최근 대화</span><Search size={14} /></div>
        {conversations.length > 0 && <input className="history-search" aria-label="대화 검색" placeholder="대화 검색" value={search} onChange={(event) => setSearch(event.target.value)} />}
        <div className="history-list">
          {conversations.filter((chat) => chat.title.toLowerCase().includes(search.toLowerCase())).map((chat) => (
            <div key={chat.id} className={`history-row ${chat.id === conversationId ? "selected" : ""}`}>
              <button onClick={() => openConversation(chat.id)} disabled={busy} title={chat.title}><MessageSquare size={14} /><span>{chat.title}</span></button>
              <button className="history-delete" title="대화 삭제" aria-label={`${chat.title} 삭제`} onClick={() => removeConversation(chat.id)} disabled={busy}><Trash2 size={13} /></button>
            </div>
          ))}
          {conversations.length === 0 && <span className="muted sidebar-empty">아직 대화가 없습니다</span>}
        </div>
        <div className="sidebar-bottom">
          <div className="privacy-note"><ShieldCheck size={16} /><span>개인 키 · 개인 할당량</span></div>
          {user ? <div className="account"><span className="avatar">{user.name.slice(0, 1)}</span><span>{user.name}<small>개인 작업공간</small></span><button className="icon-button" title="로그아웃" aria-label="로그아웃" onClick={() => signOut()}><LogOut size={16} /></button></div>
            : <button className="login-button" onClick={() => authConfigured ? signIn("github") : setLoginHelp(true)}><LogIn size={18} /> GitHub로 로그인</button>}
        </div>
      </aside>

      <div className="workspace-main">
        <header className="topbar">
          <div className="breadcrumb"><button className="icon-button mobile-menu" title="메뉴 열기" aria-label="메뉴 열기" onClick={() => setSidebarOpen(true)}><Menu size={20} /></button><span>작업공간</span><ChevronRight size={13} /><strong>{view === "chat" ? "대화" : view === "connections" ? "내 연결" : "사용 기록"}</strong></div>
          <span className="free-policy"><ShieldCheck size={14} /> 무료 전용</span>
        </header>

        <main className="main-content">
          {error && <div className="alert" role="alert"><span>{error}</span><button className="icon-button" aria-label="알림 닫기" title="알림 닫기" onClick={() => setError("")}><X size={16} /></button></div>}
          {view === "chat" && <div className="chat-layout">
            <section className="chat-column">
              <div className="chat-heading"><div><span className="eyebrow">CONVERSATION</span><h1>{conversationId ? conversations.find((chat) => chat.id === conversationId)?.title || "대화" : "새 대화"}</h1></div><span className="connection-indicator"><span className={`status-dot ${approved.length ? "online" : ""}`} />{approved.length}개 연결</span></div>
              <div className="message-area" aria-label="대화 내용">
                {messages.length === 0 && <div className="empty-chat">
                  <div className="empty-symbol"><GitBranch size={36} strokeWidth={1.6} /></div>
                  <h2>생각이 이어지는 곳.</h2>
                  <p>{user ? "무엇부터 이야기할까요?" : "대화를 시작하려면 로그인해주세요."}</p>
                  <div className="prompt-suggestions">
                    {["복잡한 개념을 쉽게 풀어줘", "아이디어를 함께 정리해줘", "글의 흐름을 다듬어줘"].map((suggestion) => <button key={suggestion} onClick={() => { setPrompt(suggestion); textarea.current?.focus(); }}><span>{suggestion}</span><ArrowUp size={14} /></button>)}
                  </div>
                </div>}
                {messages.map((message) => <article key={message.id} className={`message ${message.role}`}>
                  <div className="message-author">{message.role === "user" ? <span className="message-avatar">{user?.name.slice(0, 1) || "U"}</span> : <span className="message-avatar assistant"><GitBranch size={15} /></span>}<strong>{message.role === "user" ? "나" : message.provider === "gemini" ? "Gemini" : "OpenRouter"}</strong>{message.model && <span className="message-model" title={message.model}>{message.model.split("/").pop()}</span>}</div>
                  <div className="markdown">{message.content ? <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={{
                    a: ({ children, href }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
                    img: ({ alt }) => <span>{alt || "외부 이미지"}</span>,
                  }}>{message.content}</ReactMarkdown> : busy ? <span className="thinking"><LoaderCircle size={15} className="spin" /> 응답을 기다리는 중</span> : <span className="muted">응답 없음</span>}</div>
                  {message.role === "assistant" && message.content && <div className="message-actions"><button className="icon-button" title="응답 복사" aria-label="응답 복사" onClick={() => copy(message.content)}><Copy size={14} /></button>{message.status === "interrupted" && <span className="interrupted">중단됨</span>}</div>}
                </article>)}
                <div ref={bottom} />
              </div>
              <div className="composer-area">
                {notice && <div className="stream-notice" role="status"><Check size={13} />{notice}</div>}
                {!user && !authConfigured && <div className="setup-notice"><KeyRound size={13} /> GitHub 로그인 설정 대기</div>}
                <form className="composer" onSubmit={(event) => { event.preventDefault(); void send(); }}>
                  <textarea ref={textarea} aria-label="메시지" placeholder="메시지를 입력하세요" value={prompt} maxLength={8000} rows={3} disabled={busy}
                    onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); } }} />
                  <div className="composer-footer"><span><GitBranch size={14} />{approved.length ? "허용된 연결 · 우선순위 순" : "연결 대기"}</span><div><small>{prompt.length}/8000</small>{busy ? <button type="button" className="send-button stopping" title="응답 중지" aria-label="응답 중지" onClick={stop}><Square size={15} fill="currentColor" /></button> : <button type="submit" className="send-button" aria-label="메시지 전송" title={!user ? "로그인 필요" : !approved.length ? "연결 필요" : "메시지 전송"} disabled={!user || !prompt.trim() || !approved.length}><ArrowUp size={19} /></button>}</div></div>
                </form>
                <p className="composer-disclaimer">AI 응답에는 오류가 있을 수 있습니다. 중요한 내용은 확인하세요.</p>
              </div>
            </section>
            <aside className="provider-rail">
              <div className="rail-heading"><span>내 연결</span><button className="icon-button" title="연결 추가" aria-label="연결 추가" onClick={addConnection}><Plus size={17} /></button></div>
              <ProviderSummary provider="gemini" credentials={credentials} />
              <ProviderSummary provider="openrouter" credentials={credentials} />
              <button className="rail-link" onClick={() => navigate("connections")}>연결 관리 <ChevronRight size={14} /></button>
              <div className="routing-diagram"><span className="eyebrow">ROUTING</span><div className="route-node"><MessageSquare size={15} /> 내 메시지</div><span className="route-line" /><div className="route-node policy"><ShieldCheck size={15} /> 전송 동의 · 무료 확인</div><span className="route-line" /><div className="route-node"><GitBranch size={15} /> 허용된 제공자</div></div>
              <div className="rail-note"><ShieldCheck size={16} /><span>유료 모델 전환 없음</span></div>
            </aside>
          </div>}

          {view === "connections" && <section className="management-view">
            <div className="view-heading"><div><span className="eyebrow">CONNECTIONS</span><h1>내 연결</h1><p>개인 API 키와 전송 동의</p></div><button className="primary-button" onClick={addConnection}><Plus size={16} /> 연결 추가</button></div>
            {!user && <div className="empty-state"><KeyRound size={26} /><h2>로그인 후 연결을 등록하세요</h2><p>{authConfigured ? "등록한 키는 본인 요청에만 사용됩니다." : "서버의 GitHub 로그인 설정이 필요합니다. 연결 추가를 눌러 설정 방법을 확인하세요."}</p><button className="text-button" onClick={() => authConfigured ? signIn("github") : setLoginHelp(true)}>{authConfigured ? "GitHub로 로그인" : "로그인 설정 안내"}</button></div>}
            {user && credentials.length === 0 && <div className="empty-state"><KeyRound size={26} /><h2>등록된 연결이 없습니다</h2><button className="text-button" onClick={() => setDialog(true)}>첫 연결 추가 <ArrowUp size={14} /></button></div>}
            <div className="connection-list">{credentials.map((credential) => <div className="connection-row" key={credential.id}>
              <ProviderLogo provider={credential.provider} /><div className="connection-detail"><strong>{credential.label}</strong><span>{credential.model}</span><small>{credential.upstreams.join(", ") || "무료 결제 등급 미확인"}</small><span className={`credential-status ${credential.status === "valid" ? "valid" : ""}`}>{credential.status === "valid" ? "키 확인됨" : credential.status === "invalid" ? "키 오류" : "무료 자격 미확인"}</span></div>
              <div className="connection-controls"><label className="priority-control">우선순위 <input type="number" min={0} max={100} aria-label={`${credential.label} 우선순위`} defaultValue={credential.priority} disabled={loading} onBlur={(event) => { const priority = Number(event.target.value); if (Number.isInteger(priority) && priority >= 0 && priority <= 100 && priority !== credential.priority) void keyAction(credential, "toggle", priority); }} /></label><label className="switch-label"><input type="checkbox" role="switch" aria-label={`${credential.label} 전송 동의`} checked={credential.approved} disabled={loading} onChange={() => keyAction(credential, "toggle")} /><span className="switch-track" /> 전송 동의</label><button className="icon-button" aria-label={`${credential.label} 키 다시 확인`} title="키 다시 확인" disabled={loading} onClick={() => keyAction(credential, "verify")}><RefreshCw size={16} /></button><button className="icon-button danger" title="연결 삭제" aria-label={`${credential.label} 연결 삭제`} disabled={loading} onClick={() => keyAction(credential, "delete")}><Trash2 size={16} /></button></div>
            </div>)}</div>
            <div className="policy-footnote"><ShieldCheck size={16} /><p>키는 암호화해 서버에 저장됩니다. 전송 동의를 철회하면 진행 중 요청도 중지됩니다. 이미 제공자에 전송된 데이터는 회수할 수 없습니다.</p></div>
          </section>}

          {view === "activity" && <section className="management-view"><div className="view-heading"><div><span className="eyebrow">ACTIVITY</span><h1>사용 기록</h1><p>이 앱에서 관측한 요청 · 제공자 전체 사용량과 다를 수 있습니다</p></div><button className="icon-button" title="사용 기록 새로고침" aria-label="사용 기록 새로고침" onClick={() => navigate("activity")} disabled={!user || loading}><RefreshCw size={18} className={loading ? "spin" : ""} /></button></div>
            {!activity.length && <div className="empty-state"><ActivityIcon size={26} /><h2>아직 사용 기록이 없습니다</h2></div>}
            {activity.length > 0 && <div className="activity-table"><table><thead><tr><th>모델</th><th>처리업체</th><th>상태</th><th>토큰</th><th>시간</th></tr></thead><tbody>{activity.map((entry) => <tr key={entry.id}><td><strong>{entry.model}</strong><small>{entry.provider}</small></td><td>{entry.upstreams.join(", ") || "Google"}</td><td><span className={`credential-status ${entry.status === "complete" ? "valid" : ""}`}>{entry.status === "complete" ? "완료" : entry.status === "cancelled" ? "취소" : "중단/실패"}</span></td><td>{entry.usage.total_tokens?.toLocaleString() ?? "미확인"}</td><td>{new Date(entry.created_at).toLocaleString("ko-KR")}</td></tr>)}</tbody></table></div>}
          </section>}
          {loading && <span className="loading-status" role="status"><LoaderCircle size={15} className="spin" /> 불러오는 중</span>}
        </main>
      </div>
      {dialog && <ConnectionDialog onClose={() => setDialog(false)} onSaved={async () => { await refresh(); setDialog(false); }} />}
      {loginHelp && <ConnectionLoginHelp authConfigured={authConfigured} onClose={() => setLoginHelp(false)} />}
    </div>
  );
}

function ConnectionLoginHelp({ authConfigured, onClose }: { authConfigured: boolean; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="connection-dialog" aria-labelledby="connection-login-title" onCancel={onClose} onClick={(event) => { if (event.target === dialog.current) onClose(); }}>
    <div className="dialog-heading"><h2 id="connection-login-title">{authConfigured ? "연결 추가 전 로그인이 필요합니다" : "GitHub 로그인 설정이 필요합니다"}</h2><button className="icon-button" aria-label="로그인 안내 닫기" onClick={onClose}><X size={20} /></button></div>
    <p>개인 연결을 안전하게 저장하려면 먼저 waglwaglagent에 로그인해야 합니다. AI 제공자 연결과는 별도입니다.</p>
    {!authConfigured && <>
      <p>현재 서버에 GitHub OAuth 정보가 설정되지 않아 로그인할 수 없습니다. 운영자는 다음 설정을 완료해주세요.</p>
      <ol>
        <li><a href="https://github.com/settings/developers" target="_blank" rel="noopener noreferrer">GitHub OAuth Apps</a>에서 앱을 등록합니다.</li>
        <li>Homepage URL은 이 사이트 주소, Callback URL은 사이트 주소 뒤에 <code>/api/auth/callback/github</code>를 붙입니다.</li>
        <li>서버의 <code>apps/web/.env.local</code>에 <code>AUTH_GITHUB_ID</code>와 <code>AUTH_GITHUB_SECRET</code>을 설정합니다.</li>
        <li>웹 서버를 재시작한 뒤 로그인하고 연결을 추가합니다.</li>
      </ol>
      <p>Client secret과 API 키는 채팅에 보내지 마세요. 호스팅 환경에서는 서버 환경 변수로 설정하세요.</p>
    </>}
    <div className="dialog-footer"><button className="secondary-button" onClick={onClose}>닫기</button>{authConfigured && <button className="primary-button" onClick={() => signIn("github")}><LogIn size={16} /> GitHub로 로그인</button>}</div>
  </dialog>;
}

export function ProviderLogo({ provider }: { provider: string }) {
  return <span className={`provider-logo ${provider}`}><Image src={provider === "gemini" ? "/gemini.png" : "/openrouter.png"} width={24} height={24} alt="" unoptimized /></span>;
}

function ProviderSummary({ provider, credentials }: { provider: "gemini" | "openrouter"; credentials: Credential[] }) {
  const keys = credentials.filter((credential) => credential.provider === provider);
  const enabled = keys.some((credential) => credential.approved && credential.status === "valid");
  const snapshotKey = keys.find((credential) => credential.quota_snapshot.daily);
  const daily = snapshotKey?.quota_snapshot.daily;
  return <div className="provider-summary"><div className="provider-title"><ProviderLogo provider={provider} /><strong>{provider === "gemini" ? "Gemini" : "OpenRouter"}</strong><span className={`status-dot ${enabled ? "online" : ""}`} /></div>
    <div className="provider-state">{keys.length ? enabled ? "전송 허용됨" : provider === "gemini" ? "무료 자격 미확인" : "전송 미허용" : "미연결"}</div>
    <div className="quota-line"><span>무료 일일 잔여</span><strong>{daily ? `${daily.remaining.toLocaleString()}회` : "알 수 없음"}</strong></div>
    {daily && <div className="quota-meter"><span style={{ width: `${Math.max(0, Math.min(100, daily.remaining / Math.max(1, daily.limit) * 100))}%` }} /></div>}
    {daily && <small className="quota-source">공식 조회값 · {snapshotKey?.checked_at ? new Date(snapshotKey.checked_at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }) : "시각 미확인"}</small>}
  </div>;
}