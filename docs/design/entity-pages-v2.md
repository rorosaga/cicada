# Entity Pages v2 — Richer, Structured, Section-Aware Entity Bodies

Status: design / implementation-ready
Branch: `feat/v2-revamp`
Axis owner: Richer entity pages
Last grounded against code: 2026-06-12

---

## 0. Problem (grounded in the live corpus)

Measured on the live `memory/entities/` (1882 files):

| Metric | Value |
|--------|-------|
| Entity files | 1882 |
| Body word count: median | 49 (P25 = 40, P75 = 60, min 28, max 152) |
| Entities with **any** `## section` | 406 (22%) — all of them `## History`, nothing else |
| Entities with `[[wikilinks]]` in body | 681 (36%) — prose-embedded, no `## Related` block |
| Entities that mention a URL (`http`) | **4** (0.2%) — URLs are effectively never captured |

Root causes in code:

1. `entity_extractor.EXTRACTION_SYSTEM_PROMPT` caps descriptions at 1–8 sentences and produces only a free prose `description` + `history_entries[]`. No structured sections, no links field.
2. `conflict_resolver._compose_entity_body()` only ever emits `description` + `## History`. `_SYNTHESIS_PROMPT` is told the body "has two sections: a description and an optional `## History`" — so even the merge step cannot create or maintain other sections.
3. Conflict resolution (`routers/nudges.py:77`) appends `request.answer` as a raw disconnected paragraph: `body = entity.body + f"\n\n{request.answer}"`.
4. Clarification answer (`routers/clarifications.py:139`) does the same: `body = entity.body.rstrip() + f"\n\n{answer_text}"`. Merge writes a raw `_Resolved…_` note (`:209`).
5. `leann_indexer.index_entities()` embeds only `name + body` (`:236-240`) — type and tags are stored as filterable metadata but never embedded, so "Python tools" can't surface a tool entity whose prose doesn't literally say "Python tool".

This spec replaces the flat body with a **fixed, ordered, section-aware layout (`layout_version: 2`)**, rewrites the extraction + synthesis prompts to populate it richly and reliably, makes all resolution paths section-aware (no more raw appends), and embeds type/tags/aliases into LEANN. It is fully backward-compatible: v1 bodies render and parse unchanged; entities are upgraded lazily the next time Sleep touches them, with an optional one-shot backfill command.

---

## 1. Entity Body v2 — the canonical layout

### 1.1 Section grammar

A v2 body is a sequence of H2 sections in a **fixed canonical order**. Any section may be absent (rendered + parsed as empty). No prose lives above the first H2 — the lead paragraph belongs to `## Summary`.

```markdown
## Summary
<1–3 sentence orientation paragraph. The "what is this and why does the user care" line.>

## Key Facts
- <atomic, machine-readable fact>
- <atomic fact, may contain a [[wikilink]]>

## History
- YYYY-MM-DD: <dated event>
- YYYY-MM-DD: <dated event>

## Related
- [[Entity Name]] — <relationship verb phrase, e.g. "supervised by", "built with">
- [[Entity Name]] — <relationship>

## Links
- [<title>](<url>) — <one-line note on why it matters / when saved>

## Open Questions
- <unresolved point the system or user still needs to settle>
```

Canonical order (the parser/writer enforces this on every write):
`Summary → Key Facts → History → Related → Links → Open Questions`.

### 1.2 Required vs optional sections per entity type

`## Summary` is **required for all 8 types** (it replaces the old free-prose description and is always non-empty after v2 enrichment). Everything else is conditionally required:

| Type | Summary | Key Facts | History | Related | Links | Open Questions |
|----------|:---:|:---:|:---:|:---:|:---:|:---:|
| person | req | rec | opt | rec | opt | opt |
| project | req | **req** | **req** | rec | rec | opt |
| company | req | **req** | rec | rec | rec | opt |
| concept | req | rec | opt | rec | rec | opt |
| tool | req | **req** | opt | rec | **req** | opt |
| deadline | req | **req** | opt | rec | opt | opt |
| skill | req | opt | opt | opt | opt | opt |
| location | req | rec | opt | opt | opt | opt |

