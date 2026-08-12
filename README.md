# langctl

Scaffold, run, and deploy production LangChain agents — **frontend and agent in one command**.

```bash
langctl new my-agent      # backend + chat UI, wired together
cd my-agent
langctl dev               # one command, one URL, already talking to each other
```

`langctl dev` starts the LangGraph Agent Server *and* your Next.js app, waits for the
agent's health endpoint before booting the UI, proxies the agent behind the frontend's
own origin, and tears both down cleanly on Ctrl-C. Like `next dev`, but the backend is
an agent.

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
- **Dev and production differ by one variable.** `AGENT_PROXY_TARGET` unset means the
  local agent; `langctl deploy` sets it to the deployed Agent Server URL. The frontend
  source does not change.

## Chat UI

`langctl new` scaffolds one of three UIs. All share the same proxy, streaming
contract, and `langctl dev` behaviour — only `web/app/components/` differs.

| `--ui` | What you get | CSS |
|---|---|---|
| `assistant-ui` *(default)* | assistant-ui runtime (threads, branching, composer) via npm; we ship a ~130-line converter you own | Tailwind utilities only |
| `minimal` | one hand-written `Chat.tsx`, zero UI dependencies | Tailwind utilities only |
| `ai-elements` *(experimental)* | shadcn-registry components copied into `web/components/` | Tailwind `@theme` tokens |

No template contains hand-written CSS. `globals.css` is `@import "tailwindcss";`
and nothing else, except `ai-elements`, which adds a `@theme` token block because
its components reference semantic classes. A test enforces this.

> **`ai-elements` is experimental and currently fails `npm run build`.** Its
> generated components pull `streamdown`, which resolves two incompatible copies
> of `shiki`; npm `overrides` do not dedupe them. Our own files typecheck clean —
> the failure is entirely in the vendored components. It is excluded from the
> interactive wizard and reachable only via an explicit `--ui ai-elements`.

## Memory

Long-term memory is on by default and needs nothing running — it uses a local
SQLite file. Verified against a real restart: without an explicit store,
`langgraph dev` keeps memories in process and loses them all on exit.

| backend | when | setup |
|---|---|---|
| `sqlite` *(default)* | one machine, one process | none |
| `postgres` | more than one replica, or shared state | set `POSTGRES_URI` |

```bash
langctl new my-agent                              # sqlite
langctl new my-agent --memory-backend postgres    # then set POSTGRES_URI in .env
```

Switching later: edit `agent.yaml`, then `langctl sync && uv sync`. `sync`
updates `pyproject.toml` too, because a backend without its driver is a startup
failure `langgraph validate` reports as valid. `langctl doctor` checks that
Postgres is actually reachable.

Semantic search is off by default (it needs an embeddings vendor and costs per
item). Enable it with `--semantic-search --embeddings local|provider|custom`.

## Adding to an existing project

```bash
langctl add memory                  # or --backend postgres, --semantic-search
langctl add frontend --ui minimal
langctl add tool "lookup order"     # scaffolds and registers it
```

`add` regenerates the files langctl produced and **skips the ones you edited**,
reporting each. A file that still matches what the template last wrote is safe
to update; anything else is yours.

## Commands

| Command | What it does |
|---|---|
| `langctl new [name]` | Scaffold backend (+ frontend), `agent.yaml`, `langgraph.json`, git init, install deps. |
| `langctl dev` | Run agent + frontend as one app. `--backend-only`, `--frontend-only`, `--port`, `--backend-port`, `--docker`, `--tunnel`, `--no-open`, `--strict-port`. |
| `langctl sync` | Regenerate `langgraph.json` from `agent.yaml`, preserving hand-written keys. `--check` for CI. |
| `langctl doctor` | Verify toolchain, ports, keys, and config before something fails mid-command. |

## Configuration

`agent.yaml` is the single source of truth; `langgraph.json` is generated from it.
`sync` merges rather than overwrites, so hand-added keys (`auth`, `checkpointer`,
`dockerfile_lines`, …) survive, and drift in owned keys is reported instead of silently
clobbered.

## Install

```bash
uv tool install -e .        # editable: source edits take effect immediately
langctl --version
```

Install **editable**. A non-editable `uv tool install .` is cached by version, so
after changing the source `uv tool install --force .` reports `Audited …` and keeps
running the old code — the version string has to change for the cache to miss. If
you already hit that: `uv tool install --force --reinstall -e .`

When debugging which copy is running, call it by absolute path
(`~/.local/bin/langctl`): an activated project venv shadows the global binary.

## Development

```bash
uv venv && . .venv/bin/activate
uv pip install -e ".[dev]"
pytest                    # unit + process-level integration
ruff check src tests
```

The suite spawns **real child processes** rather than mocking `Popen`: the failures
that matter here — orphaned grandchildren, ports left held, signals that never arrive —
do not exist at the mock level. See `tests/test_supervisor.py` and `tests/test_signals.py`.

Two heavier checks need a scaffolded project with dependencies installed:

```bash
export LANGCTL_E2E_PROJECT=/path/to/scaffolded/project
tests/e2e/dev_runtime.sh     # health gate, proxy, thread creation, clean teardown
tests/e2e/sse_streaming.sh   # asserts SSE arrives incrementally, not buffered
```

`sse_streaming.sh` measures *arrival times*, not just the final body — a buffering proxy
passes every status-code assertion and still ruins the product.

## Status

Phase 1 (scaffold + unified dev runtime) works end to end. Deploy providers
(`langsmith_cloud`, `vercel`) are next — see [plan/](plan/).

## License

Apache-2.0. Generated projects carry no license obligation to this tool.
