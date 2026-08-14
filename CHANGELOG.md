# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.12.0] - 2026-08-14

### Added

- **`langctl deploy` — the frontend and the agent ship together, in one
  operation.** One command brings up one stack on one host: the chat UI, the
  Agent Server, Postgres and Redis, behind a single URL.

  ```
  langctl deploy                        # this machine
  langctl deploy --host user@1.2.3.4    # a host you own
  langctl deploy --host … --domain x.io # the same, with automatic HTTPS
  ```

  The frontend reaches the agent at `http://agent:8000` — a service name on the
  private network, not a URL. There is nothing to paste into a config and
  nothing to update on the next deploy, so redeploying the agent cannot break
  the UI. Only the frontend publishes a port; the Agent Server has no route in
  from outside, so the LangSmith key stays server-side exactly as it does under
  `langctl dev`.

  Secrets live in `.env.deploy` and are checked *before* any image is built —
  a missing key stops the command in a second rather than ten minutes into a
  build. They are never uploaded by a deploy and never baked into an image; you
  place them on the host once.

  `--wait` on the compose start means a deploy that fails exits non-zero
  instead of handing back a URL that does not load. With `--domain`, Caddy
  joins the stack and obtains and renews a Let's Encrypt certificate on its
  own; it deliberately does not compress `text/event-stream`, since buffering
  the token stream to compress it is what makes an agent appear to hang and
  then answer all at once.

  Also `--logs`, `--down` (the database survives unless `--volumes`, which
  prompts), `--build-only` and `--force`.

- `next.config.mjs` in the generated frontend now sets `output: "standalone"`,
  which is what lets the deployment image run without `node_modules`. It
  changes nothing for `langctl dev`.

## [0.11.1] - 2026-08-14

### Fixed

- **Child process output is decoded as UTF-8 on every platform.** `subprocess`
  with `text=True` and no explicit encoding uses the *locale* codec. On Linux
  and macOS that is UTF-8 and nothing goes wrong; on Windows it is the ANSI
  codepage, and every tool langctl supervises emits UTF-8 — Next.js opens with
  `▲ Next.js` and `✓ Ready in`.

  On Western Windows (cp1252) this produced mojibake. On Japanese and Korean
  installs (cp932, cp949) it raised `UnicodeDecodeError` on the very first
  line — and because `UnicodeDecodeError` subclasses `ValueError`, the log
  reader's own error handler swallowed it. The thread died silently before
  delivering a single line: no child logs at all, an empty error panel when a
  child failed to start, and `langctl share` never finding the tunnel URL it
  was waiting for.

- `langctl sync` crashed on Windows reading a `pyproject.toml` containing an em
  dash — the same missing-encoding mistake, through `Path.read_text`.

- The generated project declared `env` under `[tool.pytest.ini_options]`
  without depending on `pytest-env`, so pytest ignored it with a warning.

## [0.11.0] - 2026-08-14

### Changed

- **`core/` is organised into packages instead of twenty flat modules.**
  Grouped along the dependency lines that already existed: `catalog/` for the
  provider and middleware tables, `project/` for `agent.yaml`, `generate/` for
  rendering, `runtime/` for subprocesses and health, `wizard/` for prompts,
  with `errors.py` at the top so every package can import it without a cycle.
  No behaviour changed; imports were the only edits.

### Fixed

- `langctl new` no longer prints `add your None to .env` for providers that
  have no API key, such as Ollama and Bedrock.

### Added

- Contribution guidelines and CI workflows.

## [0.10.1] - 2026-08-13

### Fixed

- **A model name is no longer guessed for providers that cannot have one.**
  0.10.0 baked `llama3.2` into the generated `config.py` for Ollama. If you had
  not pulled that exact model it failed on the first message with an opaque 404,
  and nothing in `.env.example` suggested changing it.

  Ollama, LiteLLM, HuggingFace, any custom `base_url`, and any provider langctl
  does not recognise now read `MODEL_NAME` from the environment with no baked-in
  fallback. `.env.example` lists it as required and seeds the value you chose;
  the generated config fails at import with a message that names the fix (for
  Ollama, `ollama list`). Hosted providers keep their default, where guessing is
  safe.

  `--model` is required for these providers, and the interactive wizard asks for
  it instead of erroring. A `ModelSpec` for one of them with no name recorded now
  stores an empty name rather than the previous provider's model, so `agent.yaml`
  never claims something like `ollama:claude-opus-5`.