- **req** = the prompt must emit it when the source contains any relevant content; the validator flags its total absence as low-quality (used only for backfill prioritization, never to block a write).
- **rec** = emit when content exists.
- **opt** = emit only when the source explicitly supports it.
- `skill` stays deliberately lean: a `skill` is a procedural rule, so `## Summary` (the rule, written as an instruction) is usually the whole page.

Section content rules:
- `## Key Facts` — atomic bullets, one fact each. Contact handle, stack component, role title, price, version, capacity. NOT a re-narration of Summary.
- `## History` — unchanged semantics; dated bullets, chronological, `YYYY-MM-DD: event`. Undated events are allowed as `- <event>` and sort last.
- `## Related` — **first time wikilinks become structured.** Each bullet is `[[Display Name]] — <verb phrase>`. This is the per-entity mirror of `graph_edges.yaml` and the `related` frontmatter list, written in human-readable form so a small LLM can traverse without reading the YAML.
- `## Links` — every external URL the episode attached to this entity. `[title](url) — note`. This is where media-ingestion URLs (see the media-ingestion axis) land; bare URLs the extractor finds in conversation also land here.
- `## Open Questions` — unresolved clarifications and conflict prompts attach here (see §4), so the page itself shows what is still uncertain instead of that living only in a separate inbox file.

### 1.3 Obsidian compatibility

All six sections are plain CommonMark H2 + bullet lists + inline links + `[[wikilinks]]`. No HTML, no custom directives, no front-of-body prose. Obsidian renders this natively, its graph view reads the `[[wikilinks]]` in `## Related`, and its outline panel shows the six headings. No plugin required.

---

## 2. Frontmatter changes (minimal, additive)

Add exactly **two** new optional frontmatter keys. Nothing existing is removed or renamed.

```yaml
layout_version: 2        # int. Absent or 1 ⇒ legacy flat body. 2 ⇒ section layout above.
aliases:                 # list[str], optional. Alternate names/surface forms for this entity.
  - Mongo                # used by LEANN embed text and (future) resolver name matching.
  - the database
```

- `layout_version` is the **single source of truth** for which renderer/parser path to use. It is the migration flag (§5).
- `aliases` is populated opportunistically by extraction/synthesis (`"Mongo" → MongoDB`) and is embedded into LEANN (§6). Optional; absent ⇒ `[]`.
- `related` (existing) stays as the programmatic slug list and remains the graph-edge fallback source. `## Related` bullets are the human/LLM-readable view; a post-write reconciler keeps them in sync (§3.4).

`markdown_parser.write()` already preserves insertion order (`sort_keys=False`), so append `layout_version` and `aliases` to the frontmatter dict where the entity is constructed and they serialize in a stable position.

---

## 3. Extraction & synthesis prompt rewrites

### 3.1 Extraction output schema (Stage 1, `entity_extractor.py`)

Extend the per-entity JSON the LLM returns. New fields are additive; `description` is retained as the `## Summary` source for compatibility, but the model now also emits structured arrays.

```jsonc
{
  "name": "Entity Name",
  "type": "person|project|company|concept|tool|deadline|skill|location",
  "aliases": ["Mongo", "the db"],          // NEW, optional
  "summary": "1-3 sentence orientation.",   // NEW — maps to ## Summary
  "key_facts": ["atomic fact", "..."],      // NEW — maps to ## Key Facts
  "history_entries": [ {"date":"YYYY-MM-DD","event":"..."} ],  // unchanged
  "links": [ {"url":"https://...", "title":"...", "note":"..."} ],  // NEW — maps to ## Links
  "open_questions": ["unresolved point"],   // NEW — maps to ## Open Questions
  "tags": ["..."],
  "confidence": 0.7,
  "description": "<= kept: if model omits summary, fall back to this>"  // back-compat
}
```

Relationships stay exactly as today (`source/target/label`); `## Related` is assembled from resolved relationships + the `related` slug list at write time (§3.4), **not** from a new extraction field — this avoids the model inventing edges that the resolver would have to re-validate.

### 3.2 `EXTRACTION_SYSTEM_PROMPT` rewrite (described)

