# `langctl` — plan

A CLI that scaffolds a production LangChain/LangGraph agent, runs frontend + agent together with
**one command** (like `next dev`), and deploys both — wired to each other — with one more.

Start with **[PLAN.md](./PLAN.md)** (the whole thing), or jump to a part:

| File | What's in it |
|---|---|
| [PLAN.md](./PLAN.md) | The complete plan. |
| [01-research-langchain.md](./01-research-langchain.md) | What the LangChain platform actually gives us, verified against the docs — and the `js-langsmith` cookbook pattern this design generalizes. |
| [02-unified-runtime.md](./02-unified-runtime.md) | **The core.** Mode A (proxy) and Mode B (embedded); the spec `langctl dev` implements. |
| [03-architecture.md](./03-architecture.md) | Repo layout, `AgentSpec`/`agent.yaml`, provider interface, deploy pipeline. |
| [04-commands.md](./04-commands.md) | Every command and flag. |
| [05-templates.md](./05-templates.md) | What a generated project contains, backend and frontend. |
| [06-providers.md](./06-providers.md) | Provider interface, deploy pipeline, plugin spec. |
| [07-edge-cases.md](./07-edge-cases.md) | Edge cases — the acceptance criteria for `doctor`/`preflight`. |
| [08-roadmap.md](./08-roadmap.md) | Phases, verification strategy, personas, risks, open questions. |
| [09-store-and-retention.md](./09-store-and-retention.md) | Store, semantic search, and data retention — making `langgraph.json` production-correct by default. |

## Decisions locked

- CLI in **Python** (Typer + Rich), shipped via `uv tool install` / `pipx`.
- v1 deploy targets: **LangSmith Cloud** (backend) + **Vercel** (frontend).
- Authoring model: **`langgraph.json` + `create_agent`** — the one contract every deploy path keys off.
- **Local-only OSS CLI**, no hosted control plane; custom clouds via the plugin spec.

## Build order

Phase 1 (`langctl new` + `langctl dev`, the unified runtime) is the product.
If `dev` isn't magic, nothing after it matters.
