# Edge cases & preflight acceptance criteria

Part of [`langctl` — a Next.js-style CLI for building, running, and deploying LangChain agents](./PLAN.md).

## 7. Edge cases (acceptance criteria for `doctor`/`preflight`)


**Unified runtime — the new, highest-risk surface**
- Port 2024 or 3000 occupied → detect, offer the next free port, and thread it through the proxy target automatically.
- Backend crashes at startup (import error, bad key) → the frontend must **not** boot into a broken app; surface the backend traceback as the primary error and exit non-zero.
- Backend healthy but slow to start → bounded exponential backoff on `/ok`, clear "still waiting… (12s)" progress, hard timeout with the actual tail of backend logs.
- Ctrl-C / SIGTERM → kill the whole process group; no orphaned `langgraph dev` holding 2024 hostage on the next run. Detect and offer to reclaim a stale orphan.
- Hot reload: backend restarts on Python change (langgraph handles it); the proxy must survive the gap and retry rather than 502 an in-flight stream.
- SSE through the proxy: disable response buffering, `changeOrigin`, **600s timeouts** on both sides, forward `text/event-stream` untouched, no compression middleware.
- Windows/WSL: no POSIX process groups — use `CREATE_NEW_PROCESS_GROUP` + job objects; test explicitly.
- Interleaved logs must not corrupt Rich's live display; log-mux takes a lock.
- `--docker` mode: `langgraph up` is on **8123**, not 2024 — the proxy target must follow the mode, not a constant.

**Plan / entitlement**
- No LangSmith Plus → detect **before** building; explain and offer Mode B on Vercel or `compose_ssh`.
- Self-hosted control plane / Hybrid without an Enterprise license → refuse early, point at standalone.
- Pre-Oct-2026 pricing orgs need `--deployment-type dev|prod`; probe the org and choose the right flag.

**Infra correctness**
- Standalone Agent Server on a serverless/scale-to-zero provider → hard block (documented task loss).
- Shared Postgres/Redis → force distinct database name and Redis db index; refuse duplicates.
- `LANGSMITH_ENDPOINT` trailing slash → strip and warn (causes auth errors).
- Air-gapped: no egress to `beacon.langchain.com` → license check fails; flag in `doctor`, point at image mirroring.
- Apple Silicon needs Buildx for `linux/amd64`; absent → fall back to remote build. No Docker at all → remote build; `dev` still works.

**Project state**
- Hand-edited `langgraph.json` → merge, report drift, never silently clobber.
- Monorepo / nested project → walk up to `agent.yaml`; honor `dependencies: ["./subdir"]`.
- Python version mismatch between venv and `langgraph.json` → warn.
- `uv` dependency-graph failure → name `pip_installer: "pip"` in the error text.
- Deployment name collision → detect existing deployment; always ask update-in-place vs create-new.

**Deploy lifecycle**
- Partial failure → state file records what exists; `--resume` continues.
- Backend URL change → frontend env re-injected and redeployed automatically.
- Rollback offered for both halves together, since they are wired.
- Concurrent deploys → advisory lock with stale-lock override.
- Ctrl-C mid-deploy → cleanup handlers; no orphaned cloud resources.

**Secrets & safety**
- `LANGSMITH_API_KEY` is injected **server-side in the proxy route only** — never `NEXT_PUBLIC_*`. A lint rule in the template CI fails the build if a secret is prefixed for the browser.
- Keyring first, `.env.local` fallback; `.gitignore` covers `.env*`, `.langctl/`, `.langgraph_api/`.
- `destroy` requires typing the deployment name.
- **Unrelated but urgent:** `/home/revnix/Desktop/research/github token ghp ….txt` holds a GitHub token in plaintext one directory above this repo. Revoke it.

---
