# Architecture

Part of [`langctl` — a Next.js-style CLI for building, running, and deploying LangChain agents](./PLAN.md).

## 4. Architecture


```
agent_cli/
├─ pyproject.toml                    # langctl = langctl.main:app
├─ src/langctl/
│  ├─ main.py
│  ├─ commands/                      # new dev build deploy env providers doctor logs rollback destroy eject sync add
│  ├─ core/
│  │  ├─ spec.py                     # AgentSpec (pydantic) ← single source of truth
│  │  ├─ manifest.py                 # agent.yaml + .langctl/state.json
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

`langgraph.json` is generated from this and kept in sync by `langctl sync`, merging rather than clobbering hand edits (unknown keys preserved, drift reported, `--force` to overwrite owned keys).

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

Discovery: built-ins + entry points `langctl.providers` + a zero-Python declarative escape hatch (`providers.yaml` describing shell commands), so a user can add a custom cloud without forking.

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
  → write .langctl/state.json → print URLs + Studio link + rollback hint
```

The wiring step is the one everybody forgets by hand, and the reason a redeployed backend silently breaks a live frontend. Here it is automatic: if `api_url` changes, the frontend is redeployed too.

---
