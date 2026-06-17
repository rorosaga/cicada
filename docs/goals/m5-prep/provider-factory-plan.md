# Provider Factory + Model-Comparison Harness — Plan (M5 prep)

Audit-only deliverable. No code changed. Maps every litellm call site + the embedding
resolution, fixes the factory shape that stays back-compatible (238 tests green), and plans
the consolidation-comparison harness against the real biggest episodes.

---

## 1. LLM call-site audit

Every LLM call in the codebase goes through **litellm**, reads the model id from `Settings`
(`api/config.py`), and passes it verbatim as `model=` to `litellm.completion` /
`litellm.acompletion`. The calls are *minimal* — only `model`, `messages`, and (usually)
`response_format={"type": "json_object"}`. **No** call passes `api_base`, `extra_headers`,
`temperature`, `max_tokens`, `drop_params`, etc. (confirmed by grep). That uniformity is what
makes a thin factory safe.

| Site | Fn | Model setting read | Notes |
|------|----|--------------------|-------|
| `entity_extractor.py:134` (`_extract_chunk`) | `acompletion` | `settings.litellm_model` | Stage-1 extraction; `response_format=json_object`. Reused by the harness. |
| `entity_extractor.py:215` (rate-limit retry) | `acompletion` | `settings.litellm_model` | second copy of the same call inside the `RateLimitError` retry. |
| `entity_resolver.py:690` (Stage-2 judge) | `acompletion` | `litellm_disambiguation_model or litellm_model` (resolved at `:28` and `:687`) | same/different/unsure; `json_object`. |
| `conflict_resolver.py:577` | `acompletion` | `settings.litellm_model` | merged-body synthesis; **no** `response_format` (returns markdown). |
| `conflict_resolver.py:626` | `acompletion` | `settings.litellm_model` | conflict-detection call. |
| `skill_extractor.py:76` | `acompletion` | `settings.litellm_model` | `json_object`. |
| `ask_service.py:260` (`_default_llm_fn`) | `completion` (sync) | `settings.litellm_model` | `json_object`; already behind an injectable `llm_fn` seam. |
| `link_enrichment.py:248` | `acompletion` | `getattr(settings,'litellm_model','') or 'gpt-5.4-mini'` | media-link summarize; capped per cycle. |

Author/provenance reads (NOT call sites, but read the same settings — leave untouched):
`claim_reconciler.py:112`, `link_enrichment.py:300`, `sleep_cycle.py:453-455` build
`Cicada-Author` trailers from `litellm_model` / `litellm_disambiguation_model`.

**Back-compat invariant:** services call litellm *directly*; they do not import a factory
today. The factory must be **additive** — default path keeps reading `settings.litellm_model`
and calling litellm exactly as now. Unit tests stub litellm or inject `llm_fn`/`embed_fn`;
none hit the network. We must not change the call shape the tests patch.

---

## 2. Embedding resolution audit

`vector_index.py :: _resolve_embed_fn()` (line 598) is the single embedding seam. It reads
`get_settings()`, resolves mode/model via `resolved_embedding_mode` / `resolved_embedding_model`
(`config.py:97-116`), and returns `(embed_fn, model_name)` where
`embed_fn(texts, *, is_query=False) -> np.ndarray (float32, 2-D)`:

- `openai`: `OpenAI().embeddings.create(model=..., input=batch)`, batched by 100, `is_query` ignored (symmetric).
- `local` (default): `SentenceTransformer(model)` with asymmetric `encode_query`/`encode_document`.

`_ensure_embed_fn` (line 103) calls `_resolve_embed_fn` only when no `embed_fn` was injected,
and records `model_name`. The index DB records `{model, dim}` (`_write_index_meta`, `index_info`)
and is derived/rebuildable, so adding a provider = a reindex. Tests inject a deterministic
`embed_fn`, so `_resolve_embed_fn` is never exercised in unit tests.

---

## 3. Factory shape (chosen design)

New module **`api/services/providers.py`** — a thin, hermetically-testable resolver layer.
Two factories, both pure functions of `Settings` + env, both returning the *exact callables the
existing code already expects*. No service rewrite required for back-compat; services may later
opt in, but the default path is unchanged.

### 3a. LLM factory

```python
def resolve_llm_fn(settings, *, model=None, completion=None) -> LlmCallable
```

- `model` defaults to `settings.litellm_model`; `completion` defaults to `litellm.completion`
  (injectable fake transport for tests — **no network in unit tests**).
- Returns a callable `(messages, *, response_format=None, **kw) -> CompletionResult` that just
  forwards to litellm with `model=` bound. Because litellm already routes
  `openrouter/<id>` / `openai/...` / `anthropic/...` / `gemini/...` purely from the model-id
  prefix (reading `OPENROUTER_API_KEY` etc. from env), **OpenRouter needs zero special-casing** —
  pointing `litellm_model` (or a new override) at `openrouter/z-ai/glm-5.2` just works.
- Add config knob `consolidation_model: str = ""` (`CICADA_CONSOLIDATION_MODEL`) →
  `effective_consolidation_model` property: returns it when set, else `litellm_model`. This lets
  the sleep/consolidation path target any provider (incl. `openrouter/...`) **without** touching
  the 238-test default (empty → identical to today).
- Optional OpenRouter attribution headers (`HTTP-Referer`, `X-OpenRouter-Title`) are added only
  when the resolved model starts with `openrouter/`, via litellm `extra_headers` — opt-in, never
  on the default path.
