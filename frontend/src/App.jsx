import React, { useState, useEffect, useRef } from "react";

// The dev server proxies /api -> the FastAPI backend (see vite.config.js),
// so we call /api/chat from the browser with no CORS hassle.
const CHAT_URL = "/api/chat";
const HEALTH_URL = "/api/health";

const EXAMPLES = [
  "How many stars does fastapi/fastapi have?",
  "What languages is fastapi/fastapi written in?",
  "How many followers does torvalds have?",
  "Compare fastapi/fastapi stars with torvalds's followers.",
  "Show the latest commits on fastapi/fastapi.",
];

export default function App() {
  const [messages, setMessages] = useState([]); // {role, text, tools?, steps?, id?, ms?}
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [online, setOnline] = useState(null); // null=unknown, true/false
  const scrollRef = useRef(null);
  const inputRef = useRef(null);
  const sessionIdRef = useRef(null); // conversation id for server-side memory

  // health check on load
  useEffect(() => {
    fetch(HEALTH_URL)
      .then((r) => setOnline(r.ok))
      .catch(() => setOnline(false));
    inputRef.current?.focus();
  }, []);

  // auto-scroll to newest message
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  async function send(question) {
    const q = (question ?? input).trim();
    if (!q || loading) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text: q }]);
    setLoading(true);
    const started = performance.now();

    try {
      const res = await fetch(CHAT_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: q,
          ...(sessionIdRef.current ? { session_id: sessionIdRef.current } : {}),
        }),
      });
      const ms = Math.round(performance.now() - started);

      if (!res.ok) {
        const detail = await res.text();
        setMessages((m) => [...m, { role: "error", text: `HTTP ${res.status}: ${detail}` }]);
        return;
      }

      const data = await res.json();
      sessionIdRef.current = data.session_id; // remember conversation for follow-ups
      setMessages((m) => [
        ...m,
        {
          role: "agent",
          text: data.answer,
          tools: data.tool_calls.map((t) => t.name),
          steps: data.steps,
          id: data.request_id,
          ms,
        },
      ]);
    } catch (e) {
      setMessages((m) => [
        ...m,
        { role: "error", text: `Request failed: ${e.message}. Is the API running?` },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={S.page}>
      <StyleTag />
      <div style={S.card}>
        {/* header */}
        <div style={S.header}>
          <div style={S.logo}>🐙</div>
          <div style={{ flex: 1 }}>
            <h1 style={S.h1}>GitHub Insights Agent</h1>
            <p style={S.sub}>Ask about any public GitHub repo or user — powered by tool-calling AI.</p>
          </div>
          <div style={S.statusWrap} title={online === false ? "API offline" : "API online"}>
            <span
              style={{
                ...S.dot,
                background: online === false ? "#ef4444" : online ? "#22c55e" : "#eab308",
                boxShadow: `0 0 0 3px ${online === false ? "#ef444433" : online ? "#22c55e33" : "#eab30833"}`,
              }}
            />
            <span style={S.statusText}>{online === false ? "offline" : online ? "online" : "…"}</span>
          </div>
          <button
            className="chip"
            style={S.newChat}
            onClick={() => {
              sessionIdRef.current = null;
              setMessages([]);
              inputRef.current?.focus();
            }}
            disabled={loading || messages.length === 0}
            title="Start a new conversation (clears memory)"
          >
            + New chat
          </button>
        </div>

        {/* chat area */}
        <div style={S.chat} ref={scrollRef}>
          {messages.length === 0 && (
            <div style={S.empty}>
              <div style={S.emptyIcon}>💬</div>
              <div style={S.emptyTitle}>Start a conversation</div>
              <div style={S.emptyHint}>Try one of the suggestions below.</div>
            </div>
          )}

          {messages.map((m, i) => (
            <Row key={i} role={m.role}>
              <div style={{ ...S.bubble, ...bubbleStyle(m.role) }}>
                <div style={S.bubbleText}>{m.text}</div>
                {(m.tools || m.steps != null) && (
                  <div style={S.metaRow}>
                    {(m.tools?.length ? m.tools : ["no tools"]).map((t, k) => (
                      <span key={k} style={S.toolBadge}>🔧 {t}</span>
                    ))}
                    {m.steps != null && <span style={S.metaChip}>{m.steps} steps</span>}
                    {m.ms != null && <span style={S.metaChip}>{m.ms} ms</span>}
                  </div>
                )}
              </div>
            </Row>
          ))}

          {loading && (
            <Row role="agent">
              <div style={{ ...S.bubble, ...bubbleStyle("agent"), display: "flex", gap: 6, alignItems: "center" }}>
                <span className="dot-a" style={S.tdot} />
                <span className="dot-b" style={S.tdot} />
                <span className="dot-c" style={S.tdot} />
              </div>
            </Row>
          )}
        </div>

        {/* example chips */}
        <div style={S.examples}>
          {EXAMPLES.map((ex) => (
            <button key={ex} className="chip" style={S.chip} onClick={() => send(ex)} disabled={loading}>
              {ex}
            </button>
          ))}
        </div>

        {/* input */}
        <div style={S.inputRow}>
          <input
            ref={inputRef}
            style={S.input}
            placeholder="Ask about a repo or user…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            disabled={loading}
          />
          <button className="send" style={S.send} onClick={() => send()} disabled={loading || !input.trim()}>
            {loading ? "…" : "Send ↑"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Row({ role, children }) {
  const isUser = role === "user";
  return (
    <div style={{ display: "flex", gap: 10, justifyContent: isUser ? "flex-end" : "flex-start", alignItems: "flex-end" }}>
      {!isUser && <div style={S.avatar}>{role === "error" ? "⚠️" : "🐙"}</div>}
      {children}
      {isUser && <div style={{ ...S.avatar, background: "#2563eb", color: "#fff" }}>you</div>}
    </div>
  );
}

function bubbleStyle(role) {
  if (role === "user") return { background: "#2563eb", color: "#fff", borderBottomRightRadius: 4 };
  if (role === "error") return { background: "#fef2f2", color: "#991b1b", border: "1px solid #fecaca", borderBottomLeftRadius: 4 };
  return { background: "#fff", color: "#0f172a", border: "1px solid #e2e8f0", borderBottomLeftRadius: 4 };
}

function StyleTag() {
  return (
    <style>{`
      * { box-sizing: border-box; }
      body { margin: 0; }
      @keyframes bounce { 0%,80%,100% { transform: translateY(0); opacity:.5 } 40% { transform: translateY(-5px); opacity:1 } }
      .dot-a { animation: bounce 1.2s infinite ease-in-out; }
      .dot-b { animation: bounce 1.2s infinite ease-in-out .18s; }
      .dot-c { animation: bounce 1.2s infinite ease-in-out .36s; }
      .chip { transition: all .15s; }
      .chip:hover:not(:disabled) { background:#eef2ff !important; border-color:#818cf8 !important; transform: translateY(-1px); }
      .send { transition: all .15s; }
      .send:hover:not(:disabled) { background:#1d4ed8 !important; }
      .send:disabled { opacity:.5; cursor:not-allowed; }
      .chip:disabled { opacity:.5; cursor:not-allowed; }
      ::-webkit-scrollbar { width: 8px; }
      ::-webkit-scrollbar-thumb { background:#cbd5e1; border-radius:8px; }
    `}</style>
  );
}

const S = {
  page: {
    minHeight: "100vh", display: "flex", justifyContent: "center", alignItems: "center",
    background: "linear-gradient(135deg,#1e293b 0%,#0f172a 50%,#312e81 100%)",
    padding: 24, fontFamily: "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
  },
  card: {
    width: "100%", maxWidth: 720, height: "min(88vh, 760px)", background: "#f8fafc",
    borderRadius: 20, boxShadow: "0 20px 60px rgba(0,0,0,.45)", display: "flex",
    flexDirection: "column", overflow: "hidden", border: "1px solid rgba(255,255,255,.08)",
  },
  header: {
    display: "flex", alignItems: "center", gap: 14, padding: "18px 22px",
    background: "#fff", borderBottom: "1px solid #e2e8f0",
  },
  logo: {
    width: 44, height: 44, borderRadius: 12, display: "grid", placeItems: "center",
    fontSize: 24, background: "linear-gradient(135deg,#6366f1,#8b5cf6)",
  },
  h1: { margin: 0, fontSize: 18, fontWeight: 700, color: "#0f172a", letterSpacing: -0.2 },
  sub: { margin: "2px 0 0", color: "#64748b", fontSize: 13 },
  statusWrap: { display: "flex", alignItems: "center", gap: 6 },
  dot: { width: 9, height: 9, borderRadius: "50%", display: "inline-block" },
  statusText: { fontSize: 12, color: "#64748b", textTransform: "uppercase", letterSpacing: 0.5 },
  newChat: { border: "1px solid #cbd5e1", background: "#fff", borderRadius: 999, padding: "6px 12px", fontSize: 12, cursor: "pointer", color: "#334155", whiteSpace: "nowrap" },

  chat: { flex: 1, display: "flex", flexDirection: "column", gap: 14, overflowY: "auto", padding: 22 },
  empty: { margin: "auto", textAlign: "center", color: "#94a3b8" },
  emptyIcon: { fontSize: 40, marginBottom: 8 },
  emptyTitle: { fontSize: 16, fontWeight: 600, color: "#475569" },
  emptyHint: { fontSize: 13, marginTop: 4 },

  avatar: {
    width: 32, height: 32, minWidth: 32, borderRadius: 10, background: "#e2e8f0",
    display: "grid", placeItems: "center", fontSize: 15, fontWeight: 600, color: "#475569",
  },
  bubble: { maxWidth: "78%", padding: "12px 15px", borderRadius: 16, fontSize: 14.5, lineHeight: 1.5, boxShadow: "0 1px 2px rgba(0,0,0,.05)" },
  bubbleText: { whiteSpace: "pre-wrap" },
  metaRow: { display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10, paddingTop: 8, borderTop: "1px solid rgba(0,0,0,.07)" },
  toolBadge: { fontSize: 11, background: "#ecfdf5", color: "#047857", border: "1px solid #a7f3d0", borderRadius: 999, padding: "2px 8px", fontWeight: 500 },
  metaChip: { fontSize: 11, background: "#f1f5f9", color: "#64748b", borderRadius: 999, padding: "2px 8px" },
  tdot: { width: 7, height: 7, borderRadius: "50%", background: "#94a3b8", display: "inline-block" },

  examples: { display: "flex", flexWrap: "wrap", gap: 8, padding: "0 22px 14px" },
  chip: { border: "1px solid #cbd5e1", background: "#fff", borderRadius: 999, padding: "7px 13px", fontSize: 12.5, cursor: "pointer", color: "#334155" },

  inputRow: { display: "flex", gap: 10, padding: "14px 22px 20px", background: "#fff", borderTop: "1px solid #e2e8f0" },
  input: { flex: 1, padding: "13px 16px", border: "1px solid #cbd5e1", borderRadius: 12, fontSize: 14.5, outline: "none", background: "#f8fafc" },
  send: { background: "#2563eb", color: "#fff", border: "none", borderRadius: 12, padding: "0 22px", fontSize: 14, fontWeight: 600, cursor: "pointer" },
};