Rewrite the prompt to:
1. Replace the single `description` instruction block with a **section-oriented instruction set**: ask for `summary`, `key_facts`, `links`, `open_questions` as named fields, plus the existing `history_entries`.
2. Raise richness targets (the old "1–2 sentences" caps were the thinness lever):
   - `summary` length by type stays close to the old per-type sentence guidance (it is the orientation line), BUT
   - `key_facts` is now where density lives — instruct: "Emit every concrete, atomic fact stated about the entity: roles, stack components, dates-as-facts, identifiers, quantities, locations, affiliations. Prefer 3–8 bullets for project/company/tool; 2–5 for person/concept; 1–3 for deadline/location; key_facts may be empty only for skill."
   - For `project`/`company`/`tool`, **require** `key_facts`. For `tool`, **require** `links` when any URL appears in the source.
3. Persist history reliably: keep the existing HISTORY rules but move them under the structured schema and add: "Always emit `history_entries` for project, company, and deadline when any dated event is present; never silently drop a date you saw."
4. Capture URLs: add a LINKS block — "Extract every URL mentioned in connection with this entity into `links[]` with a human title and a one-line note (what it is / why it came up). Never drop a URL into prose only." (This directly fixes the 4/1882 URL-capture gap.)
5. Keep the wikilink instruction but scope it: "Use `[[Entity Name]]` inside `summary` and `key_facts` to reference other entities; do not fabricate links section bullets — those are generated from relationships."

The JSON-shape example at the top of the prompt is updated to the §3.1 schema. `response_format={"type":"json_object"}` is unchanged. No Pydantic validation is added in this axis (out of scope) — defensive `.get(...)` access with defaults is used as today.

### 3.3 `_SYNTHESIS_PROMPT` rewrite (Stage 3 accumulation, `conflict_resolver.py`)

This is the heart of **section-aware accumulation** (§4). Rewrite `_SYNTHESIS_PROMPT` so the model is given:
- the **existing v2 body**, parsed into named sections (passed as labeled blocks, not one blob),
- the **new** `summary / key_facts / history_entries / links / open_questions` from this cycle,
- the entity type + its required/recommended section table row.

Instructions (described):
1. "Output a complete v2 body with the canonical section order: `## Summary, ## Key Facts, ## History, ## Related, ## Links, ## Open Questions`. Omit a section only if it has no content."
2. **Merge per section, never clobber:**
   - `## Summary`: integrate new facts into the existing summary, resolve contradictions by preferring newer info, keep it to its length target. Demote superseded facts into `## History` as a dated bullet (`YYYY-MM-DD: Previously X, now Y`).
   - `## Key Facts`: union of old + new atomic facts; dedupe semantically equivalent bullets; drop a fact only if a newer fact directly contradicts it (and record the change in `## History`).
   - `## History`: append new dated entries in chronological order, dedupe exact lines (existing `_merge_history_entries` behavior, now prompt-enforced).
   - `## Links`: union of old + new links; dedupe by URL; keep the best title/note.
   - `## Open Questions`: union; **remove** any question the new information answers.
3. "Preserve every `[[wikilink]]`, date, name, and number that is not explicitly superseded."
4. "Do not invent `## Related` bullets — leave the `## Related` section exactly as given; it is reconciled separately."
5. Output only the markdown body, no fences, no frontmatter (existing stripping logic retained).

`_synthesize_entity_update()` keeps its signature shape but its inputs expand to carry the parsed section dict and the new structured fields. The fallback (`_fallback_merge_body`) is upgraded to a **section-aware non-LLM merge** (see §3.4) so a synthesis failure still produces a valid v2 body instead of a raw append.

### 3.4 New shared module: `entity_body.py`

Create `api/services/entity_body.py` — a single, dependency-light home for the section grammar so extractor, conflict_resolver, both routers, the backfill script, and LEANN all share one implementation.

