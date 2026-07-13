# M6/M7 — Memory Banks + Chat-Export Import (design note)

Status: design only (audit done on `feat/memory-evolution`, 126 tests green). Build agents follow
this. **No file relocation** of the existing memory dir — the legacy dir becomes the "default" bank
*in place* via a registry pointer, not by moving bytes.

---

## 1. Audit result: memory_path resolution is SAFE to make dynamic

Every read of the memory path in the codebase goes through **one** of two channels, and **nothing
ever assigns `settings.memory_path` as a stored field** (the only `self.memory_path = ...` writes are
on unrelated service objects — `VectorIndexer`, `ClarificationManager`, `_FakeSettings` — that take a
path *argument*, never the `Settings` instance).

Two channels:

1. **`settings.memory_path`** read off a `Settings` instance. The instance is always obtained via
   `Depends(get_settings)` (routers) or threaded through as a function arg (`sleep_cycle.run(settings,…)`,
   `inbox_service._resolve_*(…, settings)`, `entity_resolver.resolve(…, settings)`, hub_builder,
   `vector_index._cli` via `get_settings()`, `ask_service` via `get_settings()`). `main.py` lifespan also
   reads `settings.memory_path` directly.
2. **A plain `memory_path: Path` argument** passed *into* a service (`SqliteVecIndexer(memory_path)`,
   `git_service.*(memory_path)`, `graph_builder`, `media_ingestor`, `predicates`, `claim_seeder`, …).
   These never see `Settings` at all — they get whatever path the caller resolved.

**Therefore:** if `settings.memory_path` resolves to the active bank, channel (1) follows automatically,
and channel (2) follows because every channel-(2) caller derived its path from a channel-(1) read. There
is exactly one place that turns "config" into "path" and we control it.

### Chosen approach: `memory_path` becomes a computed property on `Settings`

Replace the plain field with a private base field + a resolving property:

```python
class Settings(BaseSettings):
    # was: memory_path: Path = Path.home() / "cicada" / "memory"
    memory_root: Path = Path.home() / "cicada" / "memory"   # CICADA_MEMORY_ROOT (legacy: CICADA_MEMORY_PATH alias)

    @property
    def memory_path(self) -> Path:
        return resolve_active_bank_path(self.memory_root)
```

- `memory_root` is the **container** for banks (`<root>/banks/<name>/…`) plus the registry file
  `<root>/banks.yaml` and, for legacy, the in-place files that already live at `<root>` itself.
- `resolve_active_bank_path()` (in a new `api/services/bank_registry.py`) reads `<root>/banks.yaml`,
  finds the `active` pointer, and returns the bank's directory. **Legacy fallback:** if `banks.yaml`
  is missing OR the active bank is the synthetic `default`, it returns `memory_root` **unchanged** —
  i.e. the existing `<root>/entities`, `<root>/episodes`, `<root>/.git` are the default bank, untouched.

#### Landmines found (all handled by this approach, none blocking)

- **`@lru_cache` on `get_settings()`**: a cached `Settings` instance is fine *because `memory_path` is now
  a property recomputed on every access* — switching banks mutates `banks.yaml`, not the `Settings`
  object, so no cache invalidation is needed for path resolution. (Embedding/LLM fields are unaffected.)
  The one nuance: `resolve_active_bank_path` reads `banks.yaml` on **every** `.memory_path` access — keep
  it cheap (small YAML, no per-call disk cost concern at personal scale; optionally mtime-cache later).
- **Tests use `CICADA_MEMORY_PATH` env + `config.get_settings.cache_clear()`** (`test_sources.py:304`).
  Keep `CICADA_MEMORY_PATH` working: make the new field accept that env name (pydantic `validation_alias`
  / `AliasChoices("CICADA_MEMORY_PATH","CICADA_MEMORY_ROOT")`, or simpler: keep the field **named**
  `memory_path` as the *root* and expose the resolved value under a new name). **DECISION:** keep the
  field literally named `memory_path` (so `CICADA_MEMORY_PATH` + all 126 tests keep passing verbatim) and
  add a SEPARATE resolving accessor `active_memory_path`/property only where banks are active. To avoid
  touching 40+ call sites, instead make `memory_path` itself the property and rename the raw field to
  `memory_root` **with `validation_alias=AliasChoices("CICADA_MEMORY_PATH","CICADA_MEMORY_ROOT")`** so the
  test env var still populates the root. When `banks.yaml` is absent (the test case — tmp dirs never have
  one) the property returns the root unchanged → **all existing tests see identical behavior**. This is
  the single most important compatibility guarantee; build agents MUST verify `pytest api/tests -q` stays
  126 green after the property swap and BEFORE adding any bank logic.