## [0.10.0] - 2026-08-13

### Added

- **Custom models.** `model.provider` was a fixed list of five; it is now open.
  25 providers are registered with their package and credential variable
  (verified against `init_chat_model`), and an unrecognised provider is accepted
  as long as `model.package` says what supplies it — so a new LangChain
  integration is usable the day it ships rather than after a langctl release.
- `--model-base-url` for OpenAI-compatible endpoints (LM Studio, vLLM, a LiteLLM
  proxy). A `provider:model` string cannot carry an endpoint, so those projects
  construct the model object and hand that to `create_agent`, which takes either.
- `--model-package`, `model.api_key_env_override`, and `model.options` for
  per-model settings such as `temperature`.
- Provider aliases (`google` → `google_genai`, `azure` → `azure_openai`, …) and
  a did-you-mean suggestion on a typo.

### Fixed

- Choosing a provider without naming a model kept the previous provider's
  default, so `--model-provider openai` produced `openai:claude-opus-5`. The
  model now follows the provider unless named explicitly.
- Providers that need no API key — Ollama, or anything using ambient cloud
  credentials — no longer have a key demanded of them at import.


## [0.9.1] - 2026-08-13

### Fixed

- **`langctl new` crashed on Windows** with
  `FileNotFoundError: [WinError 2] The system cannot find the file specified`
  while installing frontend dependencies. npm, pnpm and npx are installed as
  `.cmd` shims on Windows, and `CreateProcess` cannot launch those from a bare
  name — even though the shell can, and even though `shutil.which` finds them.
  The code checked with `which` but then spawned the unresolved name.

  Every program langctl spawns is now resolved to a full path first
  (`core/executables.py`), which is what `which` already returned. That covers
  `npm`, `pnpm`, `npx`, `uv`, `git` and `docker`, in `new`, `dev`, `share`,
  `doctor` and the Node runner — not only the one call site that was reported.

### Added

- A static test that parses the package and fails if any `subprocess.run` or
  `Popen` starts with a bare program name. Verified by reintroducing the
  original bug and watching it fail.


## [0.9.0] - 2026-08-13

### Changed

- **The chat UI is now LangChain's `agent-chat-ui`, vendored unmodified** at a
  pinned commit under the MIT licence. It brings thread history, an agent inbox
  for human-in-the-loop approvals, artifacts, markdown with syntax highlighting,
  attachments and generative UI — none of which the hand-built templates had.
- The setup screen that asks for a deployment URL and assistant ID **never
  appears**, because `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_ASSISTANT_ID` are
  pre-filled. It is bypassed rather than deleted: the source stays byte-identical
  so a future re-sync is a diff, not a merge.
- `langctl dev` and `langctl share` now set `LANGGRAPH_API_URL` for the app's own
  passthrough instead of the old `AGENT_PROXY_TARGET`.

### Removed

- The `nextjs_minimal`, `nextjs_assistant_ui` and `nextjs_ai_elements` templates,
  and the `_shared` layer that existed to keep one proxy route across them.
  agent-chat-ui is self-contained. Every old `frontend.kind` still loads and maps
  to the new one, and an existing `web/` directory is left untouched.
- The `--ui` question in the wizard. The flag remains for scripts that pass it.

### Notes

The vendored app arrived at the same architecture langctl already used — a
same-origin passthrough with the API key attached server-side. Its `.env.example`
says so explicitly: "Do NOT prefix this with NEXT_PUBLIC_". Its passthrough runs
on the edge runtime where ours used nodejs.

Verified end to end: `npm install`, `tsc --noEmit`, `next build`, then `langctl
dev` serving the chat with no setup screen, the passthrough reaching the agent,
no key in the page, and both ports released on shutdown.


## [0.8.1] - 2026-08-13

### Changed

