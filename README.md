# langctl

Scaffold, run, and deploy production LangChain agents — **frontend and agent in one command**.

```bash
uv tool install langctl
langctl new my-agent
cd my-agent          # add your API key to .env
langctl dev
```

`langctl dev` starts the LangGraph Agent Server *and* your Next.js app, waits for the
agent's health endpoint before booting the UI, proxies the agent behind the frontend's
own origin, and tears both down cleanly on Ctrl-C. Like `next dev`, but the backend is
an agent.

Long-term memory is on by default and needs nothing running.

## Install

```bash
uv tool install langctl     # recommended — isolated environment, on PATH
pipx install langctl        # same idea
pip install langctl         # works, but shares your environment
```

Upgrade with `uv tool upgrade langctl`. If that reports no change when you expect one,
it is uv's cached index: `uv tool install --force --reinstall langctl`.

## Commands

| Command | What it does |
|---|---|
| [`langctl new`](#langctl-new) | Scaffold a project |
| [`langctl dev`](#langctl-dev) | Run agent + frontend as one app |
| [`langctl add`](#langctl-add) | Add a feature to an existing project |
| [`langctl share`](#deploying) | Expose your local app on a public URL |
| [`langctl sync`](#langctl-sync) | Regenerate derived files from `agent.yaml` |
| [`langctl doctor`](#langctl-doctor) | Check the environment before it bites |

### `langctl new`

```bash
langctl new my-agent                    # interactive
langctl new my-agent --yes              # all defaults
langctl new api-bot --yes --no-frontend
langctl new my-agent --yes --memory-backend postgres --semantic-search
```

`--runtime` · `--model-provider` · `--model` · `--frontend/--no-frontend` · `--ui` ·
`--memory/--no-memory` · `--memory-backend` · `--semantic-search` · `--embeddings` ·
`--embedding-model` · `--yes` · `--no-install` · `--no-git`

### `langctl dev`

`--backend-only` · `--frontend-only` · `--port` · `--backend-port` · `--no-open` ·
`--docker` (runs `langgraph up`, port 8123) · `--tunnel` · `--strict-port`

### `langctl add`

```bash
langctl add memory --backend postgres
langctl add frontend --ui minimal
langctl add tool "lookup order"
```

`add` regenerates the files langctl produced and **skips the ones you edited**, listing
each. A file that still matches what the template last wrote is safe to update; anything
else is yours. See [Adding to an existing project](#adding-to-an-existing-project).

### `langctl sync`

Regenerates `langgraph.json` **and** `pyproject.toml` dependencies from `agent.yaml`.
`--check` exits non-zero on drift, for CI. `--force` overwrites owned keys you edited.

### `langctl doctor`

Toolchain, ports, API keys, Postgres reachability, and `langgraph validate`. Prints a fix
for each failure.

## Why the proxy

The browser only ever talks to `/api/agent/...` on the frontend's origin:

```
localhost:3000                      127.0.0.1:2024
┌────────────────────────┐          ┌──────────────────┐
│ Next.js                │          │ langgraph dev    │
│  /            chat UI  │          │  /threads /runs  │
│  /api/agent/* ─proxy───┼─────────▶│  /assistants /ok │
└────────────────────────┘          └──────────────────┘
        same origin ⇒ no CORS, ever
```

Three things fall out of this:

- **CORS never applies.** There is no cross-origin request to preflight.
- **The API key stays on the server.** The proxy runs in a route handler and attaches
  `x-api-key` there. Nothing secret reaches the browser.
- **Dev, tunnel, and production differ by one variable.** `AGENT_PROXY_TARGET` points at
  localhost, then a container, then a deployed server. The frontend source never changes.

## Chat UI

`web/` is [LangChain's agent-chat-ui](https://github.com/langchain-ai/agent-chat-ui),
vendored **unmodified** at a pinned commit (MIT). You get the real thing: thread
history, an agent inbox for human-in-the-loop approvals, artifacts, markdown with
syntax highlighting, file and image attachments, and generative UI.

**The setup screen never appears.** Upstream shows a form asking for a deployment URL
and assistant ID when either is missing:

```tsx
if (!finalApiUrl || !finalAssistantId) {  // ← the setup screen
```

langctl pre-fills both, so that branch is never reached. The screen is *bypassed, not
deleted* — leaving the source byte-identical means re-syncing with upstream is a plain
diff rather than a merge. `web/VENDORED.md` records the exact commit.

## Models

25 providers, plus anything `init_chat_model` supports:

```bash
langctl new my-agent --model-provider openai
langctl new my-agent --model-provider openrouter --model z-ai/glm-5.2
langctl new my-agent --model-provider ollama              # local, no API key
```

**A custom endpoint** — LM Studio, vLLM, a LiteLLM proxy, any OpenAI-compatible
gateway:

```bash
langctl new my-agent --model-provider openai --model my-model \
  --model-base-url http://localhost:1234/v1
```

**A provider langctl does not know** — just say what supplies it:

```bash
langctl new my-agent --model-provider mycloud --model m1 \
  --model-package langchain-mycloud
```

The provider list is open rather than fixed, so a new LangChain integration is
usable the day it ships instead of waiting on a langctl release. Choosing a
provider without naming a model picks that provider's default, and providers
that need no key (Ollama, ambient cloud credentials) do not demand one.

Everything is also editable in `agent.yaml`, including per-model options:

```yaml
model:
  provider: openai
  name: my-model
  base_url: http://localhost:1234/v1
  api_key_env_override: MY_GATEWAY_KEY
  options: {temperature: 0.2}
```

When `base_url` or `options` are set the model is constructed rather than passed
as a `provider:model` string, because a string carries neither.

## Memory

Long-term memory is on by default and needs nothing running. Verified against a real
restart: without an explicit store, `langgraph dev` keeps memories in process and loses
them all on exit.

| backend | when | setup |
|---|---|---|
| `sqlite` *(default)* | one machine, one process | none |
| `postgres` | more than one replica, or shared state | set `POSTGRES_URI` |

Semantic search is **off** by default — it needs an embeddings vendor and costs per item
stored. Three ways to produce vectors:

| `--embeddings` | Trade-off |
|---|---|
| `local` | sentence-transformers, no API key, no per-item cost, but pulls torch (GB) |
| `provider` | hosted API, fastest to set up, needs a key |
| `custom` | your own function |

Two memories, opposite defaults, for a reason: overriding the **store** is a strict gain
(it is otherwise lost on restart), while overriding the **checkpointer** loses
`adelete_for_runs`, so threads stay server-managed unless you ask.

## Middleware

Every new project ships with cost and reliability guards on — an agent with no
call limit can loop until it exhausts your budget:

```python
MIDDLEWARE = [
    # limits
    ModelCallLimitMiddleware(run_limit=20),
    ToolCallLimitMiddleware(run_limit=30),
    # reliability
    ToolRetryMiddleware(max_retries=2),
]
```

```bash
langctl add middleware --list              # registry, and what is on
langctl add middleware summarization
langctl add middleware --custom rate_limit # your own class
```

**Order is semantic, not alphabetical.** langctl emits a fixed sequence —
guardrails → context → limits → reliability → human-in-the-loop → capability →
custom — because PII redaction placed after summarization means raw content
already reached the summarizing model. Custom middleware always runs last, so it
sees a fully prepared request.

Settings live in `agent.yaml` and are regenerated into `middleware/__init__.py`
by `langctl sync`.

Custom middleware gets **one module per class**, mirroring `tools/`:

```
middleware/
├── __init__.py          MIDDLEWARE list — built-ins, then yours
└── custom/
    ├── __init__.py      registry, regenerated by `langctl sync`
    ├── rate_limit.py
    └── audit_log.py
```

Each is scaffolded as a bare class — **no hooks**. Which of the six hooks a
middleware needs is the design decision, so the docstring lists them all with
real signatures and you add only what you use.

## Adding to an existing project

Upgrading langctl does not touch projects you already created — templates are copied at
creation, not linked. Use `langctl add`.

**Projects from 0.1.x/0.2.x** used single modules (`tools.py`, `prompts.py`) where 0.3+
uses packages (`tools/`, `prompts/`). After `add`, both exist and Python imports the
package, so the old file is silently ignored. Move anything you wrote into the package
and delete the module — editing it will have no effect.

## Sharing and deploying

### `langctl share` — shipped

Puts your locally running app on a public URL. One tunnel covers the whole
thing, because the agent already sits behind the frontend's proxy — the agent
port is never exposed and no API key leaves your machine.

```bash
langctl share                      # cloudflared if present, else ngrok
langctl share --provider ngrok
langctl share --backend-only       # expose the agent API instead (warns first)
```

`cloudflared` is preferred because its quick tunnels need no account. Nothing is
hosted: close the laptop and the URL dies. Good for demos, client previews,
webhook testing, and trying the app on a phone.

> The URL is public and unauthenticated. Anyone with it can talk to your agent
> and spend your API credits.

### `langctl deploy` — not built yet

The plan is both halves on **one** platform, with the frontend as the only public
surface and the agent internal behind the proxy:

```
┌─ one host ────────────────────────────────────┐
│  web      Next.js        ← public             │
│   └ proxy → agent                             │
│  agent    Agent Server     internal only      │
│  postgres · redis          internal           │
└───────────────────────────────────────────────┘
```

Until then, deploying means `langgraph deploy` for the agent and setting
`AGENT_PROXY_TARGET` + `LANGSMITH_API_KEY` on your frontend host.

Two constraints that shape the design, worth knowing now:

- **The Agent Server is licensed.** Self-hosting it in production needs a LangSmith
  Enterprise licence key. The licence-free paths are `langctl share`, the JS embedded
  mode (agent inside Next.js route handlers, no Agent Server), and LangSmith Cloud.
- **A SQLite store on an ephemeral container filesystem loses every memory on restart**,
  so `deploy` will have to switch long-term memory to Postgres or refuse.

## Configuration

`agent.yaml` is the single source of truth; `langgraph.json` and the dependency list are
generated from it. `sync` merges rather than overwrites, so hand-added keys and packages
survive, and drift is reported instead of silently clobbered.

## Development

```bash
uv venv && . .venv/bin/activate
uv pip install -e ".[dev]"
pytest
ruff check src tests
```

The suite spawns **real child processes** rather than mocking `Popen`: the failures that
matter — orphaned grandchildren, ports left held, signals that never arrive — do not
exist at the mock level.

Heavier checks need a scaffolded project:

```bash
export LANGCTL_E2E_PROJECT=/path/to/project
tests/e2e/dev_runtime.sh          # health gate, proxy, thread creation, teardown
tests/e2e/sse_streaming.sh        # asserts SSE arrives incrementally, not buffered
tests/e2e/memory_persistence.sh   # writes a memory, kills the process group, restarts
tests/e2e/share_tunnel.sh         # live tunnel: public URL, proxy, clean teardown
```

`sse_streaming.sh` measures arrival *times*: a buffering proxy passes every status-code
assertion and still ruins the product. `memory_persistence.sh` kills by process group and
requires the port to be released — an earlier version killed only the parent, left the
uvicorn child serving, and reported a fake pass.

## License

Apache-2.0. Generated projects carry no license obligation to this tool.
