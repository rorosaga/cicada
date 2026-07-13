# Consolidation-Readiness Plan (M5-prep)

Audit-only plan ahead of a fresh real consolidation run of Rodrigo's Claude export into a
NEW empty bank (`claude-chats`), with the OLD 1,882-entity bank preserved and renamed
`original-v1`. Consolidation uses GLM 5.2 (`openrouter/z-ai/glm-5.2`) via litellm + the M5f
claim pipeline. All four prep changes must be **additive / decode-tolerant** for legacy data
and must keep the old graph intact and all **254 tests green** (no real models/network in tests).

---

## 0. Ground truth located in the audit

| Concern | Location |
|---|---|
| Python `EntityType` | `api/models/schemas.py:19` — `class EntityType(str, Enum)`; 10 members: person, project, company, concept, tool, deadline, skill, location, **media** (already present), + the closed-8 from CLAUDE.md. |
| Swift `EntityType` | `app/CicadaApp/Sources/CicadaApp/Models/Entity.swift:3` — `enum EntityType: String, Codable, CaseIterable, Identifiable`; `case person, project, company, concept, tool, deadline, skill, location`. (Swift currently lacks `media`; decode of an unknown raw type would fail unless there's a fallback — verify before relying on it.) |
| Extraction prompt (Stage-1) | `api/services/entity_extractor.py` — emits typed entities + relationships; type set is enumerated in the prompt text. |
| Embed resolution | `api/services/providers.py::resolve_embed_fn` (modes: `openai` / `openrouter[google/gemini-embedding-2]` / `local[embeddinggemma-300m]`) + `api/services/vector_index.py::_resolve_embed_fn` (thin wrapper, line 598) called by `SqliteVecIndexer._ensure_embed_fn` (line 103). |
| Index meta | `vector_index.py` writes `{model, dim}` into `index_meta` at **build** time (`_write_index_meta`, line 164); `index_info()` (line 175) reads it back. |
| Bank registry | `api/services/bank_registry.py` — `resolve_active_bank_path` (64), `bank_dir` (94), `load/save_registry`, `list/create/activate/duplicate_bank`. **No `rename_bank` exists.** |
| Banks router | `api/routers/banks.py` — list/create/activate/duplicate/`POST /banks/{name}/import`. |
| Active-bank resolution | `api/config.py:39` — `memory_path` is a **computed property** = `resolve_active_bank_path(memory_root)`. |

---

## 1. EntityType parity (Python ↔ Swift)

- Python already has `media`; Swift does not. If GLM emits any type beyond the Swift case set,
  the SwiftUI `Codable` decode of an entity/graph node will throw.
- **Action (additive):** add the missing case(s) to the Swift enum, OR add an `unknown`/default
  decoding fallback so legacy + future raw types decode tolerantly. Mirror any new Python member
  into Swift. Do NOT remove or rename existing members (breaks old `original-v1` frontmatter).
- The Stage-1 prompt enumerates the allowed types inline; if the type set changes, update the
  prompt enumeration in `entity_extractor.py` to match — but for THIS run keep the closed set the
  legacy bank already uses so `original-v1` stays decodable.

## 2. Per-bank query-embedding resolution (the real fix)

**Problem.** Build time records the true model into each bank's `index_meta`. But search-time
indexers are constructed with **no `embed_fn`** — `search.py:56`, `entities.py:318` & `:428`,
`status.py:62` all do `SqliteVecIndexer(memory_path)`. `_ensure_embed_fn` (line 103) then falls
through to `_resolve_embed_fn()`, which reads the **global** `Settings.resolved_embedding_mode/
model` — ignoring what that bank was actually built with. So if `original-v1` was built with model
A and the global env now points at model B (e.g. switched to openrouter for the new run), queries
get embedded with B against A's vectors → dimension mismatch or garbage cosine scores.

**Design (precise).** Resolve the embed fn **per bank, from `index_meta.model`**:

1. Add a helper (e.g. `providers.resolve_embed_fn_for_model(model_name, settings, *, ...injectables)`)
   that maps a recorded model id → its mode (`text-embedding-3-small`→openai,
   `google/gemini-embedding-2`→openrouter, `*embeddinggemma*`/local names→local) and builds that
   model's `embed_fn`. Reuse the existing `_openrouter_embed_fn` / openai / local branches; keep
   the same `(embed_fn, model) ` contract and `embed_fn(texts, *, is_query=False)->np.ndarray` shape.
2. At search time, read `SqliteVecIndexer(memory_path).index_info()` → `model`; if present, build
   the embed fn for that model and pass it into the indexer (`SqliteVecIndexer(memory_path,
   embed_fn=fn, model_name=model)`). If `index_info()` is empty (unbuilt) or model is `unknown`,
   fall back to today's global `_resolve_embed_fn()` — preserving legacy behavior.
3. Keep injectable transports/factories so **no test touches the network**; add unit coverage
   asserting "recorded openai model → openai branch chosen" with a fake client, mirroring
   `test_providers.py`.

**Why this is safe/additive:** build path is unchanged (still records `{model,dim}`); the new path
only *reads* `index_meta` and only activates when a model was recorded. Banks with no recorded
model behave exactly as before. The query/document asymmetry (`is_query`) is preserved by routing
through the same per-mode branches.

## 3. Bank rename surface (`original-v1`)

There is **no `rename_bank`** today — only create/activate/duplicate. Renaming the old bank to
`original-v1` needs a small additive function: move `banks/<old>` → `banks/<original-v1>` on disk,
rekey the `banks` dict in `banks.yaml`, and if it was the `active` pointer, repoint `active`.
Guard against: target slug already existing, renaming the legacy root-level default (which lives at
`memory_root`, not under `banks/` — that case must MOVE the legacy tree into `banks/original-v1`
and write a registry, matching the `duplicate_bank` legacy-default handling). Then `create_bank
('claude-chats')` + `activate_bank('claude-chats')` for the fresh empty target. (Renaming can also
be done manually on disk + a hand-edit of `banks.yaml`, but a tested helper is preferable.)

## 4. Import + Sleep already honor the active bank — confirmed

- **Import** is explicitly bank-scoped: `POST /banks/{name}/import` resolves `bank_dir(root, name)`
  and stages into that named bank (validates membership, scaffolds, dedups by content hash). It does
  **not** depend on the active pointer — correct for seeding `claude-chats` directly.
- **Sleep** runs on the ACTIVE bank: `POST /sleep/trigger` → `run(settings, cycle_id)` and
  `sleep_cycle.run` does `memory_path = settings.memory_path` (line 68), which is the computed
  active-bank property. So after `activate_bank('claude-chats')`, the sleep cycle, its
  `SqliteVecIndexer(memory_path)` (line 238), git commits, and claim pipeline all operate on
  `claude-chats`. **No hard-coded default** in either path.

---

## 5. Run sequence (operational)

1. (code) Add per-bank embed resolution (§2) + Swift type parity/fallback (§1) + `rename_bank` (§3).
2. Rename old bank → `original-v1` (preserve its `.git` history + index untouched).
3. `create_bank('claude-chats')`; `POST /banks/claude-chats/import` the Claude export.
4. `activate_bank('claude-chats')`; set env for `openrouter/z-ai/glm-5.2` (consolidation override)
   and the chosen embedding mode for the new bank.
5. `POST /sleep/trigger` → consolidate into `claude-chats` via GLM 5.2 + M5f claim pipeline.
6. Verify: 254 tests still green; `original-v1` graph + history intact; `claude-chats` index
   `index_info().model` matches the env-selected embedding model.

## 6. Test guardrails

- New embed-resolution + rename code must be hermetic (injected fakes; no network/model download).
- Decode tolerance: assert Swift/JSON decode of a legacy entity with the old closed-8 types still
  succeeds; assert an entity carrying `media` (or any future type) does not crash the app decode.
- Keep all existing 254 tests green; add focused tests rather than mutating fixtures of legacy data.