- Custom middleware is now a **package with one module per class**
  (`middleware/custom/rate_limit.py`) rather than everything appended to a
  single `custom.py`, mirroring how `tools/` already works. A shared module
  becomes a merge-conflict site as soon as two people add one, and grows without
  bound.
- The generated `custom/__init__.py` re-exports every class, with imports and
  `__all__` sorted so the package passes the `ruff` config it ships with.
  Execution order still follows `agent.yaml`, not the alphabet.
- The `# custom` label is emitted once rather than once per entry.


## [0.8.0] - 2026-08-12

### Added

- Middleware support. A registry of 13 built-ins, emitted into
  `middleware/__init__.py` in a fixed **semantic** order — guardrails → context
  → limits → reliability → human-in-the-loop → capability → custom — because
  redaction placed after summarization means raw content already reached the
  summarizing model.
- `langctl add middleware <name> | --custom <name> | --list`.
- Custom middleware scaffolds as a bare class with **no hook methods**. Which
  hooks a middleware needs is the whole design decision; the docstring lists all
  six with their real signatures so the choice can be made in place.

### Changed

- **New projects now have cost guards by default**: `ModelCallLimitMiddleware`
  (20 model calls per run), `ToolCallLimitMiddleware` (30 tool calls) and
  `ToolRetryMiddleware` (2 retries). This changes behaviour — an agent that
  previously ran unbounded now stops. The limits are in `agent.yaml`.
- Generated projects now lint clean under the `ruff` config they ship with.
  Conditional templates were importing modules their chosen branch never used,
  so a freshly scaffolded project failed its own `ruff check` with 13 errors.

### Notes

