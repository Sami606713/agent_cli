# Command surface

Part of [`langctl` — a Next.js-style CLI for building, running, and deploying LangChain agents](./PLAN.md).

## 5. Commands


| Command | Behavior |
|---|---|
| `langctl new [name]` | Rich wizard → `agent.yaml`, renders backend (+frontend +proxy), `git init`, installs deps. `--yes` + flags for CI. |
| **`langctl dev`** | **The headline command.** §3. Flags: `--backend-only`, `--frontend-only`, `--port/--backend-port`, `--no-open`, `--docker` (uses `langgraph up` on 8123 for a production-like run), `--tunnel` (public URL for webhook/mobile testing). |
| `langctl studio` | Opens Studio against the running local server. |
| `langctl sync` | Regenerate `langgraph.json`, `.env.example`, proxy config, Dockerfile, CI from `agent.yaml`; report drift. |
| `langctl add tool\|frontend\|ui-component\|provider\|eval` | Idempotent additions. `add frontend` retrofits the proxy onto a backend-only project. |
| `langctl env set/pull/push/diff` | Per-environment env; push to provider secret stores; never committed. |
| `langctl build` | `langgraph build` + frontend build. |
| `langctl deploy [--env prod] [--backend-only] [--frontend-only] [--dry-run] [--resume]` | §4.3. |
| `langctl logs [--backend\|--frontend] [-f]`, `rollback`, `destroy` | Proxy to provider; `destroy` needs the typed name. |
| `langctl providers list/add/test` | Capability matrix; register/validate custom providers. |
| `langctl doctor` | python/node/docker/uv versions, `langgraph-cli` version compat, ports 2024/3000, API keys valid, plan tier, Docker daemon, provider auth. |
| `langctl eject` | Emit raw scripts/Dockerfile/Compose/workflows and drop the CLI. **Anti-lock-in is a feature.** |

Generated projects also carry plain `npm run dev` / `make dev` equivalents that call the same supervisor, so a teammate without `langctl` installed can still run the app.

---