- **`_FakeSettings` in tests** only sets `.memory_path` as a plain attr — a property on the *real*
  `Settings` does not affect the fake. Safe.
- **`main.py` lifespan** mkdirs `settings.memory_path / subdir` and `git init`s it. With the legacy
  fallback this still targets `<root>` exactly as today. When a real (non-legacy) bank is active it
  targets that bank dir — also correct (each bank is self-contained: own `entities/…/.git`).

---

## 2. Banks registry + active pointer + legacy mapping

### On-disk layout (no relocation)

```
<memory_root>/                     ← CICADA_MEMORY_PATH (unchanged env)
├── banks.yaml                     ← NEW registry + active pointer
├── entities/  episodes/  .git ...  ← the LEGACY "default" bank, IN PLACE
└── banks/                         ← NEW container for all non-legacy banks
    └── <slug>/                    ← one self-contained memory dir per bank
        ├── entities/ episodes/ inbox/ ... (.git per bank)
```

`banks.yaml`:
```yaml
active: default
banks:
  default:
    legacy: true          # ← lives at <root> directly, NOT under banks/
    created: 2026-04-08
    description: "Primary memory"
  claude-import:
    legacy: false         # ← lives at <root>/banks/claude-import
    created: 2026-06-17
    description: "Claude conversation export"
```

`resolve_active_bank_path(root)`:
1. If `root/banks.yaml` missing → return `root` (legacy fallback; first run / tests).
2. Load it; `name = active`. If the bank record has `legacy: true` → return `root`.
3. Else return `root / "banks" / name`.

### Bank lifecycle (the API contract)

- **`GET /banks`** → list every bank with `name, active(bool), entityCount, episodeCount, createdAt,
  description`, plus top-level `active`. Counts = `len(glob("entities/*.md"))` / `episodes/*.md` on each
  bank's resolved dir. (Cheap; personal scale.)
- **`POST /banks` `{name, description?}`** → slugify name (reuse `id_utils.sanitize_id`), reject if exists,
  create `root/banks/<slug>/` with the SAME subdir scaffold as `main.py` lifespan (factor that scaffold
  into a shared `bank_registry.scaffold_bank(path)` and call it from BOTH lifespan-legacy-path and here),
  `git init` it, add to `banks.yaml` with `legacy:false`. Does NOT activate.
- **`POST /banks/{name}/activate`** → set `active: name` in `banks.yaml`. Because `memory_path` is a
  property, the next request resolves to the new bank with no restart. (Vector index: each bank has its
  own `vector_index.db`; no cross-bank bleed.)