The registry's parameter names were wrong on the first pass — taken from the
docs rather than the constructors — and only importing the generated module
caught it. `ModelCallLimitMiddleware` takes `run_limit`/`thread_limit`, not
`max_calls`; `SummarizationMiddleware` requires a model (defaulted to the
project's own); `PIIMiddleware` takes a single `pii_type`, so N types produce N
instances.

Three middleware are deliberately not offered. `ToolErrorMiddleware` requires an
`on_error` callable, which cannot be expressed in YAML — write it as custom
middleware. `ModelFallbackMiddleware` and `HumanInTheLoopMiddleware` are
rejected unless their required settings are present, rather than emitting a call
that raises at import.


## [0.7.0] - 2026-08-12

### Added

- `langctl share` — puts the locally running app on a public URL through
  cloudflared or ngrok. **One** tunnel covers the whole app: because the browser
  reaches the agent through the frontend's proxy, exposing the frontend is
  enough, and the agent port and API keys never become reachable from outside.
  `--backend-only` exposes the agent API instead, and warns first.
  cloudflared is preferred because its quick tunnels need no account.
- `ProcessSpec.on_line` and `ProcessSpec.echo` on the supervisor, so a process's
  output can be scraped for a value it only announces in prose (a tunnel URL)
  without flooding the console.
- `tests/e2e/share_tunnel.sh` — runs a live tunnel and checks the public URL
  serves the app, the agent answers through the proxy, and SIGTERM releases both
  ports with no stray tunnel client.

### Changed

- README rewritten: full command reference, the memory model and why the two
  memories have opposite defaults, upgrading older projects, and an explicit
  note that `langctl deploy` is **not built yet** rather than implying it exists.


## [0.6.0] - 2026-08-12

### Added

- `langctl add memory | frontend | tool` — bring a feature into a project that
  already exists, instead of only choosing at creation.
  - `add memory` reuses the creation wizard, so the questions are identical, and
    warns before reconfiguring memory that is already on.
  - `add tool "lookup order"` scaffolds the module and splices it into the
    `TOOLS` registry, or prints the two lines to add if the registry has been
    restructured.
- `plan_layers()` renders templates to memory, which is what lets `add` tell a
  file it generated from one you edited.

### Notes

`add` does not simply skip existing files. The template has already written a
file for the *old* spec, so skipping would leave the project stale — a
`langgraph.json` promising durable memory while `store.py` still returns an
in-memory store. That is silent wrongness rather than an error, and it is what
the first implementation did. Files are now compared against what the template
*would have written before the change*: identical means untouched and safe to
regenerate, different means you edited it and it is left alone and reported.

Editing `agent.yaml` cannot preserve comments through a PyYAML round-trip, so a
commented file is backed up to `agent.yaml.bak` before the section is replaced.


## [0.5.0] - 2026-08-12

### Added

- Postgres as a long-term memory backend, selectable at creation
  (`--memory-backend postgres`, or the new wizard question). SQLite remains the
  default. Set `POSTGRES_URI`; the schema is created on first start, so there is
  no migration step of your own.
- `langctl doctor` verifies a Postgres backend is actually reachable, and
  distinguishes "URI not set", "driver not installed", and "cannot connect".

### Fixed

- `doctor` probed for `psycopg` in langctl's own environment rather than the
  project's, so a working Postgres project was reported as broken. It now runs
  the probe with the project's interpreter, the same way the `langgraph` binary
  is resolved.

### Verified

Both backends were tested against a real server, not just rendered: write a
memory, kill the whole process group, restart, read it back. The Postgres path
additionally covers the SQLAlchemy `+psycopg` URI prefix that psycopg3 rejects,
and the missing-`POSTGRES_URI` error message.


## [0.4.0] - 2026-08-12

### Added

- `langctl new` now asks about memory, using progressive disclosure: long-term
  memory is simply on (it costs nothing and needs no services), semantic search
  is one yes/no question, and only if you say yes are you asked how embeddings
  are produced. Asked *after* the chat provider, because the embeddings default
  depends on it — and choosing Anthropic warns that it has no embeddings API, so
  search means a second vendor and key.
- Non-interactive equivalents for CI and scripting: `--memory/--no-memory`,
  `--semantic-search`, `--embeddings {local,provider,custom}`,
  `--embedding-model`.

### Fixed

- **`langctl sync` now updates `pyproject.toml` dependencies**, not just
  `langgraph.json`. Turning on semantic search in `agent.yaml` previously left
  the embeddings package uninstalled, producing a project that passes
  `langgraph validate` and then dies at server startup with a
  ModuleNotFoundError. `sync --check` exits non-zero on dependency drift, so CI
  catches it. Only the `dependencies` array is rewritten; hand-added packages
  and every other section are left untouched.


## [0.3.0] - 2026-08-12

### Added

- **Long-term memory, on by default, with no services to run.** Generated
  projects ship a `memory/` package backed by SQLite and wired through
  `store.path` in `langgraph.json`, plus `save_memory` / `recall_memory` tools
  namespaced per user.
- Embeddings in three modes for semantic search (off by default): `provider`
  (hosted API), `local` (sentence-transformers, no key), and `custom` (your own
  function). `dims` is derived from the model, because a wrong width cannot be
  corrected without re-embedding everything.
- Dependency fan-out: enabling a feature adds its package to `pyproject.toml`
  and its key to `.env.example`. A missing package is a startup failure that
  `langgraph validate` reports as valid.
- `tools/` and `prompts/` are now packages, so adding a tool never touches
  agent wiring.
- `tests/e2e/memory_persistence.sh` — writes a memory, kills the server's whole
  process group, restarts, and reads it back.

### Changed

- `memory` in `agent.yaml` is now `{short_term, long_term}`. The 0.2.0 shape
  (`checkpointer`/`store`/`semantic_search`) still loads and is migrated.
- `data/` and `*.sqlite` are gitignored — those files hold real conversations.

### Notes

Why the two memories have opposite defaults: verified against a real restart,
`langgraph dev` keeps the long-term store **in process** and loses every item on
exit, so overriding it is a strict gain. The checkpointer is the reverse — the
server manages threads well, and a custom one lacking `adelete_for_runs` stops
cleaning up checkpoints from cancelled runs. So long-term memory is ours by
default; short-term stays server-managed unless asked for.


## [0.2.0] - 2026-08-11

### Added

- Three chat UI templates, selectable with `langctl new --ui`:
  - `assistant-ui` (default) — the assistant-ui runtime via npm, with a
    converter mapping LangChain `BaseMessage[]` to `ThreadMessageLike[]`.
  - `minimal` — a single hand-written `Chat.tsx` with no UI dependencies
    (this is what 0.1.0 shipped as `nextjs_proxy`).
  - `ai-elements` — **experimental**, see Known issues.
- `frontend/_shared` template layer holding the proxy route, layout, Tailwind
  entry, and build config, so those exist in exactly one place rather than once
  per UI.
- `render_layers()`, which resolves template layers in memory before writing.
  This keeps "a later layer overrides an earlier one" separate from "never
  overwrite a file the user edited".

### Changed

- Default frontend is now `nextjs_assistant_ui`. Projects created with 0.1.0
  keep working: the old `nextjs_proxy` and `vite_proxy` names are accepted and
  mapped to `nextjs_minimal`.
- No template contains hand-written CSS. `globals.css` is `@import
  "tailwindcss";` and nothing else; the `ai-elements` template adds a Tailwind
  v4 `@theme` token block because its components reference semantic classes.
  A test fails the build on any CSS rule block outside `@theme`.

### Removed

- Dead `html, body { height: 100% }` rule. `h-dvh` is a viewport unit and never
  depended on ancestor heights.

### Known issues

- `--ui ai-elements` currently fails `npm run build`. Its generated components
  pull `streamdown`, which resolves two incompatible copies of `shiki`
  (4.4.3 and 3.23.0); npm `overrides` do not dedupe them. Our own files
  typecheck clean — the failure is entirely in the vendored components. The
  option is excluded from the interactive wizard and reachable only via an
  explicit `--ui ai-elements`.

## [0.1.0] - 2026-08-10

First release: scaffold a LangChain agent with a chat UI, and run both as one
application.

### Added

- `langctl new` — scaffolds a `create_agent` backend, a Next.js frontend, and a
  `langgraph.json` generated from `agent.yaml`.
- `langctl dev` — runs the Agent Server and the frontend as a single foreground
  process group. The frontend does not start until the agent answers `/ok`, both
  share one prefixed log stream, and Ctrl-C tears everything down.
- `langctl sync` — regenerates `langgraph.json` from `agent.yaml`, merging rather
  than overwriting so hand-written keys survive.
- `langctl doctor` — checks toolchain, ports, API keys, and validates
  `langgraph.json` with the real `langgraph validate`.
- A same-origin proxy route: the browser only ever calls `/api/agent/...` on the
  frontend's own origin, so CORS never applies and the LangSmith API key is
  attached server-side and never reaches the client. Dev and production differ
  only by `AGENT_PROXY_TARGET`.

### Fixed

- `Failed to construct 'URL': Invalid URL` on the first message. The LangGraph
  SDK builds request URLs with `new URL(apiUrl + path)` and no base argument, so
  the relative `apiUrl` the chat component passed threw immediately. It now
  derives an absolute same-origin URL.
- Route handler directory now derives from `frontend.proxy_prefix`. It was
  hardcoded, so changing the prefix moved the client's calls while leaving the
  handler behind.
- `langctl --version` was unreachable: Click does not invoke a group's callback
  when no subcommand is present.
- Shutdown signals. SIGTERM was not handled at all, and SIGINT is inherited as
  `SIG_IGN` from non-interactive shells, so `except KeyboardInterrupt` never
  fired. Both left `langgraph dev` and `next dev` orphaned holding their ports.

[Unreleased]: https://github.com/Sami606713/agent_cli/compare/v0.10.1...HEAD
[0.10.1]: https://github.com/Sami606713/agent_cli/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/Sami606713/agent_cli/compare/v0.9.1...v0.10.0
[0.9.1]: https://github.com/Sami606713/agent_cli/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/Sami606713/agent_cli/compare/v0.8.1...v0.9.0
[0.8.1]: https://github.com/Sami606713/agent_cli/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/Sami606713/agent_cli/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/Sami606713/agent_cli/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/Sami606713/agent_cli/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Sami606713/agent_cli/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Sami606713/agent_cli/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Sami606713/agent_cli/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Sami606713/agent_cli/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Sami606713/agent_cli/releases/tag/v0.1.0
