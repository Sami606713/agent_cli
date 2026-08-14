<div align="center">

# langctl

**Scaffold, run, and deploy production LangChain agents — frontend and agent in one command.**

[![PyPI](https://img.shields.io/pypi/v/langctl.svg)](https://pypi.org/project/langctl/)
[![Python](https://img.shields.io/pypi/pyversions/langctl.svg)](https://pypi.org/project/langctl/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![CI](https://github.com/Sami606713/agent_cli/actions/workflows/ci.yml/badge.svg)](https://github.com/Sami606713/agent_cli/actions)

</div>

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

## Requirements

| | Version | Needed for | If missing |
|---|---|---|---|
| **Python** | 3.11 – 3.13 | langctl itself, and the agent | Nothing works. 3.14 is not supported: the Agent Server targets 3.11–3.13. |
| **uv** | any recent | Installing the project's Python dependencies | `langctl new` skips the install and warns; run `uv sync --extra dev` yourself later. |
| **Node.js** | 20 or newer | The chat UI | The frontend is not installed; `--no-frontend` projects do not need it. |
| **npm** or **pnpm** | ships with Node | The chat UI | Same as above. |
| **Docker** | with the compose plugin | `langctl deploy`, and `langctl dev --docker` | `dev` and `share` still work; `deploy` stops with a clear error. |
| **Git** | any | `langctl new` initialises a repo | Scaffolding still succeeds; pass `--no-git` to skip it. |

Two more are installed **into your project** by `langctl new`, not onto your machine:
`langgraph-cli`, which runs the Agent Server, and your model provider's LangChain
package. If you scaffold with `--no-install`, run `uv sync --extra dev` before
`langctl dev`.

For **deploying to a remote host** you also need `ssh` and `rsync` locally, and Docker
with the compose plugin on the target machine. Nothing else — no registry, no
Kubernetes, no cloud account.

Everything is checked for you:

```bash
langctl doctor        # versions, ports, API keys, Postgres, langgraph validate
```

**Platforms.** Linux, macOS and Windows are all supported. On Windows, use PowerShell or
Windows Terminal rather than the legacy console.

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
| [`langctl deploy`](#langctl-deploy) | Ship both halves to one host |
| [`langctl add`](#langctl-add) | Add a feature to an existing project |
| [`langctl share`](#sharing-and-deploying) | Expose your local app on a public URL |
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
`--docker` (runs `langgraph up`, port 8123) · `--tunnel` · `--auto-port/--strict-port`

### `langctl add`

```bash
langctl add memory --backend postgres
langctl add frontend
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

The browser only ever talks to `/api/...` on the frontend's origin:

```
localhost:3000                      127.0.0.1:2024
┌────────────────────────┐          ┌──────────────────┐
│ Next.js                │          │ langgraph dev    │
│  /            chat UI  │          │  /threads /runs  │
│  /api/*       ─proxy───┼─────────▶│  /assistants /ok │
└────────────────────────┘          └──────────────────┘
        same origin ⇒ no CORS, ever
```

Three things fall out of this:

- **CORS never applies.** There is no cross-origin request to preflight.
- **The API key stays on the server.** The proxy runs in a route handler and attaches
  `x-api-key` there. Nothing secret reaches the browser.
- **Dev, tunnel, and production differ by one variable.** `LANGGRAPH_API_URL` points at
  localhost, then a container on the deploy network. The frontend source never changes.

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
langctl new my-agent --model-provider ollama --model qwen3   # name is required
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
usable the day it ships instead of waiting on a langctl release. Providers that
need no key (Ollama, ambient cloud credentials) do not demand one.

**Some providers have no safe default model.** A hosted provider does — everyone
with an OpenAI key can reach `gpt-5.5`. Ollama, LiteLLM, HuggingFace, a custom
`base_url`, and any provider langctl does not know all serve whatever *your*
machine or gateway has, so no name is invented for them. `MODEL_NAME` comes from
`.env`, and the generated `config.py` fails at startup with a clear message
rather than on the first message with a 404 from a server it never saw.

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

### `langctl deploy`
<a id="langctl-deploy"></a>

Both halves go to **one host, in one operation**, behind one URL:

```bash
langctl deploy                                    # this machine
langctl deploy --host user@1.2.3.4                # a server you own
langctl deploy --host user@1.2.3.4 --domain x.io  # the same, with HTTPS
```

```
┌─ one host ────────────────────────────────────┐
│  web       Next.js          ← the only door   │
│   └ /api → agent                              │
│  agent     Agent Server       internal only   │
│  postgres · redis             internal        │
└───────────────────────────────────────────────┘
```

**The frontend is never told an address.** It reaches the agent at `http://agent:8000`
— a service name on the private network. There is nothing to paste into a config and
nothing to update later, so redeploying the agent cannot break the UI. This is the
failure the command exists to prevent; deploying the two halves separately means
re-wiring them every time.

Only the frontend publishes a port. The Agent Server has no route in from outside, so
the LangSmith key stays in the server-side proxy exactly as it does in development.

**First deploy**, in three steps:

```bash
langctl deploy --host user@1.2.3.4        # 1. stops, writes .env.deploy
#                                            2. fill in the three secrets
scp .env.deploy user@1.2.3.4:~/my-agent/  # 3. place them on the host, once
langctl deploy --host user@1.2.3.4        #    run again — done
```

Secrets are checked **before** anything is built, so a missing key costs you a second
rather than ten minutes into an image build. `.env.deploy` is never uploaded by a
deploy and never baked into an image.

| | |
|---|---|
| `--logs [--service agent]` | Follow logs from the stack |
| `--down` | Stop it. The database survives |
| `--down --volumes` | Stop and **delete all data** — prompts first |
| `--build-only` | Build images without starting |
| `--force` | Overwrite stack files you have edited |

Redeploy with the same command: rsync sends only what changed and Docker reuses layers.

With `--domain`, Caddy joins the stack and obtains and renews a Let's Encrypt
certificate on its own. It deliberately does not compress `text/event-stream` —
buffering the token stream to compress it is what makes an agent appear to hang and
then answer everything at once.

The startup order is enforced by health checks: Postgres and Redis become healthy →
the agent starts and answers `/ok` → only then does the UI start. A deploy that fails
exits non-zero instead of handing back a URL that does not load.

> **The Agent Server is licensed.** Self-hosting it in production needs a
> `LANGGRAPH_CLOUD_LICENSE_KEY` from a LangSmith Enterprise plan. It starts without one
> using your LangSmith API key, and `deploy` warns rather than blocks — but that is
> outside LangChain's terms for production use. The licence-free paths are
> `langctl share` and LangSmith Cloud.

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
