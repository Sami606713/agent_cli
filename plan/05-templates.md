# Generated project templates

Part of [`agentctl` — a Next.js-style CLI for building, running, and deploying LangChain agents](./PLAN.md).

## 6. What gets generated


**Backend (Python, `create_agent` + `langgraph.json`)** — `src/<pkg>/agent.py`, `tools/`, `prompts/`, `context.py`; pydantic-settings config with fail-fast validation and a fully documented `.env.example`; Postgres checkpointer + store in prod / `MemorySaver` locally; `store.index` semantic search and `store.ttl` when memory is on; HITL interrupt + structured-output + guardrail-middleware examples; model retry/rate-limit handling; `pytest` unit tests plus a LangSmith eval harness and seed dataset; ruff + mypy + pre-commit; pinned `Dockerfile` and a Compose file (server + Postgres 16 + Redis 6, healthchecked); GitHub Actions for lint/test, PR preview deploy, tag→prod; README + `docs/`.

**Frontend** — `nextjs_proxy` (default): Next.js + Tailwind + `@langchain/react` `useStream`; the `app/api/agent/[...path]/route.ts` streaming proxy; thread sidebar, tool-call cards, interrupt/approval UI, time-travel, markdown/code rendering, streaming reasoning, subagent panels, error/retry/reconnect states. `vite_proxy`: lighter SPA, same wiring. `nextjs_embedded`: Mode B, all six protocol endpoints. When `generative_ui: true`, also `src/agent/ui.tsx` + the `ui` key in `langgraph.json` + `LoadExternalComponent` rendering — the agent ships its own React components.

---
