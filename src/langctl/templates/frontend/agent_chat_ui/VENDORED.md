# Vendored from langchain-ai/agent-chat-ui

Source: https://github.com/langchain-ai/agent-chat-ui
Commit: `d96e46f365f55f3e23ef1036fe05de7c53064897`
License: MIT (see LICENSE)

The application code is copied unmodified except for two marked patches (see
below). The setup screen that asks for a
deployment URL and assistant ID is not removed — it is simply never reached,
because `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_ASSISTANT_ID` are pre-filled.
Keeping the source byte-identical means a future re-sync is a plain diff.

To re-sync:

    git clone https://github.com/langchain-ai/agent-chat-ui
    diff -r agent-chat-ui/src src

## Local patches

The application source is otherwise byte-identical to upstream, so re-syncing
stays a plain diff. Two files are deliberately changed:

### `next.config.mjs` — `output: "standalone"`

Lets the deployment image run `node server.js` without `node_modules`. No
effect on `next dev`.

### `src/providers/Stream.tsx` — `resolveApiUrl()`

`@langchain/langgraph-sdk` builds every request with
``new URL(`${apiUrl}${path}`)``, which throws on a relative value:
`new URL("/api/threads")` is an Invalid URL because it has no base. langctl
points the UI at `/api`, the same-origin passthrough route, so the value is
resolved against `window.location.origin` before it reaches the SDK.

Resolved in the browser rather than baked in at build time, so one image serves
localhost, a bare IP, a tunnel and a custom domain without rebuilding.

Verified present in SDK 1.9.27, 1.9.28 and 1.9.29 — this is the SDK's contract,
not a regression. Upstream agent-chat-ui does not hit it because its documented
default is an absolute `http://localhost:2024`.

### Branding — the app is named after your project

`src/components/icons/langgraph.tsx` is regenerated wholesale: it exports the
project's display name as `APP_NAME` and draws a mark from the project's
initials on a colour derived from its name. The filename and the exported
component name are upstream's, so every import site keeps working untouched.

`src/app/layout.tsx` takes the project name as the browser tab title, and
`src/app/icon.svg` replaces the vendored `favicon.ico` — Next serves
`app/icon.svg` as the tab icon, and shipping both would leave the browser
choosing.

`src/components/thread/index.tsx` is **patched, not templated**: it contains
seven JSX style props written with double braces, which Jinja would consume as
expressions. It imports `APP_NAME` and renders it in single braces, which Jinja
never touches. Any file in this tree with JSX object props must be handled the
same way.

All patches are marked in-file and covered by tests, so a re-sync that drops
them fails the suite rather than shipping a broken or unbranded UI.
