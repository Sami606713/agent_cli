# `agentctl` — a Next.js-style CLI for building, running, and deploying LangChain agents

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

## 2. Non-goals (v1)

Visual builder; LangSmith replacement; hosted dashboard; billing; Terraform for AWS/GCP (Phase 5).

---

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

## 4. Architecture

```
agent_cli/
├─ pyproject.toml                    # agentctl = agentctl.main:app
├─ src/agentctl/
│  ├─ main.py
│  ├─ commands/                      # new dev build deploy env providers doctor logs rollback destroy eject sync add
│  ├─ core/
│  │  ├─ spec.py                     # AgentSpec (pydantic) ← single source of truth
│  │  ├─ manifest.py                 # agent.yaml + .agentctl/state.json
│  │  ├─ render.py                   # Jinja2 template renderer
│  │  ├─ supervisor.py               # ★ process supervisor: spawn, health-gate, log-mux, teardown
│  │  ├─ health.py                   # /ok polling, port probing, readiness backoff
│  │  ├─ langgraph_cli.py            # subprocess wrapper for dev/build/dockerfile/deploy/up
│  │  ├─ wiring.py                   # ★ backend outputs → frontend env, both modes
│  │  ├─ secrets.py                  # keyring + .env.local; never into state.json
│  │  ├─ preflight.py                # doctor + capability validation
│  │  └─ errors.py                   # typed errors with fix hints
│  ├─ providers/                     # base.py, langsmith_cloud.py, vercel.py, compose_ssh.py,
│  │                                 # flyio.py, render.py, ecs.py, cloudrun.py, k8s_helm.py, custom.py
│  └─ templates/
│     ├─ backend/{minimal,react_agent,rag,deep_agent,multi_agent}/
│     ├─ frontend/{nextjs_proxy,vite_proxy,nextjs_embedded}/
│     └─ shared/{proxy,ci,docker,eval,docs}/
```

`core/supervisor.py` is the most load-bearing new code in the project, and the piece nothing upstream provides for Python backends: cross-platform process groups, health-gated sequential startup, interleaved log multiplexing, and guaranteed teardown (including orphan reaping when the parent is SIGKILLed).

### 4.1 `AgentSpec` (`agent.yaml`)

```yaml
version: 1
name: support-agent
runtime: python              # python | node
template: react_agent
mode: proxy                  # proxy | embedded   ← picks the runtime shape
model:  { provider: anthropic, name: claude-opus-5 }
memory: { checkpointer: postgres, store: postgres, semantic_search: true }
frontend:
  enabled: true
  kind: nextjs_proxy         # nextjs_proxy | vite_proxy | nextjs_embedded | none
  port: 3000
  proxy_prefix: /api/agent
  generative_ui: true        # emits langgraph.json `ui` + LoadExternalComponent wiring
backend: { port: 2024 }
observability: { langsmith: true, project: support-agent }
deploy:
  backend:  { provider: langsmith_cloud, deployment_type: serverless }
  frontend: { provider: vercel }
environments: [dev, staging, prod]
```

`langgraph.json` is generated from this and kept in sync by `agentctl sync`, merging rather than clobbering hand edits (unknown keys preserved, drift reported, `--force` to overwrite owned keys).

### 4.2 Provider interface

```python
class Capabilities(BaseModel):
    kind: Literal["backend", "frontend", "both"]
    serverless: bool           # True + standalone Agent Server → hard-blocked
    provisions_postgres: bool
    provisions_redis: bool
    supports_secrets / logs / rollback / custom_domain: bool
    requires: list[str]        # binaries, e.g. ["docker", "vercel"]

class Provider(ABC):
    def validate(spec, env) -> list[Diagnostic]
    def preflight(ctx) -> None          # auth, plan tier, binaries, quota
    def provision(ctx) -> Resources     # idempotent
    def deploy(ctx) -> DeployResult     # → url, deployment_id, revision
    def logs / rollback / destroy(ctx)
```

Discovery: built-ins + entry points `agentctl.providers` + a zero-Python declarative escape hatch (`providers.yaml` describing shell commands), so a user can add a custom cloud without forking.

### 4.3 Deploy pipeline — deploy preserves the dev topology