- **Back-compat:** services keep their inline `litellm.acompletion(model=settings.litellm_model,
  ...)` calls verbatim. The factory is the *new* preferred seam (harness uses it); migrating the
  services is out of scope for keeping tests green and is explicitly deferred.

### 3b. Embedding factory

Move `_resolve_embed_fn`'s body into `providers.py :: resolve_embed_fn(settings, *, transport=None)`
returning the same `(embed_fn, model_name)` tuple, and keep a one-line shim in `vector_index.py`
(`from api.services.providers import resolve_embed_fn as _resolve_embed_fn`) so nothing downstream
moves. Preserve the `embed_fn(texts, *, is_query=False) -> np.ndarray` contract and `{model,dim}`
recording exactly.

Add a third branch selected by `CICADA_EMBEDDING_MODE=openrouter`
(+ `CICADA_EMBEDDING_MODEL=google/gemini-embedding-2`, with a sane default model when unset):

```
POST https://openrouter.ai/api/v1/embeddings
Authorization: Bearer $OPENROUTER_API_KEY
{ "model": <embedding_model>, "input": <batch> }  ->  data[].embedding
```

- Batched (≤100), returns float32 2-D, `is_query` accepted-and-ignored (symmetric).
- Mirror the existing openai auto-degrade: if `mode==openrouter` and no `OPENROUTER_API_KEY`,
  degrade to `local` (extend `resolved_embedding_mode` to know the new mode + its key) and warn.
- **Dim is recorded from the live response at build time** (~3072 for gemini-embedding-2 —
  confirm at runtime; the index already stores `dim`, so no hard-coding).
- Injectable `transport` (a fake POST) keeps unit tests offline.

### 3c. Config additions (additive, all defaulted to today's behavior)

```python
consolidation_model: str = ""                 # CICADA_CONSOLIDATION_MODEL (empty => litellm_model)
embedding_model_openrouter: str = "google/gemini-embedding-2"  # CICADA_EMBEDDING_MODEL when mode=openrouter
openrouter_referer: str = ""                   # optional attribution
openrouter_title: str = "Cicada"               # optional attribution
```

`resolved_embedding_mode` / `resolved_embedding_model` extended to handle `openrouter`. Defaults
chosen so an unconfigured install behaves **byte-identically** to today → 238 tests stay green.

### 3d. TDD plan for the factory (hermetic, offline)

`api/tests/test_providers.py`:
1. `resolve_llm_fn` default → uses `settings.litellm_model`; injected fake `completion` captures
   the `model=` kwarg (assert no network).
2. `consolidation_model` set → `effective_consolidation_model` returns it; empty → `litellm_model`.
3. `openrouter/...` model → attribution headers present; non-openrouter → absent.
4. `resolve_embed_fn` mode=openai/local unchanged (fake transport / monkeypatched ST), returns
   `(fn, model)`, fn yields float32 2-D, `is_query` honored for local.
5. `mode=openrouter` with fake POST transport → posts to `/embeddings`, parses `data[].embedding`,
   records dim from response; missing key → degrades to local + warns.
6. Re-run full suite: `api/.venv/bin/python -m pytest api/tests -q` → **238 green**.

---

## 4. Consolidation-comparison harness plan

`benchmarks/run_model_comparison.py` (bootstraps via `benchmarks/_bootstrap.py`, loading
`api/.env` → `OPENROUTER_API_KEY`). Reuses the **real** Stage-1 path:
`entity_extractor.extract(episodes, settings)` (and/or `_extract_chunk` + `EXTRACTION_SYSTEM_PROMPT`),
overriding the model per run via the new `resolve_llm_fn` / a per-run `Settings(litellm_model=...)`.

- **Models:** the 3 ids, overridable by `--models` (default
  `openrouter/z-ai/glm-5.2`, `openrouter/minimax/minimax-m3`, `openrouter/qwen/qwen3.7-max`).
- **Episodes:** `--n` biggest by byte size from `memory/episodes/` (the 3 largest below), with a
  per-episode **token cap** (`--max-tokens` / truncate) so cost stays bounded.
- **Run:** for each (episode × model) run real extraction → write
  `benchmark_results/model_comparison/<episode>/<model>.json` containing
  `{entities, relationships, claims (via entities_to_claims), summary(s), usage{tokens, cost}}`.
  OpenRouter returns `usage.cost` + token counts on the litellm response — capture per call and
  sum per (episode, model).
- **Index:** write `benchmark_results/model_comparison/index.md` — a side-by-side table
  (rows=episodes, cols=models; cells = #entities / #claims / tokens / $cost) plus totals.
- **`--embed-test`:** embed a few fixed strings with `google/gemini-embedding-2` via the new
  OpenRouter embeddings provider; record **actual dim** + cost to
  `benchmark_results/model_comparison/embed_test.json`.
- **Safety:** read-only over `memory/episodes/`; never mutates live `memory/`; all output under
  gitignored `benchmark_results/`. Exercised in the RUN phase (real calls) — not in unit tests.

---

## 5. Three biggest real episodes (by bytes, from `memory/episodes/`)

1. `ep_2026-02-23_002.md` — 293,404 B
2. `ep_2026-03-09_003.md` — 244,939 B
3. `ep_2026-04-04_002.md` — 158,916 B

(next: `ep_2026-02-18_001.md` 117,126 B, `ep_2026-03-17_001.md` 80,299 B — use with `--n 5`.)
