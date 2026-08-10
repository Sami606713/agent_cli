# Roadmap, verification, personas, risks

Part of [`langctl` — a Next.js-style CLI for building, running, and deploying LangChain agents](./PLAN.md).

## 8. Phases


| Phase | Scope | Done when |
|---|---|---|
| **0. Skeleton** | Typer app, `AgentSpec`, manifest, renderer, errors, provider ABC, `doctor`. | `langctl doctor` prints a full environment table. |
| **1. ★ Unified runtime** | `supervisor.py`, `health.py`, proxy templates, `minimal` + `react_agent` Python backends, `nextjs_proxy` frontend, `langctl new` + `langctl dev`. | `langctl new x && cd x && langctl dev` → one URL, chat with the agent, edit `agent.py`, see hot reload, Ctrl-C leaves nothing running. |
| **2. Deploy v1** | `langsmith_cloud` + `vercel`, wiring, smoke test, state, `logs`/`rollback`/`destroy`, CI. | One `langctl deploy` → both halves live and wired; a backend-only redeploy still leaves the UI working. |
| **3. No-plan path** | Mode B `nextjs_embedded` + `compose_ssh` standalone provider. | A user with no LangSmith plan deploys end-to-end. |
| **4. Breadth** | `rag`/`deep_agent`/`multi_agent`, generative UI (`ui` key), `vite_proxy`, `flyio`/`render`, `add *`, eval harness. | |
| **5. Any cloud** | `ecs`/`cloudrun`/`k8s_helm` as reviewable Terraform/Helm emitters, plugin spec docs, `eject`. | A platform engineer adds an internal cloud without forking. |

Phase 1 is the product. If `langctl dev` isn't magic, nothing after it matters.

---

## 9. Verification


- **Unit:** spec validation; `langgraph.json` merge/drift; wiring for both modes; capability matrix (serverless × standalone → blocked); supervisor lifecycle with fake processes (health gate, crash propagation, teardown, orphan reaping); proxy header injection and secret-leak lint.
- **Golden-file:** snapshot every rendered template; generated projects must pass `ruff`/`eslint` and `mypy`/`tsc`.
- **★ Runtime integration (the critical suite):** scaffold into a tmpdir, run `langctl dev` against a **stub model server**, then assert — `:2024/ok` healthy; `GET :3000/` 200; `POST :3000/api/agent/threads` proxies through; a run **streams SSE through the proxy** with tokens arriving incrementally (not buffered — assert timing, not just the final body); editing `agent.py` triggers reload and the next request succeeds; SIGINT leaves **zero** surviving PIDs and both ports free. Matrix: `{python, node} × {nextjs_proxy, vite_proxy, none}` + Mode B, on Linux and macOS, plus a Windows smoke run.
- **Docker:** `langctl dev --docker` → `langgraph up` on 8123, proxy retargets, thread state survives a container restart (proves the checkpointer).
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