```
preflight (auth, plan tier, binaries, capability matrix)
  → sync langgraph.json → build
  → provision backend deps (Postgres, Redis, secrets)
  → deploy backend → capture {api_url, assistant_id, revision}
  → ★ wiring: set AGENT_PROXY_TARGET=<api_url> + LANGSMITH_API_KEY in the frontend's
      provider secret store  (Mode B: skipped — nothing to wire)
  → deploy frontend
  → smoke test: GET <api>/ok · POST a trivial run · GET <web>/ · assert the proxy
      route returns 200 from the browser origin  ← proves end-to-end wiring
  → write .agentctl/state.json → print URLs + Studio link + rollback hint
```

The wiring step is the one everybody forgets by hand, and the reason a redeployed backend silently breaks a live frontend. Here it is automatic: if `api_url` changes, the frontend is redeployed too.

---

## 5. Commands

| Command | Behavior |
|---|---|
| `agentctl new [name]` | Rich wizard → `agent.yaml`, renders backend (+frontend +proxy), `git init`, installs deps. `--yes` + flags for CI. |
| **`agentctl dev`** | **The headline command.** §3. Flags: `--backend-only`, `--frontend-only`, `--port/--backend-port`, `--no-open`, `--docker` (uses `langgraph up` on 8123 for a production-like run), `--tunnel` (public URL for webhook/mobile testing). |
| `agentctl studio` | Opens Studio against the running local server. |
| `agentctl sync` | Regenerate `langgraph.json`, `.env.example`, proxy config, Dockerfile, CI from `agent.yaml`; report drift. |
| `agentctl add tool\|frontend\|ui-component\|provider\|eval` | Idempotent additions. `add frontend` retrofits the proxy onto a backend-only project. |
| `agentctl env set/pull/push/diff` | Per-environment env; push to provider secret stores; never committed. |
| `agentctl build` | `langgraph build` + frontend build. |
| `agentctl deploy [--env prod] [--backend-only] [--frontend-only] [--dry-run] [--resume]` | §4.3. |
| `agentctl logs [--backend\|--frontend] [-f]`, `rollback`, `destroy` | Proxy to provider; `destroy` needs the typed name. |
| `agentctl providers list/add/test` | Capability matrix; register/validate custom providers. |
| `agentctl doctor` | python/node/docker/uv versions, `langgraph-cli` version compat, ports 2024/3000, API keys valid, plan tier, Docker daemon, provider auth. |
| `agentctl eject` | Emit raw scripts/Dockerfile/Compose/workflows and drop the CLI. **Anti-lock-in is a feature.** |

Generated projects also carry plain `npm run dev` / `make dev` equivalents that call the same supervisor, so a teammate without `agentctl` installed can still run the app.

---

## 6. What gets generated

**Backend (Python, `create_agent` + `langgraph.json`)** — `src/<pkg>/agent.py`, `tools/`, `prompts/`, `context.py`; pydantic-settings config with fail-fast validation and a fully documented `.env.example`; Postgres checkpointer + store in prod / `MemorySaver` locally; `store.index` semantic search and `store.ttl` when memory is on; HITL interrupt + structured-output + guardrail-middleware examples; model retry/rate-limit handling; `pytest` unit tests plus a LangSmith eval harness and seed dataset; ruff + mypy + pre-commit; pinned `Dockerfile` and a Compose file (server + Postgres 16 + Redis 6, healthchecked); GitHub Actions for lint/test, PR preview deploy, tag→prod; README + `docs/`.

**Frontend** — `nextjs_proxy` (default): Next.js + Tailwind + `@langchain/react` `useStream`; the `app/api/agent/[...path]/route.ts` streaming proxy; thread sidebar, tool-call cards, interrupt/approval UI, time-travel, markdown/code rendering, streaming reasoning, subagent panels, error/retry/reconnect states. `vite_proxy`: lighter SPA, same wiring. `nextjs_embedded`: Mode B, all six protocol endpoints. When `generative_ui: true`, also `src/agent/ui.tsx` + the `ui` key in `langgraph.json` + `LoadExternalComponent` rendering — the agent ships its own React components.

---

## 7. Edge cases (acceptance criteria for `doctor`/`preflight`)

**Unified runtime — the new, highest-risk surface**
- Port 2024 or 3000 occupied → detect, offer the next free port, and thread it through the proxy target automatically.
- Backend crashes at startup (import error, bad key) → the frontend must **not** boot into a broken app; surface the backend traceback as the primary error and exit non-zero.
- Backend healthy but slow to start → bounded exponential backoff on `/ok`, clear "still waiting… (12s)" progress, hard timeout with the actual tail of backend logs.
- Ctrl-C / SIGTERM → kill the whole process group; no orphaned `langgraph dev` holding 2024 hostage on the next run. Detect and offer to reclaim a stale orphan.
- Hot reload: backend restarts on Python change (langgraph handles it); the proxy must survive the gap and retry rather than 502 an in-flight stream.
- SSE through the proxy: disable response buffering, `changeOrigin`, **600s timeouts** on both sides, forward `text/event-stream` untouched, no compression middleware.
- Windows/WSL: no POSIX process groups — use `CREATE_NEW_PROCESS_GROUP` + job objects; test explicitly.
- Interleaved logs must not corrupt Rich's live display; log-mux takes a lock.
- `--docker` mode: `langgraph up` is on **8123**, not 2024 — the proxy target must follow the mode, not a constant.