- **`POST /banks/{name}/duplicate` `{newName}`** → "save current under a name": copy the *named* bank's
  dir tree to a new `banks/<newSlug>/`. Use `shutil.copytree` EXCLUDING `.git` (start a fresh `git init`
  in the copy so version history doesn't fork-share), register it `legacy:false`. Source may be the legacy
  bank (copytree from `<root>` selecting only the memory subdirs + top-level files, not `banks/` itself).

New module `api/services/bank_registry.py` owns: `load_registry`, `save_registry`, `resolve_active_bank_path`,
`bank_dir(root,name)`, `scaffold_bank`, `list_banks`, `create_bank`, `activate_bank`, `duplicate_bank`. New
router `api/routers/banks.py` (registered in `main.py`). All bank-mutating ops take `memory_root` (=
`settings.memory_root`, the raw field), NOT the resolved `memory_path`, so they can see/manage all banks.

---

## 3. Import pipeline (reuse conversations + media seams)

**`POST /banks/{name}/import`** (multipart `file`) — stage parsed conversations as DATED episodes into
bank `{name}` (NOT necessarily the active bank). Returns
`{episodesStaged, duplicatesSkipped, dateRange:{from,to}, format}`.

### Reuse, do not reinvent

`routers/conversations.py` already has the full parse+stage machinery. The import endpoint REUSES it:
- **Format auto-detect**: extend the existing `detect_source()` + the `.html`/`.json` branch in
  `upload_conversation`. Add: (a) **zip** handling — unzip in a tmp dir, locate `conversations.json`
  (Claude), ChatGPT `conversations.json`, or `Takeout/My Activity/Gemini Apps/MyActivity.html` (Gemini),
  recurse into the contained file; (b) **Gemini MyActivity.html** parser. Map detected → `format` field
  in the response (`claude` | `chatgpt` | `gemini` | `claude_memories` | `claude_projects`).
- **Parsers already present & verified**: `parse_anthropic_conversations` (Claude `conversations.json`),
  `parse_chatgpt_json`, `parse_anthropic_memories`, `parse_anthropic_projects`. Reuse verbatim.
- **Staging**: reuse `_stage_episodes(episodes, bank_dir/"episodes")` — it already does content-hash
  dedup (`duplicatesSkipped`) and chronological `ep_YYYY-MM-DD_NNN` IDs. Target the **bank's** episodes
  dir: `bank_registry.bank_dir(settings.memory_root, name) / "episodes"` (scaffold the bank first if the
  caller created an empty one). This is the media_ingestor staging pattern too (`memory_path/"episodes"`).
- **`dateRange`**: min/max of `episode["original_date"]` across staged (and skipped-but-parsed) episodes.

### Claude `created_at` → backdated episode `timestamp` (the exact mapping)

This is the load-bearing detail for "DATED episodes". It ALREADY works correctly in
`parse_anthropic_conversations` + `_stage_episodes`; the import endpoint just routes through it:

1. Each Claude conversation has `created_at` (ISO-8601 µs, e.g. `2026-02-24T12:39:02.701295Z`).
   `parse_anthropic_conversations` sets `episode["timestamp"] = conv["created_at"]` (falling back to the
   first message's `created_at` if the conv lacks one) and `episode["original_date"] = _extract_date(ts)`
   = `ts[:10]` → `2026-02-24`.
2. `_stage_episodes` builds the ID from `original_date`: `ep_2026-02-24_NNN` (NNN = per-date sequence,
   continuing existing counts in that bank's episodes dir), and writes frontmatter
   `timestamp: <conv created_at, verbatim>`, `processed: false`, `content_hash: sha256(...)[:12]`,
   `source: "claude"`, `title: conv name`.
   → Episodes are **backdated to when the conversation actually happened**, so the Sleep cycle's temporal
   logic (decay, ordering) sees true chronology, not import time. Messages within a conv are sorted by
   their own `created_at` before joining. Gemini/ChatGPT follow the same `timestamp`→`original_date`→ID
   path (ChatGPT unix `create_time`→ISO; Gemini activity timestamps parsed from the HTML entries).
3. Episodes with no timestamp (e.g. `claude_memories`) fall back to `datetime.now()` for ID/timestamp —
   acceptable for seed-memory entries that have no real date.

### One required guard

`_stage_episodes` dedups only **within one episodes dir** (the target bank). That is exactly what we want:
importing the same export into two different banks should populate both. Cross-bank dedup is NOT desired.

---

## 4. Build order for agents (keep 126 green at each step)

1. Swap `memory_path` field → `memory_root` field (`validation_alias` keeps `CICADA_MEMORY_PATH`) +
   `memory_path` property returning `resolve_active_bank_path(memory_root)`. Add `bank_registry.py` with
   the legacy-fallback resolver. **Run pytest — MUST stay 126 green** (no `banks.yaml` exists in any test
   tmp dir, so the property returns the root unchanged).
2. Factor the lifespan scaffold into `bank_registry.scaffold_bank`; call from lifespan (legacy path).
3. Add registry CRUD + `routers/banks.py` (`GET/POST /banks`, activate, duplicate). Tests with a tmp root.
4. Add `POST /banks/{name}/import` reusing `conversations.py` parsers + `_stage_episodes`; add zip + Gemini
   HTML detection/parsing. Tests with the fixture exports (use SMALL synthetic fixtures, never commit real
   personal exports — mirror the benchmarks privacy rule).
