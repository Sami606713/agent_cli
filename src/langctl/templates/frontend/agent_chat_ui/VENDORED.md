# Vendored from langchain-ai/agent-chat-ui

Source: https://github.com/langchain-ai/agent-chat-ui
Commit: `d96e46f365f55f3e23ef1036fe05de7c53064897`
License: MIT (see LICENSE)

The application code is copied **unmodified**. The setup screen that asks for a
deployment URL and assistant ID is not removed — it is simply never reached,
because `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_ASSISTANT_ID` are pre-filled.
Keeping the source byte-identical means a future re-sync is a plain diff.

To re-sync:

    git clone https://github.com/langchain-ai/agent-chat-ui
    diff -r agent-chat-ui/src src
