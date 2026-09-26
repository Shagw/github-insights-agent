# 🐙 GitHub Insights Agent

An **async AI agent** that answers natural-language questions about public GitHub
repositories and users. It uses Google Gemini to reason, and calls the **GitHub
REST API as tools** in a bounded Reason → Act → Observe loop — then grounds every
answer in the data the tools returned.

> Ask *"How many stars does fastapi/fastapi have, and what languages is it written in?"*
> and the agent decides which tools to call, fetches the data, and answers.

Built as a backend-focused portfolio project: the emphasis is on the **agent loop,
tool design, resilience, observability, and tests** — not a heavy UI.

---

## ✨ What it does

- **Tool-calling agent** — Gemini chooses which GitHub API calls to make, with
  arguments, to answer a question. Supports **multi-step** questions (chaining
  several tool calls before answering).
- **Four read-only tools** — repo info, user info, language breakdown, recent commits.
- **Strict argument validation** — every tool call the model produces is validated
  with Pydantic (`extra="forbid"`) before execution; bad arguments are fed back to
  the model to self-correct instead of crashing.
- **Resilient GitHub client** — timeouts, retry-with-backoff on transient failures,
  a TTL cache, and graceful handling of GitHub's rate limit.
- **Production-shaped API** — FastAPI with `/chat`, `/health`, `/metrics`, auto
  `/docs`, request tracing, usage counters, API-key auth, and CORS.
- **Tested & evaluated** — 35 offline unit tests plus a behavioral eval harness.

---

## 🧠 How it works

```
                          ┌──────────────────────────────────────┐
  user question ─────────►│           run_agent() loop           │
                          │  (Reason → Act → Observe, bounded)    │
                          └──────────────────────────────────────┘
                                   │                ▲
                    send question  │                │ tool result
                    + tool specs   ▼                │ (or validation error)
                          ┌─────────────────┐       │
                          │   Gemini LLM    │       │
                          └─────────────────┘       │
                                   │                │
                    function call  │                │
                    {name, args}   ▼                │
                          ┌─────────────────────────┴──┐
                          │ validate args (Pydantic)   │
                          │ → dispatch async tool       │
                          └─────────────────────────────┘
                                   │
                                   ▼
                          ┌─────────────────────────────┐
                          │  GitHubClient (async httpx)  │
                          │  timeouts · retry · cache    │
                          └─────────────────────────────┘
                                   │
                                   ▼
                           GitHub REST API
```

1. The question and the **tool declarations** go to Gemini.
2. If Gemini replies with a **function call**, the agent validates the arguments,
   runs the matching async tool, and sends the result back.
3. Gemini observes the result and either calls another tool or writes the final
   answer. A `MAX_STEPS` cap guarantees termination.

---

## 🛠️ Tech stack

| Layer | Choice | Why |
|-------|--------|-----|
| Language | **Python 3.13** | Strong typing + best LLM ecosystem |
| LLM | **Gemini `gemini-flash-latest`** | Free tier, native function calling |
| Tool validation | **Pydantic v2** | Validates untrusted LLM args at the boundary |
| HTTP client | **httpx (async)** | Async I/O + built-in timeouts for the resilience story |
| External API | **GitHub REST API** | Public data; optional token raises the rate limit |
| Web framework | **FastAPI** | Typed, async, auto `/docs` |
| Server | **uvicorn** | ASGI runtime |
| Tests | **pytest** + TestClient | Deterministic, fully offline |

---

## 📁 Project structure

```
github-agent/
├── app/
│   ├── config.py          # settings from .env (keys, model, token, API key, CORS)
│   ├── key_manager.py     # rotate up to 5 Gemini keys with cooldown
│   ├── github_client.py   # async GitHub client: timeouts, retry/backoff, TTL cache
│   ├── tools.py           # the 4 tools (shape GitHub JSON into small clean dicts)
│   ├── schemas.py         # Pydantic arg schemas + Gemini function declarations
│   ├── agent.py           # the async Reason→Act→Observe loop
│   └── api.py             # FastAPI: /chat /health /metrics /docs + middleware
├── tests/                 # 35 offline tests (faked GitHub + faked LLM)
├── eval/                  # behavioral eval set + scoring harness
├── demo.py                # drives the running API with example questions
├── requirements.txt
└── .env.example
```