**Plan / entitlement**
- No LangSmith Plus → detect **before** building; explain and offer Mode B on Vercel or `compose_ssh`.
- Self-hosted control plane / Hybrid without an Enterprise license → refuse early, point at standalone.
- Pre-Oct-2026 pricing orgs need `--deployment-type dev|prod`; probe the org and choose the right flag.

**Infra correctness**
- Standalone Agent Server on a serverless/scale-to-zero provider → hard block (documented task loss).
- Shared Postgres/Redis → force distinct database name and Redis db index; refuse duplicates.
- `LANGSMITH_ENDPOINT` trailing slash → strip and warn (causes auth errors).
- Air-gapped: no egress to `beacon.langchain.com` → license check fails; flag in `doctor`, point at image mirroring.
- Apple Silicon needs Buildx for `linux/amd64`; absent → fall back to remote build. No Docker at all → remote build; `dev` still works.

**Project state**
- Hand-edited `langgraph.json` → merge, report drift, never silently clobber.
- Monorepo / nested project → walk up to `agent.yaml`; honor `dependencies: ["./subdir"]`.
- Python version mismatch between venv and `langgraph.json` → warn.
- `uv` dependency-graph failure → name `pip_installer: "pip"` in the error text.
- Deployment name collision → detect existing deployment; always ask update-in-place vs create-new.

**Deploy lifecycle**
- Partial failure → state file records what exists; `--resume` continues.
- Backend URL change → frontend env re-injected and redeployed automatically.
- Rollback offered for both halves together, since they are wired.
- Concurrent deploys → advisory lock with stale-lock override.
- Ctrl-C mid-deploy → cleanup handlers; no orphaned cloud resources.

**Secrets & safety**
- `LANGSMITH_API_KEY` is injected **server-side in the proxy route only** — never `NEXT_PUBLIC_*`. A lint rule in the template CI fails the build if a secret is prefixed for the browser.
- Keyring first, `.env.local` fallback; `.gitignore` covers `.env*`, `.agentctl/`, `.langgraph_api/`.
- `destroy` requires typing the deployment name.
- **Unrelated but urgent:** `/home/revnix/Desktop/research/github token ghp ….txt` holds a GitHub token in plaintext one directory above this repo. Revoke it.

---

## 8. Phases

| Phase | Scope | Done when |
|---|---|---|
| **0. Skeleton** | Typer app, `AgentSpec`, manifest, renderer, errors, provider ABC, `doctor`. | `agentctl doctor` prints a full environment table. |
| **1. ★ Unified runtime** | `supervisor.py`, `health.py`, proxy templates, `minimal` + `react_agent` Python backends, `nextjs_proxy` frontend, `agentctl new` + `agentctl dev`. | `agentctl new x && cd x && agentctl dev` → one URL, chat with the agent, edit `agent.py`, see hot reload, Ctrl-C leaves nothing running. |
| **2. Deploy v1** | `langsmith_cloud` + `vercel`, wiring, smoke test, state, `logs`/`rollback`/`destroy`, CI. | One `agentctl deploy` → both halves live and wired; a backend-only redeploy still leaves the UI working. |
| **3. No-plan path** | Mode B `nextjs_embedded` + `compose_ssh` standalone provider. | A user with no LangSmith plan deploys end-to-end. |
| **4. Breadth** | `rag`/`deep_agent`/`multi_agent`, generative UI (`ui` key), `vite_proxy`, `flyio`/`render`, `add *`, eval harness. | |
| **5. Any cloud** | `ecs`/`cloudrun`/`k8s_helm` as reviewable Terraform/Helm emitters, plugin spec docs, `eject`. | A platform engineer adds an internal cloud without forking. |

Phase 1 is the product. If `agentctl dev` isn't magic, nothing after it matters.

---

## 9. Verification

