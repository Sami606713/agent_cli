# LangChain platform research

Part of [`agentctl` — a Next.js-style CLI for building, running, and deploying LangChain agents](./PLAN.md).

## 1. Context


`agent_cli` is an empty repo. The goal: a CLI where one command scaffolds a production LangChain/LangGraph agent (backend, or backend + frontend), **one command runs the whole thing as a single app** — frontend and agent already talking to each other, like `next dev` — and one command deploys both, wired, to a cloud of the user's choice.

The **unified-runtime requirement is the core of the product**, not a convenience. Today a user assembles it by hand: start `langgraph dev` in one terminal, start the UI in another, copy `http://localhost:2024` into an env var, hit CORS, fix CORS, then repeat the whole dance with a different URL after deploying. `agentctl` collapses that into `agentctl dev` and `agentctl deploy`.

### 1.1 The decisive research finding

LangChain's own `js-langsmith` cookbook **already implements exactly this pattern**, and it is the blueprint to generalize:

```jsonc
// package.json
"dev":       "concurrently -n agent,web -c blue,green \"pnpm dev:agent\" \"pnpm dev:web\"",
"dev:agent": "langgraphjs dev --no-browser --host 127.0.0.1",   // Agent Server on :2024
"dev:web":   "wait-on http-get://127.0.0.1:2024/ok && vite"     // UI waits for the agent, then boots
```

```ts
// scripts/vite-langgraph-proxy.ts  → server.proxy
target: process.env.LANGGRAPH_PROXY_TARGET ?? "http://127.0.0.1:2024"
changeOrigin: true, timeout: 600_000, proxyTimeout: 600_000       // long agent runs
paths: "/api/langgraph" (rewrite: strip prefix), "/threads", "/runs",
       "/assistants", "/sandbox", "/download", "/ok", "/info"
```

Four mechanisms make it work, and every one of them generalizes to Next.js and to Python backends:

1. **`concurrently`** supervises both processes under one Ctrl-C with labeled, colored output.
2. **`wait-on .../ok`** gates the UI on the Agent Server's health endpoint, so the frontend never boots against a dead backend — this is what removes the race that makes hand-rolled setups flaky.
3. **A same-origin dev proxy** forwards the Agent Server's API surface. Same origin ⇒ **CORS never happens**, and the browser talks to `/api/agent/...`, never to `:2024` directly.
4. **One env var flips the target.** `LANGGRAPH_PROXY_TARGET` unset ⇒ local `:2024`. Set ⇒ a deployed Agent Server. **The frontend code is byte-identical in dev and prod.** This is the hinge the entire deploy story hangs on.

Long timeouts (600s) are not incidental: agent runs are long, and a default 30s proxy timeout silently kills SSE streams mid-run.

### 1.2 Everything else verified (docs.langchain.com, Aug 2026)

| Fact | Consequence |
|---|---|
| `langgraph.json` is the universal contract (`graphs`, `dependencies`, `env`, `auth`, `store`, `http`, `ui`, `checkpointer`, `webhooks`, `base_image`, `image_distro`, `python_version`/`node_version`, `pip_installer`) | Every template exports a graph through it. The one invariant making all runtimes and deploy targets interchangeable. |
| `langgraph dev`: no Docker, hot reload by default, port **2024**, health at `/ok`, OpenAPI at `/docs`, `--no-browser`, `--host`, `--port` | The backend half of `agentctl dev`. `--no-browser` is required — *we* own what opens. |
| `langgraph up` = Docker, port 8123, `--watch` opt-in | The "production-like" local mode: `agentctl dev --docker`. |
| `langgraph build` / `dockerfile` / `deploy` (+ `deploy list/logs/delete/revisions`), `--deployment-type serverless\|dedicated` (or `dev\|prod` pre-Oct-2026 pricing) | We wrap, never reimplement. |
| Deployment environments: Cloud (**Plus plan+**), Self-hosted control plane (**Enterprise**), Hybrid (**Enterprise**), **Standalone Agent Server** (Docker/Compose/K8s + your Postgres/Redis + license key) | Standalone is the "any cloud" path. Docs: **never** run standalone on serverless/scale-to-zero (task loss). |
| Standalone env contract: `REDIS_URI`, `DATABASE_URI`, `LANGSMITH_API_KEY`, `LANGGRAPH_CLOUD_LICENSE_KEY`, optional `LANGSMITH_ENDPOINT` (no trailing slash), egress to `beacon.langchain.com`; shared PG/Redis needs distinct db name / db index | Exactly what provider adapters provision and validate. |
| `js-next` cookbook: agent **inside** Next.js route handlers implementing the Agent Streaming Protocol — `POST /api/threads/:id/commands`, `POST /api/threads/:id/stream` (SSE), `GET\|POST /api/threads/:id/state`, plus `GET /api/threads`, `DELETE /api/threads/:id`, `POST /api/threads/:id/history`. Needs `runtime = "nodejs"` + `dynamic = "force-dynamic"`. No separate backend process, no LangSmith plan. | The second runtime mode (§3, Mode B). |
| Frontend SDK v1: `useStream` (React/Vue/Svelte), `injectStream` (Angular), `HttpAgentServerAdapter`, `StreamProvider`; typed state, tool-call lifecycle, interrupts, checkpoints/time-travel, subagent namespacing | The UI is an agent control plane, not a chat log. |
| `langgraph.json` **`ui`** field: colocate React components with the graph; the Agent Server bundles them (Tailwind 4 + shadcn supported) and the client renders them via `LoadExternalComponent` | Genuine two-way frontend↔backend coupling: the *agent* ships UI. Worth first-class support. |
| Templates: `new-langgraph-project(-js)`, `simple-agent-template`, `deep-agent-template(-js)`, `react-agent`, `retrieval-agent-template`, `memory-agent`. Cookbook: `js-langsmith`, `js-next`, `js-nuxt`, `js-sveltekit`, `js-cloudflare`, `js-deno` | We adapt these; our value-add is the unified runtime + deploy wiring. |

### 1.3 Decisions locked with the user

- CLI in **Python** (Typer + Rich), shipped via `uv tool install` / `pipx`.
- v1 deploy targets: **LangSmith Cloud** (backend) + **Vercel** (frontend).
- Authoring model: **`langgraph.json` + `create_agent`**.
- **Local-only OSS CLI**; custom providers via a plugin spec.

---
