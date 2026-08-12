# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Sami606713/agent_cli/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/Sami606713/agent_cli/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/Sami606713/agent_cli/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Sami606713/agent_cli/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Sami606713/agent_cli/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Sami606713/agent_cli/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Sami606713/agent_cli/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Sami606713/agent_cli/releases/tag/v0.1.0
