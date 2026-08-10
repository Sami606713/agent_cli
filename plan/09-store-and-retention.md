# Store, memory, and data retention

Part of [`langctl` — plan](./README.md). Scope: make every generated project ship a
`langgraph.json` whose **store** and **retention** settings are production-correct by
default, instead of the minimal config we emit today.

## 1. Context

`langctl` currently emits `store` only when `memory.semantic_search` is true, and when it
does it hardcodes:

```json
"store": { "index": { "embed": "openai:text-embedding-3-small", "dims": 1536, "fields": ["$"] } }
```

Three things are wrong with that, and one whole key is missing:

1. **The embedding provider is hardcoded to OpenAI** while the default chat model is
   Anthropic. Anthropic has no embeddings API at all, so the user silently needs an
   `OPENAI_API_KEY` that `.env.example` never mentions.
2. **The dependency is never added.** Turning on semantic search makes the server fail
   to boot, because `langchain-openai` is not in `pyproject.toml`.
3. **`dims` is hardcoded to 1536** regardless of model. Any other model produces a
   dimension mismatch on the first write.
4. **`checkpointer.ttl` is never emitted.** Thread and checkpoint data therefore grows
   without bound — the most expensive default in the whole config.

## 2. Findings (verified, not assumed)

Verified against `langgraph-cli 0.4.31`, the published
[config schema](https://raw.githubusercontent.com/langchain-ai/langgraph/refs/heads/main/libs/cli/schemas/schema.json),
and a real `langgraph dev` boot.

### 2.1 The failure mode validation does not catch

Adding `store.index` without the embeddings package:

```
$ langgraph validate
Configuration file langgraph.json is valid. (1 graph found)     ← passes

$ langgraph dev
Loading embeddings openai:text-embedding-3-small
ImportError('Could not import langchain-openai python package.')
ModuleNotFoundError: No module named 'langchain_openai'
Application startup failed. Exiting.                            ← hard failure
```

`validate` checks config shape, not whether the referenced model can be constructed. The
failure surfaces only at startup. **Whenever we emit `store.index`, we must also add the
matching provider package to `pyproject.toml` and the API key to `.env.example`.** This is
the single most important rule in this document.

### 2.2 `store` schema

| Field | Type | Notes |
|---|---|---|
| `index.embed` | string | `"provider:model"` **or** `"./path/to/file.py:async_fn"` for a custom function. |
| `index.dims` | integer | Must match the model's output dimension or writes fail. |
| `index.fields` | string[] | Defaults to `["$"]` (embed the whole JSON). Can be `["text", "metadata.title"]`; each is embedded separately. |
| `ttl.default_ttl` | float | **Minutes.** Applies only to items created after deploy. Omitted ⇒ never expires. |
| `ttl.refresh_on_read` | bool | Default `true`. `get`/`search` reset the timer. |
| `ttl.sweep_interval_minutes` | int | Default 5. Omitted ⇒ no sweeping. |

Two constraints from the docs that shape the design:

- **One embedding model per deployment.** Multiple models are not supported, because
  `/store` endpoints would become ambiguous.
- **Changing `embed` or `dims` requires re-embedding everything.** There is no migration
  tooling. So this is a decision the scaffold must get right up front, and one `langctl`
  must refuse to silently change later.

### 2.3 `checkpointer.ttl` — the missing key

| Field | Type | Notes |
|---|---|---|
| `strategy` | `"delete"` \| `"keep_latest"` | `delete` removes the whole thread; `keep_latest` keeps the thread and newest checkpoint, pruning history. |
| `default_ttl` | float | Minutes. `delete` window does **not** refresh with activity; `keep_latest` refreshes on run completion. |
| `sweep_interval_minutes` | int | Defaults to ~5. |
| `sweep_limit` | int | Threads per sweep. Default 10000 (server v0.12+), 1000 (v0.8–0.11). |

Global TTL applies to **new** threads only; `delete` is not retroactive.

### 2.4 Embedding providers accepted by the `provider:model` string

From `langchain.embeddings.init_embeddings`:

`openai`, `azure_ai`, `azure_openai`, `bedrock`, `cohere`, `google_vertexai`,
`huggingface`, `mistralai`, `ollama`

**`anthropic` is absent** — it offers no embeddings API. A project whose chat model is
Anthropic must pick a *different* provider for embeddings. Note also that Google chat
models use `google` while Google embeddings use `google_vertexai`, which is different
auth (service account, not an API key).

Requires `langchain >= 0.3.8` for the string form.

## 3. Design

### 3.1 Spec additions (`agent.yaml`)

```yaml
memory:
  checkpointer: postgres
  store: postgres
  semantic_search: true
  embeddings:                       # only meaningful when semantic_search is true
    provider: openai                # must be an init_embeddings provider
    model: text-embedding-3-small
    dims: 1536                      # auto-filled from the table; overridable
    fields: ["$"]
  retention:
    threads:                        # → checkpointer.ttl
      enabled: true
      strategy: delete
      days: 30
      sweep_interval_minutes: 60
    store:                          # → store.ttl
      enabled: true
      days: null                    # null ⇒ memories never expire
      refresh_on_read: true
      sweep_interval_minutes: 120
```

Days are the user-facing unit; `langctl` converts to the minutes the schema wants
(`days * 1440`). Minutes-as-a-float is a foot-gun in a hand-edited file — `default_ttl:
43200` reads like milliseconds to most people.

### 3.2 Known embedding dimensions

Auto-fill `dims` from the model, since a mismatch is an unrecoverable data error. Values
below come from **provider documentation, not from a live call** — the CLI should treat
them as defaults, not gospel, and always let `dims` be overridden.

| Model | dims |
|---|---|
| `openai:text-embedding-3-small` | 1536 |
| `openai:text-embedding-3-large` | 3072 |
| `openai:text-embedding-ada-002` | 1536 |
| `cohere:embed-english-v3.0` | 1024 |
| `cohere:embed-multilingual-v3.0` | 1024 |
| `mistralai:mistral-embed` | 1024 |
| `google_vertexai:text-embedding-004` | 768 |
| `ollama:nomic-embed-text` | 768 |

Unknown model ⇒ require an explicit `dims` rather than guessing.

### 3.3 Defaults, and why they differ for threads vs memories

**Threads: expire. Memories: do not.**

- `checkpointer.ttl` **on by default** — `strategy: delete`, 30 days, sweep hourly.
  Unbounded checkpoint growth is the default cost and compliance problem in every
  long-running deployment, and 30 days matches the documented example.
- `store.ttl` **on by default but with no `default_ttl`** — sweeping configured,
  `refresh_on_read: true`, nothing expires. Long-term memory exists precisely to
  outlive threads; silently deleting a user's remembered preferences after N days is a
  worse failure than disk growth, and the user can opt in with one line.

Both are one line to change in `agent.yaml`, and the generated `langgraph.json` carries
a comment block in the README explaining the retention posture. Because TTL deletes real
user data, `langctl sync` must show a **diff and require confirmation** when a retention
value changes, rather than applying it silently.

### 3.4 Coupled artifacts (the §2.1 rule, enforced)

When `semantic_search` is on, one spec change must fan out to four files:

| File | What is added |
|---|---|
| `langgraph.json` | `store.index` with resolved `embed` / `dims` / `fields` |
| `pyproject.toml` | `langchain-openai` (or the matching provider package) |
| `.env.example` | `OPENAI_API_KEY` with a comment saying it is for embeddings, not chat |
| `README.md` | A line noting embeddings cost money per stored item |

`langctl doctor` gains two checks: the embeddings package imports, and the embeddings
API key is set. Both are FAIL when `store.index` is configured, because the server will
not boot without them.

### 3.5 Provider selection logic

```
chat provider   → default embeddings provider
openai          → openai            (same key, nothing extra)
google          → google_vertexai   (WARN: different auth — service account, not API key)
anthropic       → openai            (WARN: Anthropic has no embeddings API; a second
                                     provider and key are required)
ollama          → ollama            (local, no key, no per-item cost)
bedrock         → bedrock           (same AWS credentials)
```

The warning is not decoration: an Anthropic user turning on semantic search is taking on
a second vendor, a second key, and a per-item cost. The wizard should say so at the point
of choice, not leave it to be discovered at boot.

## 4. Edge cases

- **Changing `embed`/`dims` after data exists** — no migration path. `langctl sync` must
  detect a change against `.langctl/state.json`, refuse by default, and require
  `--force` with a printed warning that all stored items must be re-embedded.
- **`store: none` + `semantic_search: true`** — incoherent; reject in spec validation.
- **`dims` mismatch** — cannot be validated offline. Document it; surface the runtime
  error clearly if it happens.
- **`fields` pointing at keys that do not exist** — items silently embed as empty. Note
  in the template comment; keep the `["$"]` default.
- **Local `langgraph dev` vs deployed** — the in-memory store honours `index`, so
  embeddings are called (and billed) in local development too. Worth a README line.
- **Ollama embeddings** — no key needed but requires a running local Ollama; `doctor`
  should check reachability rather than a key.
- **TTL sweep on a large table** — `sweep_limit` defaults to 10000 (server v0.12+);
  mention it for high-volume deployments rather than setting it.
- **`keep_latest` vs `delete`** — `keep_latest` preserves resumability while pruning
  history; offer it in the wizard for chat products where users return to old threads.

## 5. Verification

- **Unit:** spec → config for every provider; `days → minutes` conversion; dims
  auto-fill and the unknown-model error; incoherent combinations rejected; emitted keys
  still a subset of `owned_keys()`.
- **Golden-file:** a project with semantic search on contains the provider package in
  `pyproject.toml` and the embeddings key in `.env.example`. This is the regression test
  for §2.1 and is the one that matters most.
- **Schema:** validate generated `store` and `checkpointer` blocks against the published
  JSON schema, and run `langgraph validate` on the scaffold.
- **Boot test (the real one):** scaffold with `semantic_search: true`, install, and
  confirm `langgraph dev` reaches `/ok`. Today that boot fails; the test should prove it
  no longer does. A second case asserts the *absence* of the package produces our
  actionable error rather than a raw `ModuleNotFoundError`.
- **TTL:** assert emitted minutes (30 days ⇒ `43200`, 7 days ⇒ `10080`) and that
  `store.ttl.default_ttl` is absent by default.

## 6. Work items

1. `MemorySpec` gains `embeddings` and `retention`; add `EMBEDDING_DIMS` table and the
   provider-defaults map.
2. `to_langgraph_config()` emits `store.index`, `store.ttl`, `checkpointer.ttl`; add
   `checkpointer` to `owned_keys()`.
3. Template fan-out: conditional dependency in `pyproject.toml.j2`, embeddings key in
   `.env.example.j2`, retention/cost notes in `README.md.j2`.
4. Wizard: ask about semantic search; on Anthropic/Google, warn and confirm the
   embeddings provider.
5. `doctor`: embeddings package importable + key present when `store.index` is set.
6. `sync`: confirmation gate on retention changes; refuse `embed`/`dims` changes without
   `--force`.
7. Tests per §5, including the boot test.