```python
# api/services/entity_body.py
CANONICAL_SECTIONS = ["Summary", "Key Facts", "History", "Related", "Links", "Open Questions"]

def parse_sections(body: str) -> dict[str, str]:
    """Split a markdown body into {section_title: section_markdown}.
    Lines before the first H2 are returned under a synthetic '' key (legacy lead prose)."""

def render_sections(sections: dict[str, str]) -> str:
    """Serialize a section dict back to canonical-order markdown, dropping empty sections."""

def compose_body_v2(
    summary: str, key_facts: list[str], history_entries: list[dict],
    related: list[tuple[str, str]],   # (display_name, verb_phrase)
    links: list[dict], open_questions: list[str],
) -> str:
    """Build a fresh v2 body from extracted fields (Stage-1 create path)."""

def merge_sections_fallback(existing: dict[str,str], new_fields: dict) -> dict[str,str]:
    """Non-LLM section-aware merge used when synthesis is unavailable:
    union Key Facts / Links / Open Questions, append+dedupe History,
    keep existing Summary if no new summary, never raw-append a blob."""

def upgrade_legacy_to_v2(body: str, entity_type: str) -> dict[str,str]:
    """Lift a v1 flat body (prose + optional ## History) into the v2 section dict:
    leading prose -> Summary, existing ## History preserved, other sections empty.
    Pure string transform, no LLM. Used by lazy migration and backfill (§5)."""

def render_related(related_slugs: list[str], edges: list[dict], id_to_name: dict) -> str:
    """Build the ## Related bullet block from the `related` frontmatter list +
    graph_edges.yaml labels, so wikilinks stay in sync with the structured edges."""
```

`compose_body_v2` replaces `conflict_resolver._compose_entity_body`; the latter becomes a thin wrapper for back-compat during the transition. `markdown_parser` is untouched (frontmatter parsing is orthogonal to section parsing).

---

## 4. Accumulation semantics — section-aware writes everywhere

The invariant: **once an entity is `layout_version: 2`, no code path may append a raw paragraph to its body.** Every write goes through section merge.

### 4.1 Stage 3 / Stage 5 (sleep) — `conflict_resolver.apply_changes`

`apply_changes` is the single write point (called from `nudge_generator.generate:25`). Changes:

- **create** branch: build the body via `entity_body.compose_body_v2(...)` from the extracted structured fields; set `frontmatter["layout_version"] = 2` and `frontmatter["aliases"] = entity.get("aliases", [])`.
- **update** branch:
  1. Parse existing body. If `layout_version` is absent/1, first run `upgrade_legacy_to_v2()` to lift it into the section dict (lazy migration, §5), and set `layout_version = 2`.
  2. Prefer `change["synthesized_body"]` (LLM section merge). If absent, run `merge_sections_fallback()` then `render_sections()`.
  3. After writing the prose sections, run the **`## Related` reconciler**: `render_related()` rebuilds the Related block from the updated `related` slug list + `graph_edges.yaml`. This keeps the human-readable Related block consistent with the structured edges on every update.
- **decay / decay_nudge / archive** branches: unchanged — they touch only frontmatter confidence/status, never the body, so they are layout-agnostic. (They do NOT trigger lazy upgrade — pure decay should not rewrite the body or burn an LLM call. Upgrade happens only on content updates.)

### 4.2 Conflict resolution (`routers/nudges.py`) — stop raw appends

Replace the raw-append branch (`:77`, `body = entity.body + f"\n\n{request.answer}"`) with a section-aware write:

```python
parsed = markdown_parser.parse(entity_path)
sections = entity_body.parse_sections(parsed.body)
if parsed.frontmatter.get("layout_version", 1) < 2:
    sections = entity_body.upgrade_legacy_to_v2(parsed.body, parsed.frontmatter.get("type","concept"))
# Conflict answer integrates into Summary + records the resolution in History.
sections = _apply_conflict_answer(sections, request, source_date)  # helper in nudges.py
parsed.frontmatter["layout_version"] = 2
parsed.frontmatter["version"] += 1
markdown_parser.write(entity_path, parsed.frontmatter,
                      entity_body.render_sections(sections))
```

