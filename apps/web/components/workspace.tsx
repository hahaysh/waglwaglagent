"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import {
  Activity as ActivityIcon, ArrowUp, Check, ChevronRight, Copy,
  GitBranch, LogIn, KeyRound, LoaderCircle, LogOut, Menu, MessageSquare,
  Paperclip, Plus, RefreshCw, Search, ShieldCheck, Square, Trash2, X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api as requestApi, consumeStream, errorMessage, notifySessionChange, type Activity, type ChatAttachment, type ChatMessage, type Conversation, type Credential } from "@/lib/api";
import { attachmentAccept, readAttachments } from "@/lib/chat-attachments";
import { ConnectionDialog } from "@/components/connection-dialog";
import { connectionProviders, connectionStateDescriptions, connectionStateLabels, type ConnectionProvider } from "@/lib/connection-providers";
import { pickSuggestions } from "@/lib/prompt-suggestions";

type View = "chat" | "connections" | "activity";
type Props = {
  user: { id: string; name: string } | null; authConfigured: boolean;
  initialProvider?: ConnectionProvider; connectionResult?: string;
  loginProvider: string;
  sessionId: string;
  onLogout: () => Promise<void>;
};

export function Workspace({ user, authConfigured, initialProvider, connectionResult, loginProvider, sessionId, onLogout }: Props) {
  const [view, setView] = useState<View>(connectionResult || initialProvider ? "connections" : "chat");
  const [suggestionSeed, setSuggestionSeed] = useState(0);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activity, setActivity] = useState<Activity[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [readingFiles, setReadingFiles] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [connectionsState, setConnectionsState] = useState<"loading" | "ready" | "error">(user ? "loading" : "ready");
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState(Boolean(initialProvider));
  const [dialogProvider, setDialogProvider] = useState<ConnectionProvider | undefined>(initialProvider);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedConnection, setSelectedConnection] = useState("");
  const controller = useRef<AbortController | null>(null);
  const lifetime = useRef<AbortController | null>(null);
  if (!lifetime.current) lifetime.current = new AbortController();
  const mounted = useRef(true);
  const bottom = useRef<HTMLDivElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const connectionStatus = useRef<HTMLElement>(null);
  const approved = credentials.filter((credential) => credential.approved && (
    (credential.usage_state ? credential.usage_state === "available" : credential.status === "valid")
    || (credential.provider === "copilot" && credential.auth_type === "oauth"
      && credential.auth_status === "authenticated" && credential.upstreams.join() === "github-copilot"
      && ["copilot_check_required", "copilot_plan_not_free", "copilot_overage_enabled"].includes(credential.usage_state || ""))
  ));
  const canSend = Boolean(user && connectionsState === "ready" && (selectedConnection
    ? approved.some((credential) => credential.id === selectedConnection) : approved.length));
  const showConnectionStatus = Boolean(user && !busy && !canSend);
  const suggestions = useMemo(
    () => pickSuggestions(user ? conversations.map((chat) => chat.title) : [], suggestionSeed),
    [user, conversations, suggestionSeed],
  );
  const blockedConnections = selectedConnection
    ? credentials.filter((credential) => credential.id === selectedConnection) : credentials;

  const api = useCallback(function sessionApi<T>(path: string, options?: RequestInit) {
    return requestApi<T>(path, {
      ...options, signal: options?.signal
        ? AbortSignal.any([lifetime.current!.signal, options.signal]) : lifetime.current!.signal,
    }, sessionId);
  }, [sessionId]);

  useEffect(() => {
    mounted.current = true;
    setSuggestionSeed(Math.floor(Math.random() * 2 ** 31) + 1);
    if (lifetime.current?.signal.aborted) lifetime.current = new AbortController();
    return () => { mounted.current = false; lifetime.current?.abort(); controller.current?.abort(); };
  }, []);

  function addConnection() {
    setDialog(true);
  }

  function goLogin(returnTo = "/") {
    window.location.assign(`/login?callbackUrl=${encodeURIComponent(returnTo)}`);
  }

  useEffect(() => {
    if (!connectionResult && !initialProvider) return;
    window.history.replaceState(null, "", "/");
    if (connectionResult) {
      if (connectionResult === "saved") setNotice("연결이 저장됐습니다. 저장된 전송 동의를 유지하고 이용 조건을 자동 확인합니다.");
      else setError(connectionResult === "oauth_cancelled" ? "GitHub 승인이 취소됐습니다. 연결은 저장하지 않았습니다."
        : "인증을 완료하지 못했습니다. 세션·연결 수·운영자 설정을 확인하고 다시 연결해주세요.");
    }
  }, [connectionResult, initialProvider]);

  const loadWorkspace = useCallback(async (verifyCopilot = false) => {
    const [keys, chats] = await Promise.all([api<Credential[]>("credentials"), api<Conversation[]>("conversations")]);
    if (!verifyCopilot) return { keys, chats, verificationError: "" };
    const results = await Promise.allSettled(keys.map((credential) =>
      credential.provider === "copilot" && credential.approved
        && credential.auth_type === "oauth" && credential.auth_status === "authenticated"
        && credential.upstreams.join() === "github-copilot"
        ? api<Credential>(`credentials/${credential.id}/verify`, {
          method: "POST", body: "{}", signal: AbortSignal.timeout(40000),
        }) : Promise.resolve(credential),
    ));
    const errors: string[] = [];
    const checkedKeys = results.map((result, index) => {
      if (result.status === "fulfilled") return result.value;
      const credential = keys[index];
      errors.push(`${credential.label}: ${result.reason instanceof Error ? result.reason.message : errorMessage("verification_unavailable")}`);
      return { ...credential, status: "unverified", usage_state: "verification_unavailable" };
    });
    return { keys: checkedKeys, chats, verificationError: errors.join("\n") };
  }, [api]);

  async function refresh(verifyCopilot = false) {
    if (!user || !mounted.current) return;
    if (verifyCopilot) setConnectionsState("loading");
    try {
      const { keys, chats, verificationError } = await loadWorkspace(verifyCopilot);
      if (!mounted.current) return;
      setCredentials(keys); setConversations(chats); setConnectionsState("ready");
      if (verificationError) setError(verificationError);
    } catch (reason) {
      setConnectionsState("error");
      throw reason;
    }
  }

  const userId = user?.id;
  useEffect(() => {
    if (!userId) return;
    let active = true;
    setConnectionsState("loading");
    loadWorkspace(true)
      .then(({ keys, chats, verificationError }) => {
        if (active) {
          setCredentials(keys); setConversations(chats); setConnectionsState("ready");
          if (verificationError) setError(verificationError);
        }
      })
      .catch((reason: Error) => { if (active) { setError(reason.message); setConnectionsState("error"); } });
    return () => { active = false; controller.current?.abort(); };
  }, [userId, loadWorkspace]);

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
    if (busy || readingFiles) return;
    setLoading(true);
    try {
      const chat = await api<{ messages: ChatMessage[] }>(`conversations/${id}`);
      setMessages(chat.messages); setConversationId(id); setView("chat"); setSidebarOpen(false); setError("");
    } catch (reason) { setError((reason as Error).message); }
    finally { setLoading(false); }
  }

  function newChat() {
    if (busy || readingFiles) return;
    setMessages([]); setConversationId(null); setPrompt(""); setAttachments([]); setError(""); setView("chat"); setSidebarOpen(false);
    setSuggestionSeed(Math.floor(Math.random() * 2 ** 31) + 1);
    textarea.current?.focus();
  }

  async function stop() {
    controller.current?.abort();
    try { await api("cancel", { method: "POST", body: "{}" }); } catch { setNotice("응답 연결을 중지했습니다."); }
  }

  async function send() {
    if ((!prompt.trim() && !attachments.length) || busy || readingFiles) return;
    if (!user) { goLogin(); return; }
    if (!canSend) {
      connectionStatus.current?.focus();
      return;
    }
    const content = prompt;
    const files = attachments;
    const userMessageId = crypto.randomUUID();
    const assistantId = crypto.randomUUID();
    setPrompt(""); setAttachments([]); setBusy(true); setError(""); setNotice("");
    setMessages((previous) => [...previous,
      { id: userMessageId, role: "user", content, attachments: files, status: "complete" },
      { id: assistantId, role: "assistant", content: "", status: "streaming" },
    ]);
    const abort = new AbortController();
    controller.current = abort;
    let terminal = false;
    let accepted = false;
    try {
      const response = await fetch("/api/gateway/chat", {
        method: "POST", headers: { "Content-Type": "application/json", "X-Wagl-Session": sessionId },
        signal: AbortSignal.any([abort.signal, lifetime.current!.signal]),
        body: JSON.stringify({
          prompt: content, conversation_id: conversationId, request_id: crypto.randomUUID(),
          credential_id: selectedConnection || null,
          attachments: files,
        }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        if (response.status === 401 || payload.detail === "Session changed") notifySessionChange();
        throw new Error(errorMessage(payload.detail || "unknown"));
      }
      accepted = true;
      await consumeStream(response, (event, payload) => {
        if (event === "conversation") setConversationId(String(payload.id));
        if (event === "attempt") {
          setMessages((previous) => previous.map((message) => message.id === assistantId
            ? { ...message, provider: String(payload.provider), model: String(payload.model) } : message));
          setNotice(Number(payload.number) > 1 ? `허용된 연결로 전환됨 · ${payload.model}` : "");
        }
        if (event === "delta") setMessages((previous) => previous.map((message) => message.id === assistantId
          ? { ...message, content: message.content + String(payload.text) } : message));
        if (event === "model") setMessages((previous) => previous.map((message) => message.id === assistantId
          ? { ...message, model: String(payload.model) } : message));
        if (event === "error") { terminal = true; setError(errorMessage(String(payload.code))); }
        if (event === "done") { terminal = true; setMessages((previous) => previous.map((message) => message.id === assistantId
          ? { ...message, status: "complete" } : message)); }
      });
      if (!terminal) setError("연결이 끊겨 응답이 중단됐습니다.");
    } catch (reason) {
      if (!accepted) {
        setPrompt(content); setAttachments(files);
        setMessages((previous) => previous.filter((message) => message.id !== userMessageId && message.id !== assistantId));
      }
      if ((reason as Error).name !== "AbortError") setError((reason as Error).message);
    } finally {
      setMessages((previous) => previous.map((message) => message.id === assistantId && message.status === "streaming"
        ? { ...message, status: "interrupted" } : message));
      setBusy(false); controller.current = null;
      await refresh().catch((reason: Error) => setError(reason.message));
    }
  }

  async function addAttachments(files: File[]) {
    if (busy || readingFiles || !files.length) return;
    setReadingFiles(true); setError("");
    try {
      const result = await readAttachments(files, attachments);
      if (mounted.current) setAttachments(result);
    }
    catch (reason) { setError((reason as Error).message); }
    finally { setReadingFiles(false); }
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
    let verifyCopilot = false;
    try {
      if (action === "delete") {
        const result = await api<{ detail?: string } | undefined>(`credentials/${credential.id}`, { method: "DELETE" });
        setNotice(result?.detail === "local_disconnect_only"
          ? "이 사이트의 연결은 삭제됐지만 GitHub의 승인 철회는 실패했습니다. GitHub 설정 → Applications → Authorized OAuth Apps에서도 직접 철회해주세요."
          : "연결을 삭제했습니다.");
      }
      if (action === "verify") {
        const checked = await api<Credential>(`credentials/${credential.id}/verify`, { method: "POST", body: "{}" });
        setNotice(checked.usage_state === "available" ? "남은 포함 사용량을 확인했습니다. 매 전송 전 다시 검사합니다."
          : "");
      }
      if (action === "toggle") {
        const currentConsent = credential.approved && (credential.provider !== "copilot"
          || credential.upstreams.join() === "github-copilot");
        const consent = priority === undefined ? !currentConsent : currentConsent;
        if (priority === undefined && consent && credential.provider === "copilot"
          && !confirm("대화와 기존 이력을 GitHub Copilot 및 Copilot이 선택한 모델 제공자로 전송하는 데 동의할까요? 남은 포함 사용량이 확인될 때만 전송하며, 소진되거나 이미 초과 사용 중이면 차단합니다. 다른 앱의 동시 사용이나 처리 중 소진까지 포함한 추가 과금 차단은 GitHub 예산 설정이 필요합니다. 기존 구독료는 별도입니다.")) return;
        await api(`credentials/${credential.id}`, {
          method: "PATCH", body: JSON.stringify({ approved: consent,
            priority: priority ?? credential.priority,
            upstreams: credential.provider === "copilot" && consent ? ["github-copilot"] : credential.upstreams }),
        });
        verifyCopilot = priority === undefined && consent && credential.provider === "copilot";
      }
      await refresh(verifyCopilot);
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
          {user ? <div className="account"><span className="avatar">{user.name.slice(0, 1)}</span><span>{user.name}<small>{loginProvider} · 개인 작업공간</small></span><button className="icon-button" title="로그아웃" aria-label="로그아웃" onClick={() => { void onLogout().catch((reason: Error) => setError(reason.message)); }}><LogOut size={16} /></button></div>
            : <button className="login-button" onClick={() => goLogin()}><LogIn size={18} /> 로그인</button>}
        </div>
      </aside>

      <div className="workspace-main">
        <header className="topbar">
          <div className="breadcrumb"><button className="icon-button mobile-menu" title="메뉴 열기" aria-label="메뉴 열기" onClick={() => setSidebarOpen(true)}><Menu size={20} /></button><span>작업공간</span><ChevronRight size={13} /><strong>{view === "chat" ? "대화" : view === "connections" ? "내 연결" : "사용 기록"}</strong></div>
          <div className="topbar-actions">
            <span className="free-policy" title="무료 모델 또는 구독 포함량을 확인해 전송합니다. Copilot 전체 과금 차단은 제공자의 예산 설정이 필요합니다."><ShieldCheck size={14} /> 무료·구독 포함량 사용</span>
            {!user && <button className="topbar-login" onClick={() => goLogin()}><LogIn size={15} /> 로그인</button>}
          </div>
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
                  <p>{user ? "무엇이든 물어보세요. 아래 예시를 눌러 시작할 수도 있습니다." : "먼저 둘러보세요. 메시지를 보내거나 연결을 추가할 때 로그인으로 안내합니다. 로그인 전에는 입력한 내용이 서버로 전송되지 않습니다."}</p>
                  <div className="prompt-suggestions">
                    {suggestions.map((suggestion) => <button key={suggestion.id} title={suggestion.prompt}
                      onClick={() => { setPrompt(suggestion.prompt); textarea.current?.focus(); }}>
                      <span>{suggestion.recent && <small>이전 질문</small>}<em>{suggestion.label}</em></span><ArrowUp size={14} />
                    </button>)}
                  </div>
                  <p className="prompt-test-help">선택하면 입력창에만 채워지며 전송 전에 수정할 수 있습니다. 전송 시 포함 사용량이 소모될 수 있습니다.</p>
                </div>}
                {messages.map((message) => <article key={message.id} className={`message ${message.role}`}>
                  <div className="message-author">{message.role === "user" ? <span className="message-avatar">{user?.name.slice(0, 1) || "U"}</span> : <span className="message-avatar assistant"><GitBranch size={15} /></span>}<strong>{message.role === "user" ? "나" : connectionProviders.find((entry) => entry.id === message.provider)?.name || "AI"}</strong>{message.model && <span className="message-model" title={message.model}>{message.model.split("/").pop()}</span>}</div>
                  {!!message.attachments?.length && <ChatAttachments files={message.attachments} />}
                  {(message.content || message.role === "assistant") && <div className="markdown">{message.content ? <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={{
                    a: ({ children, href }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
                    img: ({ alt }) => <span>{alt || "외부 이미지"}</span>,
                  }}>{message.content}</ReactMarkdown> : busy ? <span className="thinking"><LoaderCircle size={15} className="spin" /> 응답을 기다리는 중</span> : <span className="muted">응답 없음</span>}</div>}
                  {message.role === "assistant" && message.content && <div className="message-actions"><button className="icon-button" title="응답 복사" aria-label="응답 복사" onClick={() => copy(message.content)}><Copy size={14} /></button>{message.status === "interrupted" && <span className="interrupted">중단됨</span>}</div>}
                </article>)}
                <div ref={bottom} />
              </div>
              <div className="composer-area">
                {notice && <div className="stream-notice" role="status"><Check size={13} />{notice}</div>}
                {!user && !authConfigured && <div className="setup-notice"><KeyRound size={13} /> 로그인 설정 대기</div>}
                {showConnectionStatus && <section id="chat-connection-status" className="chat-connection-status" role="status"
                  aria-label="대화 연결 상태" aria-busy={loading || connectionsState === "loading"} tabIndex={-1} ref={connectionStatus}>
                  <strong>{connectionsState === "loading" ? "연결 상태를 불러오는 중입니다." : "메시지를 아직 전송할 수 없습니다."}</strong>
                  {connectionsState === "ready" && error && <p role="alert">{error}</p>}
                  {connectionsState === "error" ? <>
                    <p>연결 상태를 불러오지 못했습니다. {error || "서버 연결을 확인해주세요."} 입력한 메시지는 전송되지 않았습니다.</p>
                    <button className="text-button" type="button" onClick={() => {
                      setConnectionsState("loading"); setError("");
                      void refresh().catch((reason: Error) => setError(reason.message));
                    }}><RefreshCw size={14} /> 연결 상태 새로고침</button>
                  </> : connectionsState === "ready" && <>
                    <p>입력한 메시지는 전송되지 않았습니다. {credentials.length ? "아래 연결 상태를 확인해주세요." : "AI 연결을 추가하고 전송에 동의해주세요."}</p>
                    {blockedConnections.map((credential) => <div className="chat-blocked-connection" key={credential.id}>
                      <strong>{credential.label} · {connectionStateLabels[credential.usage_state || ""] || "이용 조건 확인 필요"}</strong>
                      <p>{connectionStateDescriptions[credential.usage_state || ""] || "이 연결의 이용 조건을 확인할 수 없습니다. 연결 설정에서 인증·전송 동의·사용 상태를 확인해주세요."}</p>
                      {credential.provider === "copilot" && credential.auth_status === "authenticated"
                        && !["consent_required", "copilot_consent_required", "reauth_required"].includes(credential.usage_state || "") &&
                        <button className="text-button" type="button" disabled={loading} onClick={() => keyAction(credential, "verify")}>
                          <RefreshCw size={14} className={loading ? "spin" : ""} />{loading ? "이용 조건 확인 중…" : `${credential.label} 이용 조건 다시 확인`}
                        </button>}
                    </div>)}
                    {selectedConnection && blockedConnections.length === 0 && <p>선택한 연결이 삭제됐거나 더 이상 존재하지 않습니다.</p>}
                    <div className="chat-connection-actions">
                      {selectedConnection && approved.length > 0 && <button className="text-button" type="button" disabled={loading} onClick={() => setSelectedConnection("")}>사용 가능한 자동 연결로 바꾸기</button>}
                      <button className="text-button" type="button" disabled={loading} onClick={() => credentials.length ? void navigate("connections") : addConnection()}>
                        {credentials.length ? "연결 설정 열기" : "연결 추가"}
                      </button>
                    </div>
                  </>}
                </section>}
                <form className="composer" onSubmit={(event) => { event.preventDefault(); void send(); }}
                  onDragOver={(event) => { if (event.dataTransfer.types.includes("Files")) event.preventDefault(); }}
                  onDrop={(event) => { if (event.dataTransfer.files.length) { event.preventDefault(); void addAttachments(Array.from(event.dataTransfer.files)); } }}>
                  <input ref={fileInput} type="file" className="attachment-input" aria-label="이미지 또는 텍스트 파일 첨부" accept={attachmentAccept}
                    multiple disabled={busy || readingFiles} onChange={(event) => {
                      void addAttachments(Array.from(event.target.files || [])); event.target.value = "";
                    }} />
                  {!!attachments.length && <ChatAttachments files={attachments} onRemove={readingFiles ? undefined : (index) => setAttachments((files) => files.filter((_, position) => position !== index))} />}
                  <textarea ref={textarea} aria-label="메시지" aria-describedby={showConnectionStatus ? "chat-connection-status" : "attachment-help"} placeholder="메시지를 입력하세요 · 스크린샷 붙여넣기 가능" value={prompt} maxLength={8000} rows={3} disabled={busy}
                    onPaste={(event) => {
                      if (event.clipboardData.files.length) {
                        event.preventDefault(); void addAttachments(Array.from(event.clipboardData.files));
                      }
                    }}
                    onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); } }} />
                  <div className="composer-footer"><div className="composer-left">
                    <label className="connection-chip" title={selectedConnection ? "선택한 연결만 사용하며 다른 서비스로 넘어가지 않습니다." : "동의한 무료·구독 포함량 연결을 우선순위 순으로 사용합니다."}>
                      <GitBranch size={13} />
                      <select aria-label="대화에 사용할 연결" value={selectedConnection} disabled={busy || !user}
                        onChange={(event) => setSelectedConnection(event.target.value)}>
                        <option value="">자동 · 우선순위 순</option>
                        {credentials.map((credential) => <option key={credential.id} value={credential.id}
                          disabled={!approved.some((entry) => entry.id === credential.id)}>
                          {credential.label} · {connectionStateLabels[credential.usage_state || ""] || credential.status}
                        </option>)}
                      </select>
                    </label>
                    {(busy || readingFiles || !user) && <span className="composer-status">{busy ? "연결 확인·응답 처리 중…" : readingFiles ? "첨부 읽는 중…" : "전송 시 로그인 화면으로 이동"}</span>}
                  </div><div><button type="button" className="icon-button" aria-label="파일 첨부" title="이미지·텍스트 파일 첨부 (PNG·JPEG·WebP 각 2MB/16MP, UTF-8 텍스트·코드 각 32KB)" disabled={busy || readingFiles || attachments.length >= 3} onClick={() => fileInput.current?.click()}><Paperclip size={18} /></button><small>{prompt.length}/8000</small>{busy ? <button type="button" className="send-button stopping" title="응답 중지" aria-label="응답 중지" onClick={stop}><Square size={15} fill="currentColor" /></button> : <button type="submit" className="send-button" aria-label="메시지 전송" aria-describedby={showConnectionStatus ? "chat-connection-status" : undefined} title={!user ? "로그인 후 전송" : !canSend ? "전송할 수 없는 이유를 입력창 위에서 확인해주세요." : "메시지 전송"} disabled={(!prompt.trim() && !attachments.length) || (Boolean(user) && !canSend) || readingFiles}><ArrowUp size={19} /></button>}</div></div>
                </form>
                <p id="attachment-help" className="attachment-help">첨부 최대 3개·합계 4MB · 이미지는 Copilot만 지원 · 첨부는 선택한 서비스로 전송되고 대화와 함께 저장됩니다.</p>
                <p className="composer-disclaimer">AI 응답에는 오류가 있을 수 있습니다. 중요한 내용은 확인하세요.</p>
              </div>
            </section>
            <aside className="provider-rail">
              <div className="rail-heading"><span>내 연결</span><button className="icon-button" title="연결 추가" aria-label="연결 추가" onClick={addConnection}><Plus size={17} /></button></div>
              <ProviderSummary provider="copilot" credentials={credentials} />
              <ProviderSummary provider="gemini" credentials={credentials} />
              <ProviderSummary provider="openrouter" credentials={credentials} />
              <button className="rail-link" onClick={() => navigate("connections")}>연결 관리 <ChevronRight size={14} /></button>
              <div className="routing-diagram"><span className="eyebrow">ROUTING</span><div className="route-node"><MessageSquare size={15} /> 내 메시지</div><span className="route-line" /><div className="route-node policy"><ShieldCheck size={15} /> 전송 동의 · 무료·포함량 확인</div><span className="route-line" /><div className="route-node"><GitBranch size={15} /> 허용된 제공자</div></div>
              <div className="rail-note"><ShieldCheck size={16} /><span>전송 전 남은 구독 포함량 확인</span></div>
            </aside>
          </div>}

          {view === "connections" && <section className="management-view">
            <div className="view-heading"><div><span className="eyebrow">CONNECTIONS</span><h1>내 연결</h1><p>개인 API 키와 전송 동의</p></div><button className="primary-button" onClick={addConnection}><Plus size={16} /> 연결 추가</button></div>
            {!user && <div className="empty-state"><KeyRound size={26} /><h2>로그인 후 연결을 등록하세요</h2><p>등록한 키와 연결은 로그인한 본인 계정에만 저장되고 본인 요청에만 사용됩니다.</p><button className="text-button" onClick={() => goLogin("/?connect=copilot")}>로그인</button></div>}
            {user && credentials.length === 0 && <div className="empty-state"><KeyRound size={26} /><h2>등록된 연결이 없습니다</h2><button className="text-button" onClick={() => setDialog(true)}>첫 연결 추가 <ArrowUp size={14} /></button></div>}
            <div className="connection-list">{credentials.map((credential) => <div className="connection-row" key={credential.id}>
              <ProviderLogo provider={credential.provider} /><div className="connection-detail"><strong>{credential.label}</strong><span>{credential.model || connectionProviders.find((entry) => entry.id === credential.provider)?.name}</span><small>{credential.auth_type === "oauth" ? "OAuth 연결" : "API 키 연결"} · {credential.auth_status === "reauth_required" ? "재인증 필요" : "인증됨"}</small><small>{credential.upstreams.join(", ")}</small><span className={`credential-status ${credential.usage_state === "available" ? "valid" : ""}`}>{connectionStateLabels[credential.usage_state || ""] || (credential.status === "valid" ? "키 확인됨" : "무료 자격 미확인")}</span>{credential.provider === "copilot" && <><small>{credential.quota_snapshot.plan && `공식 조회 플랜: ${credential.quota_snapshot.plan} · `}{credential.checked_at ? `확인: ${new Date(credential.checked_at).toLocaleString("ko-KR")}` : "이용 조건을 다시 확인하세요."} 매 요청 전 남은 포함량·초과 사용 여부를 재검사합니다.</small><p>개인 유료·Business·Enterprise 구독도 추가 요금 없는 포함 사용량은 이용할 수 있습니다. 기존 구독료는 별도입니다. 다른 앱의 동시 사용이나 응답 중 소진까지 추가 과금을 막으려면 GitHub의 예산·사용 중지를 설정하세요.</p>{credential.quota_snapshot.overage_allowed && <p>GitHub의 소진 후 초과 사용이 허용돼 있습니다. 앱은 남은 포함량을 확인하지만 다른 앱의 동시 사용이나 처리 중 소진까지 과금을 보장하지는 못합니다. 추가 과금을 확실히 차단하려면 GitHub의 예산·사용 중지를 설정하세요.</p>}</>}{["copilot_plan_not_free", "copilot_overage_enabled", "copilot_overage_in_use"].includes(credential.usage_state || "") && <p>{connectionStateDescriptions[credential.usage_state || ""]}</p>}{credential.auth_type === "oauth" && <button className="text-button" onClick={() => { setDialogProvider("copilot"); setDialog(true); }}>Copilot 다시 연결</button>}</div>
              <div className="connection-controls"><label className="priority-control">우선순위 <input type="number" min={0} max={100} aria-label={`${credential.label} 우선순위`} defaultValue={credential.priority} disabled={loading} onBlur={(event) => { const priority = Number(event.target.value); if (Number.isInteger(priority) && priority >= 0 && priority <= 100 && priority !== credential.priority) void keyAction(credential, "toggle", priority); }} /></label><label className="switch-label"><input type="checkbox" role="switch" aria-label={`${credential.label} 전송 동의`} checked={credential.approved && (credential.provider !== "copilot" || credential.upstreams.join() === "github-copilot")} disabled={loading} onChange={() => keyAction(credential, "toggle")} /><span className="switch-track" /> 전송 동의</label><button className={credential.provider === "copilot" ? "text-button" : "icon-button"} aria-label={`${credential.label} ${credential.provider === "copilot" ? "이용 조건 다시 확인" : "키 다시 확인"}`} title="자격 다시 확인" disabled={loading} onClick={() => keyAction(credential, "verify")}><RefreshCw size={16} />{credential.provider === "copilot" && "이용 조건 다시 확인"}</button><button className="icon-button danger" title="연결 삭제" aria-label={`${credential.label} 연결 삭제`} disabled={loading} onClick={() => keyAction(credential, "delete")}><Trash2 size={16} /></button></div>
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
      {dialog && <ConnectionDialog signal={lifetime.current.signal} sessionId={sessionId} authenticated={Boolean(user)} authConfigured={authConfigured} initialProvider={dialogProvider} onLogin={(provider) => goLogin(`/?connect=${provider}`)} onClose={() => { setDialog(false); setDialogProvider(undefined); }} onSaved={async () => { await refresh(); setDialog(false); setDialogProvider(undefined); setNotice("연결이 저장됐습니다. 전송 동의는 유지되며 이용 조건이 확인된 연결만 사용할 수 있습니다."); }} />}
    </div>
  );
}

function ChatAttachments({ files, onRemove }: { files: ChatAttachment[]; onRemove?: (index: number) => void }) {
  return <ul className="chat-attachments" aria-label="첨부 파일">
    {files.map((file, index) => <li key={`${index}-${file.name}`}>
      <a href={`data:${file.mime_type};base64,${file.data}`} download={file.name} title={`${file.name} 다운로드`}>
        {file.mime_type.startsWith("image/") ? <Image src={`data:${file.mime_type};base64,${file.data}`}
          alt={`${file.name} 미리보기`} width={112} height={72} unoptimized /> : <Paperclip size={22} />}
        <span>{file.name}</span>
      </a>
      {onRemove && <button type="button" className="icon-button" aria-label={`${file.name} 첨부 삭제`} title="첨부 삭제" onClick={() => onRemove(index)}><X size={14} /></button>}
    </li>)}
  </ul>;
}

export function ProviderLogo({ provider }: { provider: string }) {
  if (!["gemini", "openrouter"].includes(provider)) return <span className="provider-logo" aria-hidden="true"><KeyRound size={22} /></span>;
  return <span className={`provider-logo ${provider}`}><Image src={provider === "gemini" ? "/gemini.png" : "/openrouter.png"} width={24} height={24} alt="" unoptimized /></span>;
}

function ProviderSummary({ provider, credentials }: { provider: "gemini" | "openrouter" | "copilot"; credentials: Credential[] }) {
  const keys = credentials.filter((credential) => credential.provider === provider);
  const enabled = keys.some((credential) => credential.approved && (credential.usage_state
    ? credential.usage_state === "available" : credential.status === "valid"));
  const snapshotKey = keys.find((credential) => credential.quota_snapshot.daily);
  const daily = snapshotKey?.quota_snapshot.daily;
  return <div className="provider-summary"><div className="provider-title"><ProviderLogo provider={provider} /><strong>{connectionProviders.find((entry) => entry.id === provider)?.name}</strong><span className={`status-dot ${enabled ? "online" : ""}`} /></div>
    <div className="provider-state">{keys.length ? enabled ? "무료·포함량 대화 가능 · 전송 전 재검사" : connectionStateLabels[keys[0].usage_state || ""] || "전송 미허용" : "미연결"}</div>
    <div className="quota-line"><span>무료 일일 잔여</span><strong>{daily ? `${daily.remaining.toLocaleString()}회` : "알 수 없음"}</strong></div>
    {daily && <div className="quota-meter"><span style={{ width: `${Math.max(0, Math.min(100, daily.remaining / Math.max(1, daily.limit) * 100))}%` }} /></div>}
    {daily && <small className="quota-source">공식 조회값 · {snapshotKey?.checked_at ? new Date(snapshotKey.checked_at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }) : "시각 미확인"}</small>}
  </div>;
}