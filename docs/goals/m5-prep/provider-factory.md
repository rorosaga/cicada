# Provider factory + model-comparison harness (M5 prep)

Shipped groundwork for **G10** (big-model bulk re-extraction): make OpenRouter *one
provider among many* and compare consolidation quality + cost across LLMs — without
touching the default path or the test suite.

## What landed

### `api/services/providers.py` — two pure factories

```python
resolve_llm_fn(settings, *, model=None, completion=None) -> LlmFn
resolve_embed_fn(settings, *, transport=None,
                 openai_client_factory=None,
                 sentence_transformer_factory=None) -> (embed_fn, model_name)
```

**LLM side.** `resolve_llm_fn` returns `fn(messages, *, response_format=None, **kw)`
bound to a model id. litellm already routes by the model-id **prefix**
(`openrouter/<id>`, `openai/…`, `anthropic/…`, `gemini/…`) reading the matching
`*_API_KEY` from env, so **OpenRouter needs no special-casing** — pointing a model id
at `openrouter/z-ai/glm-5.2` just works. The only OpenRouter-specific touch is opt-in
attribution headers (`HTTP-Referer`, `X-OpenRouter-Title`), attached **only** when the
resolved model starts with `openrouter/` *and* `CICADA_OPENROUTER_REFERER/TITLE` are set.

**How a model id selects a provider:** the prefix, end to end. `resolve_llm_fn`
defaults `model` to `settings.litellm_model`; pass
`settings.effective_consolidation_model` to use the consolidation override, or any
explicit id. litellm dispatches off the prefix.

**Embedding side.** `resolve_embed_fn` folds the old
`vector_index._resolve_embed_fn` (now a one-line shim) and adds a third mode:

| `CICADA_EMBEDDING_MODE` | backend | model default | dim |
|---|---|---|---|
| `local` (default) | sentence-transformers (asymmetric) | `google/embeddinggemma-300m` | 768 |
| `openai` | OpenAI `embeddings.create` | `text-embedding-3-small` | 1536 |
| `openrouter` | POST `…/api/v1/embeddings` | `google/gemini-embedding-2` | recorded live (~3072) |

OpenRouter embeddings are symmetric (`is_query` accepted-and-ignored), batched ≤100,
and **auto-degrade to local** when `OPENROUTER_API_KEY` is missing (mirrors openai).
The index records `{model, dim}` exactly as before, so switching = a reindex.

### Config (all defaulted to today's behavior — unconfigured install is byte-identical)

```python
consolidation_model: str = ""                                 # CICADA_CONSOLIDATION_MODEL (empty => litellm_model)
embedding_model_openrouter: str = "google/gemini-embedding-2" # CICADA_EMBEDDING_MODEL when mode=openrouter
openrouter_referer: str = ""                                  # CICADA_OPENROUTER_REFERER
openrouter_title: str = "Cicada"                              # CICADA_OPENROUTER_TITLE
```

`effective_consolidation_model` returns `consolidation_model` if set, else
`litellm_model`. `resolved_embedding_mode` / `resolved_embedding_model` extended to
know the `openrouter` mode + its key.

## `benchmarks/run_model_comparison.py` — the RUN harness

Reuses the **real** Stage-1 path (`entity_extractor.extract`) per model on the
biggest-N real episodes, capturing per-call `usage` (tokens + OpenRouter `cost`).

```sh
# side-by-side extraction across the 3 candidate models on the biggest episode
api/.venv/bin/python -m benchmarks.run_model_comparison --n 1

# explicit models + 3 episodes, truncated to 24k chars each
api/.venv/bin/python -m benchmarks.run_model_comparison \
    --models openrouter/z-ai/glm-5.2 openrouter/minimax/minimax-m3 openrouter/qwen/qwen3.7-max \
    --n 3 --max-chars 24000

# embed-only: live dim + latency for google/gemini-embedding-2
api/.venv/bin/python -m benchmarks.run_model_comparison --embed-test --n 0
```

Flags: `--models` (default = the 3 candidates), `--n` (biggest-N episodes, `<=0`
skips the LLM run), `--max-chars` (per-episode truncation = token-cap proxy),
`--embed-test` / `--embed-mode`.

Output (all under **gitignored** `benchmark_results/` — never committed):

```
benchmark_results/model_comparison/
    <episode_id>/<model_slug>.json   # entities, relationships, claims, summaries, usage{tokens,cost}
    index.md                          # table: rows=episodes, cols=models; cells = e/r/c · tokens · $cost
    embed_test.json                   # --embed-test: model, mode, dim, elapsed
```

Read-only over `memory/episodes/`; never mutates live `memory/`. RUN-phase only —
real network calls, **not** part of the unit suite.

## Tests

`api/tests/test_providers.py` — 16 hermetic tests (injected fake `completion` /
fake POST transport / fake OpenAI+ST factories; **no network**): default model
binding, explicit override, `response_format` forwarding, OpenRouter attribution
headers present/absent, `effective_consolidation_model` fallback, openai/local/
openrouter embed paths, missing-key degrade, batching.

```
api/.venv/bin/python -m pytest api/tests -q   # 254 passed (238 prior + 16)
```
