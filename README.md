# agentctl

Scaffold, run, and deploy production LangChain agents — **frontend and agent in one command**.

```bash
agentctl new my-agent      # backend + chat UI, wired together
cd my-agent
agentctl dev               # one command, one URL, already talking to each other
```

`agentctl dev` starts the LangGraph Agent Server *and* your Next.js app, waits for the
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
  local agent; `agentctl deploy` sets it to the deployed Agent Server URL. The frontend
  source does not change.

## Commands

| Command | What it does |
|---|---|
| `agentctl new [name]` | Scaffold backend (+ frontend), `agent.yaml`, `langgraph.json`, git init, install deps. |
| `agentctl dev` | Run agent + frontend as one app. `--backend-only`, `--frontend-only`, `--port`, `--backend-port`, `--docker`, `--tunnel`, `--no-open`, `--strict-port`. |
| `agentctl sync` | Regenerate `langgraph.json` from `agent.yaml`, preserving hand-written keys. `--check` for CI. |
| `agentctl doctor` | Verify toolchain, ports, keys, and config before something fails mid-command. |

## Configuration

`agent.yaml` is the single source of truth; `langgraph.json` is generated from it.
`sync` merges rather than overwrites, so hand-added keys (`auth`, `checkpointer`,
`dockerfile_lines`, …) survive, and drift in owned keys is reported instead of silently
clobbered.

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
export AGENTCTL_E2E_PROJECT=/path/to/scaffolded/project
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