`_apply_conflict_answer` semantics: if the user picked an option ("Postgres" over "SQLite"), rewrite the relevant `## Summary`/`## Key Facts` to the chosen state and add a `## History` bullet `YYYY-MM-DD: Resolved conflict — chose <option> over <other>`. If "both are true (different contexts)", keep both as `## Key Facts` bullets with the contextual qualifier and add a History note. Free-text answers integrate into `## Summary` and drop a History bullet. **No raw paragraph append.** Cost: zero extra LLM calls for option-pick (pure string ops); free-text answer may optionally route through `_synthesize_entity_update` for clean integration (one call) — acceptable since it is user-initiated and rare.

### 4.3 Clarification resolution (`routers/clarifications.py`) — section-aware

- **answer** branch (`:139`): same pattern as §4.2 — integrate `answer_text` into `## Summary`, record a History bullet, never raw-append. The fresh-entity create path (`:145`) builds a v2 body via `compose_body_v2(summary=answer_text, ...)` and sets `layout_version: 2`.
- **merge** branch (`:209`): instead of appending `_Resolved ambiguous mention…_` to the body, add a `## History` bullet `YYYY-MM-DD: Merged mention '<mention>' into this entity` to the target's section dict, and add the mention to the target's `aliases` frontmatter list (so future LEANN/resolver matching benefits). Set `layout_version: 2` on the target.

### 4.4 Why this prevents the historical "disconnected paragraphs" failure

Today both routers and the fallback merge bolt new text onto the end of the body. Over many resolutions a page becomes a stack of orphan paragraphs (called out in findings AREA "Sleep-Cycle" [MEDIUM]). With v2, the body is always a fixed set of sections reconstructed from a parsed dict, so there is no "end of body" to append to — new content can only enter a named section, deduped against what is already there.

---

## 5. Migration — lazy enrichment + optional backfill

**No bulk rewrite at deploy. No data loss. Two complementary paths.**

### 5.1 Lazy enrichment (default, zero added cost beyond normal Sleep)

- v1 entities (no `layout_version`, or `=1`) are read and rendered exactly as today — the parser treats a flat body as `{"Summary": <leading prose>, "History": <existing ## History>}` via `upgrade_legacy_to_v2`, so the API and app see structured sections immediately on read, even before any rewrite.
- The **file on disk** is upgraded to v2 only when Sleep next *updates* that entity (§4.1 update branch) — i.e. when the entity is mentioned again. At that point the structural lift is a free string transform and the LLM synthesis call (which would happen anyway for an update) produces the enriched sections. So active entities migrate naturally; dormant ones stay v1 on disk but still render as v2 on read.
- This means: **the live `memory/` works untouched on day one**, and the graph self-heals toward v2 as the user keeps using it.

### 5.2 Optional one-shot backfill command

For users who want every page enriched now (and for the thesis Results section), add a backfill script mirroring the `benchmarks/` runner + Makefile conventions.

Files:
- `scripts/backfill_entity_pages.py` (new) — async, uses `api/.venv`, loads `api/.env` via the same bootstrap pattern as `benchmarks/_bootstrap.py`.
- Makefile target.

Behavior (two tiers):
- `--mode structural` (default, **free, no LLM**): apply `upgrade_legacy_to_v2()` + `render_sections()` + `render_related()` to every v1 entity, set `layout_version: 2`. Pure string transform. Reorders existing content into the section grammar and materializes `## Related` from `related`+`graph_edges.yaml`. This alone fixes section structure and wikilink traversability for all 1882 entities at zero token cost.
- `--mode enrich` (opt-in, **LLM, costs tokens**): for each v1 entity, run a single synthesis-style "enrich existing page into rich v2 sections" call (re-derive Key Facts from Summary + source episodes, fill Open Questions from any pending clarification). Concurrency-bounded by a semaphore (reuse `MAX_CONCURRENCY = 10`).

Safety rails (mirror `benchmarks` rules): `--memory` flag, refuses to run on a path whose name doesn't end in `memory` unless `--force`; writes are git-committed in batches with a structured message `Backfill: entity pages -> layout_version 2 (mode: <mode>)`; `--dry-run` prints a per-entity plan without writing; `--limit N` for smoke tests.

```makefile
backfill-structural:    # free, no LLM
	$(PYTHON) -m scripts.backfill_entity_pages --memory $(MEMORY) --mode structural
backfill-enrich:        # costs tokens — see estimate below
	$(PYTHON) -m scripts.backfill_entity_pages --memory $(MEMORY) --mode enrich \
		$(if $(LIMIT),--limit $(LIMIT),)
backfill-smoke:
	$(MAKE) backfill-enrich LIMIT=10
```

