# The unified runtime — spec for `agentctl dev`

Part of [`agentctl` — a Next.js-style CLI for building, running, and deploying LangChain agents](./PLAN.md).

This is the core of the product. Phase 1 implements exactly this.

## 3. The unified runtime — the heart of the design


Two runtime modes. Both give the user *one command, one URL, frontend already talking to the agent*. `agent.yaml` picks one; `agentctl dev` behaves identically from the user's side.

### Mode A — `proxy` (default; works with Python **or** JS agents)

Two processes, one origin. This is the generalized `js-langsmith` pattern.

```
                    http://localhost:3000          ← the only URL the user opens
┌──────────────────────────────────────────────┐
│  Next.js dev server (frontend, owns origin)  │
│                                              │
│   /            → chat UI (useStream)         │
│   /api/agent/* → proxy ──────────────┐       │
└──────────────────────────────────────┼───────┘
                                       │  no CORS: same origin
                                       ▼
                         http://127.0.0.1:2024   ← `langgraph dev`, hot reload
                         Agent Server: /threads /runs /assistants /ok /info /docs
```

`agentctl dev` supervises both:

1. resolve `agent.yaml`, sync `langgraph.json`, load `.env.local`
2. preflight: ports 2024/3000 free, deps installed, model key present
3. spawn `langgraph dev --no-browser --host 127.0.0.1 --port 2024`
4. **poll `http://127.0.0.1:2024/ok`** until healthy (this gate is the difference between "works" and "flaky")
5. spawn the frontend dev server with `AGENT_PROXY_TARGET=http://127.0.0.1:2024`
6. open **one** browser tab at `:3000`; print a panel with UI, Agent API, `/docs`, and the Studio deep link
7. interleave both logs with colored `[agent]` / `[web]` prefixes; one Ctrl-C tears both down; if either dies, report which and why and shut the other down cleanly

**Prod is the same picture with one value changed.** After deploy, `AGENT_PROXY_TARGET` becomes the deployed Agent Server URL and the proxy — running server-side in a Next.js route handler — **injects `x-api-key: $LANGSMITH_API_KEY` there**, so the key is never in the browser. The frontend source does not change between dev and prod. (Note: the reference Vite proxy does *not* inject auth, because it only ever targets a local server. Ours must, since it targets a real deployment. This is a deliberate, security-motivated extension of the pattern.)

Next.js implementation: a catch-all route handler at `app/api/agent/[...path]/route.ts` (`runtime = "nodejs"`, `dynamic = "force-dynamic"`) that streams the upstream response body through untouched. A `next.config` rewrite is *not* sufficient — it cannot inject the auth header and can buffer SSE.

### Mode B — `embedded` (JS only; literally one process)

The `js-next` shape: the agent lives inside Next.js route handlers implementing the Agent Streaming Protocol. `agentctl dev` runs `next dev` and nothing else. No Agent Server, no port 2024, **no LangSmith plan required**, and `agentctl deploy` ships a single Vercel app. This is the answer for users with no LangSmith Plus, and the cheapest path to production.

Trade-off surfaced honestly at scaffold time: Mode B has no durable Agent Server, so checkpointing, cron, background runs, and multi-replica SSE replay are yours to wire (Redis/Postgres checkpointer + shared session registry). Mode A gets all of it for free.

### Choosing (the wizard decides for the user, and explains why)

| | Mode A `proxy` | Mode B `embedded` |
|---|---|---|
| Agent language | Python or JS | JS/TS only |
| Processes in dev | 2 (one command) | 1 |
| LangSmith plan to deploy | Plus+ (or self-host standalone) | none |
| Durable threads, cron, background runs | built in | you wire it |
| Studio / time travel | yes | partial |
| Deploy shape | Agent Server + static/SSR frontend | one Vercel app |

Python agent ⇒ Mode A, always. JS agent ⇒ ask.

---
