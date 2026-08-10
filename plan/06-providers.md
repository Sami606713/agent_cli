# Deploy providers & plugin spec

Part of [`agentctl` — a Next.js-style CLI for building, running, and deploying LangChain agents](./PLAN.md).

v1 ships `langsmith_cloud` (backend) + `vercel` (frontend). Everything else is added behind the same
interface; Phase 5 adds `ecs`/`cloudrun`/`k8s_helm` as reviewable Terraform/Helm emitters rather than
black-box deploys. See [08-roadmap.md](./08-roadmap.md) for phasing and
[07-edge-cases.md](./07-edge-cases.md) for the entitlement and infra checks each provider must enforce.

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