### 5.3 Cost estimate for `--mode enrich` on 1882 entities

One synthesis call per entity. Per-call token budget (grounded in current prompt sizes): existing body ≤ 6000 chars (~1.5k tok) + structured new fields + instructions ≈ **~2.0k input tokens**, output a richer body ≈ **~0.5k output tokens**. Total ≈ 2.5k tokens/entity → ~4.7M tokens for 1882 entities.

| Default model (`gpt-5.4-mini`, the configured `litellm_model`) | ~$0.15/1M in, ~$0.60/1M out (current mini-tier pricing) | input 3.8M × $0.15 + output 0.9M × $0.60 ≈ **$0.57 + $0.54 ≈ ~$1.1 total** |
| Disambiguation-tier (`gpt-5.4-nano`) | cheaper still | **< $0.50 total** |

So a full LLM enrich backfill of the entire corpus is **roughly $1**, a one-time cost. The structural mode is free. Recommend: ship structural backfill as the documented default; treat `enrich` as optional. The README/thesis should report the structural path (deterministic, reproducible, no API spend) as the canonical migration.

Note: enrich backfill does **not** re-run LEANN embedding per entity — it only rewrites markdown. A single `make rebuild-episodes`-style entity index rebuild afterward (one batched embedding pass, the existing `index_entities()` cost) re-embeds the enriched bodies. That embedding cost is the existing per-Sleep entity-index cost, unchanged.

---

## 6. LEANN impact — embed type, tags, aliases, and section structure

Change `leann_indexer.index_entities()` (`:236-240`) so the embedded text is richer and type/tag-aware, fixing the "type/tags not embedded" gap (findings AREA "Storage" [MEDIUM]).

New embed-text composition (described):
```
<name> (<type>)
aliases: <comma-joined aliases>          # if any
tags: <comma-joined tags>                # if any
<v2 body, sections in canonical order>
```

Rationale: prepending `type`, `aliases`, and `tags` makes a query like "Python tools" match a `tool`-type entity even when its prose never says "Python tool"; aliases make "Mongo" match the `MongoDB` page. The body is already the v2 section text (after lazy/backfill migration), so `## Key Facts` and `## Links` content — the new dense material — gets embedded, directly improving recall quality (which the findings flagged as degraded by thin bodies).

Metadata stays as-is plus add `"layout_version"` and `"aliases"` to the `metadata={...}` dict so downstream filtering/Bookworm can use them. No index-format change, no rebuild-mechanics change — only the `text_parts` assembly and metadata dict are edited. The existing batched-embedding build path is untouched.

The `EntityResponse.markdown_content` field (returned by `GET /entities/{id}`) is unchanged in shape — it still returns the body string — but that string is now the v2 sectioned body, which the SwiftUI/d3 renderers can split on H2 for collapsible sections (handled by the app axis). Add two fields to `EntityResponse` so the app doesn't have to re-parse:

```python
class EntityResponse(CamelModel):
    ...
    layout_version: int = 1          # NEW
    aliases: list[str] = []          # NEW
    sections: dict[str, str] = {}    # NEW — pre-parsed {title: markdown}, via entity_body.parse_sections
```

`routers/entities.py:get_entity` populates these: `layout_version = fm.get("layout_version", 1)`, `aliases = fm.get("aliases", [])`, `sections = entity_body.parse_sections(parsed.body)` (lifting v1 on the fly so the app always receives sections). This is additive — existing `markdownContent` consumers keep working.

---

## 7. Files to create / modify