---

## 🔧 The tools

| Tool | GitHub endpoint | Returns |
|------|-----------------|---------|
| `get_repo_info(owner, repo)` | `/repos/{owner}/{repo}` | stars, forks, open issues, language, topics, description |
| `get_user_info(username)` | `/users/{username}` | name, bio, company, location, public repos, followers |
| `list_languages(owner, repo)` | `/repos/{owner}/{repo}/languages` | language breakdown as **percentages** |
| `list_recent_commits(owner, repo, limit)` | `/repos/{owner}/{repo}/commits` | recent commits (sha, message, author, date) |

---

## 🚀 Run it locally

### 1. Install
```bash
git clone <your-repo-url>
cd github-agent

python3.13 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
```
Edit `.env`:
- `GEMINI_API_KEY_1` — get one free at https://aistudio.google.com/app/apikey
  (add up to 5 keys for rotation)
- `GITHUB_TOKEN` — **optional**; without it you get 60 requests/hour, with it 5000
- `API_KEY` — optional; if set, `/chat` requires the `X-API-Key` header

### 3. Start the API
```bash
uvicorn app.api:app --reload
```
Open the interactive docs at **http://localhost:8000/docs** — you can call `/chat`
right from the browser.

### 4. Try the demo script
```bash
python demo.py
# or a single question:
python demo.py "What languages is fastapi/fastapi written in?"
```

### Example `curl`
```bash
curl -s http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"question": "How many stars does fastapi/fastapi have?"}' | jq
```

---

## ✅ Testing

All tests run **offline** — GitHub is faked with `httpx.MockTransport` and the LLM
is faked with a scripted `FakeChat`, so no network or API quota is used.

```bash
pytest                       # 35 tests
```

Covers: the resilient client (retry / no-retry / cache), tool response shaping,
schema validation, the agent loop (single-tool, multi-tool, error recovery,
refusal), and every API endpoint (auth, tracing, error mapping, CORS).

---

## 📊 Evaluation

Unit tests check code correctness; the **eval harness** checks *agent behavior* —
does it call the right tools and ground its answer?

```bash
# offline: verify the grading logic against ideal outcomes (no Gemini)
python -m eval.run_eval --self-test

# live: run the real agent over the eval set (needs Gemini keys + network)
python -m eval.run_eval
```

The set has **15 cases** across three categories: single-tool (8), multi-tool (3),
and out-of-scope/refuse (4). Each is graded on tool selection **and** answer content.

---

## 💡 Design decisions (the interesting bits)

- **Async throughout.** GitHub calls use `httpx.AsyncClient`; the synchronous Gemini
  SDK is wrapped in `asyncio.to_thread` so it never blocks the event loop. This keeps
  the API responsive under concurrent load.
- **Resilience lives in one layer.** All retry/backoff/caching/rate-limit logic is in
  `github_client.py`, so every tool inherits it and the tools stay pure and testable.
- **Transient vs. permanent errors.** Only transient failures (timeouts, 5xx) are
  retried; permanent ones (404, rate-limit 403) are not — retrying them just wastes
  quota.
- **Untrusted LLM output.** Tool arguments are validated with strict Pydantic schemas
  before anything executes; validation errors are returned to the model so it can
  self-correct.
- **Bounded loop.** `MAX_STEPS` guarantees the agent always terminates, even if the
  model keeps requesting tools.
- **Key rotation.** Up to 5 Gemini keys rotate with a cooldown, so a single key's
  free-tier limit doesn't take the service down.
- **Observability.** Every request gets an id, is timed, and is logged; `/metrics`
  exposes simple usage counters.

---

## ⚠️ Known limitations

- **Read-only.** The agent only reads public GitHub data — no writes, by design.
- **In-memory cache & metrics.** Both reset on restart; a multi-instance deployment
  would use Redis / a metrics backend.
- **Gemini free-tier quota.** Live runs are limited by the daily quota; the tests and
  eval self-test are fully offline to work around this.
- **No conversation memory across requests.** Each `/chat` call is independent (stateless).

---

## 📄 License

MIT — free to use and adapt.