- **Unit:** spec validation; `langgraph.json` merge/drift; wiring for both modes; capability matrix (serverless × standalone → blocked); supervisor lifecycle with fake processes (health gate, crash propagation, teardown, orphan reaping); proxy header injection and secret-leak lint.
- **Golden-file:** snapshot every rendered template; generated projects must pass `ruff`/`eslint` and `mypy`/`tsc`.
- **★ Runtime integration (the critical suite):** scaffold into a tmpdir, run `agentctl dev` against a **stub model server**, then assert — `:2024/ok` healthy; `GET :3000/` 200; `POST :3000/api/agent/threads` proxies through; a run **streams SSE through the proxy** with tokens arriving incrementally (not buffered — assert timing, not just the final body); editing `agent.py` triggers reload and the next request succeeds; SIGINT leaves **zero** surviving PIDs and both ports free. Matrix: `{python, node} × {nextjs_proxy, vite_proxy, none}` + Mode B, on Linux and macOS, plus a Windows smoke run.
- **Docker:** `agentctl dev --docker` → `langgraph up` on 8123, proxy retargets, thread state survives a container restart (proves the checkpointer).
- **E2E (gated, real creds, nightly):** deploy to LangSmith Cloud + Vercel, smoke both URLs, confirm the browser never sees the API key (scan the client bundle), `rollback`, `destroy`, assert no orphans.
- **`--dry-run` contract test:** every provider produces a full action plan with no network access.
- **Manual:** the four §3/§10 journeys on a clean machine — including "no LangSmith plan, no Docker", which must never dead-end.

---

## 10. Personas served

1. **Indie** — no plan, no Docker: `new` → `dev` → chat; deploys Mode B to Vercel free.
2. **Startup** — has Plus: Mode A → LangSmith Cloud + Vercel, PR previews, secrets in the provider.
3. **Enterprise** — data residency: standalone Agent Server on own K8s/ECS, own Postgres/Redis, self-hosted LangSmith endpoint, **reviewable IaC** rather than a black-box deploy.
4. **Platform engineer** — adds an internal cloud via the plugin spec, no fork.

## 11. Risks

- `langgraph deploy` is **beta**; flags will move. Pin `langgraph-cli`, version-assert in `doctor`, keep the wrapper in one file.
- The supervisor is the classic source of cross-platform pain (signals, orphans, PTY colors). Mitigation: it is Phase 1, tested hardest, and small enough to own outright.
- LangChain may ship this. Our moat: Python-backend unified dev, multi-cloud, deploy-time wiring, and `eject`.
- Template rot (`create-agent-chat-app` has been stale since Apr 2025). Mitigation: weekly CI scaffolds every template against latest deps and files an issue on failure.

## 12. Open questions (Phase 1, non-blocking)

CLI name availability on PyPI/npm; license (generated code must be unencumbered — state it); telemetry off by default, opt-in only.

## 13. Files this plan becomes

`agent_cli/plan/` → `PLAN.md` (this file), `01-research-langchain.md` (§1), `02-unified-runtime.md` (§3 — the spec for `dev`), `03-architecture.md` (§4), `04-commands.md` (§5), `05-templates.md` (§6), `06-providers.md` (§4.2), `07-edge-cases.md` (§7), `08-roadmap.md` (§8–§11).

**Sources:** [Build overview](https://docs.langchain.com/build-overview) · [LangGraph CLI](https://docs.langchain.com/langsmith/cli) · [Local dev & testing](https://docs.langchain.com/langsmith/local-dev-testing) · [Deployment](https://docs.langchain.com/langsmith/deployment) · [Deploy to Cloud](https://docs.langchain.com/langsmith/deploy-to-cloud-overview) · [Self-hosted](https://docs.langchain.com/langsmith/deploy-to-self-hosted-overview) · [Standalone server](https://docs.langchain.com/langsmith/deploy-standalone-server) · [Full-stack web apps](https://docs.langchain.com/langsmith/deploy-frameworks-and-platforms) · [Next.js (embedded)](https://docs.langchain.com/langsmith/deploy-nextjs) · [Vite + LangSmith (proxy)](https://docs.langchain.com/langsmith/deploy-vite-langsmith) · [Generative UI](https://docs.langchain.com/langsmith/generative-ui-react) · [Frontend SDK](https://docs.langchain.com/oss/python/langchain/frontend/overview) · [deployment-cookbook](https://github.com/langchain-ai/deployment-cookbook) · [agent-protocol](https://github.com/langchain-ai/agent-protocol) · [agent-chat-ui](https://github.com/langchain-ai/agent-chat-ui)