| Path | Action | Note |
|------|--------|------|
| `api/services/entity_body.py` | create | Section grammar: parse/render/compose/merge/upgrade/related. Single source of truth. |
| `api/services/entity_extractor.py` | modify | Rewrite `EXTRACTION_SYSTEM_PROMPT` + JSON schema (summary/key_facts/links/open_questions/aliases); raise richness targets; mandate URL capture. |
| `api/services/conflict_resolver.py` | modify | Rewrite `_SYNTHESIS_PROMPT` (section-aware merge); route `_compose_entity_body` → `entity_body.compose_body_v2`; upgrade `_fallback_merge_body` → section-aware; create/update branches set `layout_version`/`aliases` + run Related reconciler + lazy-upgrade v1 on update. |
| `api/routers/nudges.py` | modify | Replace raw-append conflict resolution with `_apply_conflict_answer` section write. |
| `api/routers/clarifications.py` | modify | Section-aware answer/merge writes; v2 create path; merge adds alias + History bullet. |
| `api/routers/entities.py` | modify | Add `layout_version`, `aliases`, `sections` to response; lift v1 on read. |
| `api/models/schemas.py` | modify | Add `layout_version`, `aliases`, `sections` to `EntityResponse`. |
| `api/services/leann_indexer.py` | modify | Enrich `index_entities()` embed text (type/aliases/tags + v2 body) + metadata. |
| `scripts/__init__.py` | create | Package marker. |
| `scripts/backfill_entity_pages.py` | create | structural (free) + enrich (LLM) backfill, with safety rails. |
| `Makefile` | modify | Add `backfill-structural`, `backfill-enrich`, `backfill-smoke`. |
| `docs/design/entity-pages-v2.md` | create | This spec. |

---

## 8. Implementation steps (ordered, single-developer, days)

1. **Create `entity_body.py`** with `CANONICAL_SECTIONS`, `parse_sections`, `render_sections`, `compose_body_v2`, `merge_sections_fallback`, `upgrade_legacy_to_v2`, `render_related`. Unit-test parse↔render round-trips on a v1 flat body, a `## History`-only body, and a full v2 body. (No LLM — pure string logic.)
2. **Wire `EntityResponse` + `routers/entities.py`** to emit `layout_version`/`aliases`/`sections` (lifting v1 on read). Verify `GET /entities/{id}` returns sections for an existing v1 entity. This is the lowest-risk, highest-immediate-value change (app gets structure for free, no disk writes).
3. **Enrich `leann_indexer.index_entities()`** embed text + metadata. (Independent of writes; safe to land early.)
4. **Rewrite `_SYNTHESIS_PROMPT`** and `_synthesize_entity_update` inputs to be section-aware; upgrade `_fallback_merge_body` to call `merge_sections_fallback`. Route `_compose_entity_body` → `compose_body_v2`.
5. **Update `apply_changes`** create/update branches: set `layout_version`/`aliases`, lazy-upgrade v1 on update, run `render_related` reconciler.
6. **Rewrite `EXTRACTION_SYSTEM_PROMPT`** + Stage-1 JSON schema (summary/key_facts/links/open_questions/aliases) and richer targets + URL-capture mandate. Smoke-test a single-episode extraction.
7. **Make resolution paths section-aware**: `nudges.py` `_apply_conflict_answer`; `clarifications.py` answer/merge/create. Verify no path raw-appends.
8. **Write `scripts/backfill_entity_pages.py`** (structural + enrich, safety rails, dry-run/limit) and add Makefile targets. Run `make backfill-structural --dry-run` then for real on a copy.
9. **End-to-end verify**: fresh sleep cycle in a `/tmp` workspace seeded from `memory/episodes` produces v2 bodies; an existing v1 entity touched by that cycle upgrades on disk; `GET /entities/{id}` shows sections; LEANN entity search returns enriched matches. Confirm v1 entities never touched still parse and render.

---

## 9. Backward-compatibility guarantees

- v1 entities (1882 on disk) work unchanged on read — no field is removed, body parsing degrades gracefully (leading prose → Summary).
- No bulk migration is forced; lazy upgrade is opt-out-by-inaction, backfill is opt-in.
- Frontmatter changes are two additive optional keys; absent ⇒ legacy behavior.
- 39 nudges / 33 clarifications: their files are untouched by this axis; the only change is that *resolving* them now writes section-aware bodies instead of raw appends — which is strictly an improvement and writes only to entity files, not to the inbox files.
- `graph_edges.yaml` and `related` remain the edge sources; `## Related` is a derived, reconciled view, never a competing source of truth.
