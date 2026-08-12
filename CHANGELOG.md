# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Sami606713/agent_cli/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Sami606713/agent_cli/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Sami606713/agent_cli/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Sami606713/agent_cli/releases/tag/v0.1.0
