# Hubs & Small-LLM Traversal (v2)

**Axis owner:** Hub tier + small-LLM traversability
**Branch:** `feat/v2-revamp`
**Status:** implementation-ready spec
**Author context:** single dev, days not weeks. Live memory dir: 1882 entities, 39 nudges, 33 clarifications, 117 episodes, `graph_edges.yaml` (~339KB). Never lose data.

---

## 0. Problem statement & design thesis

A small/cheap LLM (Haiku-class, 8B local) cannot semantically scan 1882 flat markdown leaves. Today the graph is flat: every entity is a peer; the only navigational signal is node radius. 681 entity bodies contain `[[wikilinks]]` that **no Python code parses** — they are decorative. Edges live in two places (`graph_edges.yaml` canonical, `related` frontmatter fallback) with no declared ownership. There is no map-of-content; an agent landing in `memory/` has no entry point.

This spec adds a **hub tier** and a **deterministic, cheap traversal path** so a small LLM can navigate:

```
_index.md  (1 file, ~3KB)         "where am I, what topics exist"
   ↓  pick a hub
hubs/<hub>.md  (1 file, ~2-5KB)   "members of this topic, one line each"
   ↓  pick a member entity_id
entities/<id>.md  (1 file)        "the entity page (richer in v2)"
   ↓  follow wikilinks / related / source_episodes
episodes/<ep>.md  (1 file)        "the raw conversation excerpt"
```

Each level is a **single small file read** — no directory scan, no LEANN call required for structural traversal. LEANN remains the *fuzzy* entry point (`cicada_recall`), and now emits **structured next-hop hints** so even a model that ignores prose can act.

**Key principle:** hubs are **persisted markdown files**, not render-time virtual nodes. The owner's goal #2 ("small/cheap LLMs must traverse the graph via filesystem/MCP without the API") requires real files an LLM can `cat`. A virtual-node-only approach (computed in `graph_builder`) would be invisible to the MCP/filesystem path and is rejected.

---

## 1. File-system layout (new + changed)

```
memory/
├── _index.md                 ← NEW. root map-of-content. single entry point.
├── hubs/                      ← NEW. persisted hub pages, regenerated each sleep cycle.
│   ├── people.md             ←   type hub (one per non-empty entity type)
│   ├── projects.md
│   ├── tools.md
│   ├── concepts.md
│   ├── places.md             ←   "location" type → friendly name "Places"
│   ├── companies.md
│   ├── skills.md
│   ├── media.md              ←   reserved type hub for media entities (goal 6; empty until media axis lands)
│   └── topic-<slug>.md       ←   tag-cluster hubs (entities sharing a frequent tag)
├── entities/                  ← unchanged location; bodies get richer (other axis), hubs read them
├── graph_edges.yaml           ← CANONICAL edge source (see §4). gains a `mentions` edge wave.
├── nudges/  clarifications/   ← unchanged by this axis (unified-inbox axis owns these)
└── leann/                     ← unchanged
```

Hub files live under `memory/hubs/`, **not** `memory/entities/`. Rationale: keeps `entities/*.md` a clean set of leaf entities for `_load_existing_entities`, `leann_indexer.index_entities`, decay, and resolution. Hubs are derived artifacts (regenerated every cycle, never decayed, never extracted-from). Keeping them out of `entities/` means **zero changes** to the resolution / decay / LEANN-entity pipeline and no risk of a hub being treated as a leaf entity to merge or decay.

---

## 2. Hub page schema

### 2.1 Type hubs (one per non-empty entity type)

The 8 closed entity types map to 8 type hubs with friendly display names:

| entity `type` | hub file | hub `name` |
|---|---|---|
| person | `hubs/people.md` | People & Contacts |
| project | `hubs/projects.md` | Projects |
| company | `hubs/companies.md` | Companies |
| concept | `hubs/concepts.md` | Concepts |
| tool | `hubs/tools.md` | Tools |
| deadline | `hubs/deadlines.md` | Deadlines |
| skill | `hubs/skills.md` | Skills |
| location | `hubs/places.md` | Places |
| (media, future) | `hubs/media.md` | Media |

A type hub is generated only if ≥1 **non-archived** entity of that type exists. Archived/dropped entities are excluded from hub member lists (they stay on disk, just not surfaced).

### 2.2 Tag-cluster hubs (cross-cutting topic hubs)

A tag-cluster hub is generated for each tag that is shared by **≥ `hub_tag_min_members` (default 5)** non-archived entities, capped at **`hub_tag_max_hubs` (default 30)** hubs (highest-membership tags win). Tags are normalized via `sanitize_id` for the filename: `topic-<sanitize_id(tag)>.md`. The hub `name` is the original tag text title-cased.

Tag-cluster hubs give cross-type topic anchors (e.g. a `robotics` tag spanning project + tool + person entities) that type hubs cannot express. This is the "intermediary/abstract HUB topic" the owner asked for (goal #4) beyond plain type buckets.

### 2.3 Frontmatter (both hub kinds)

```yaml
---
type: hub               # NEW sentinel value. NOT added to EntityType enum (see §6). Lives only in hub files.
hub_kind: type | tag    # discriminator
status: active          # always active; hubs are never decayed
generated: '2026-06-12' # ISO date this hub was last (re)written by a sleep cycle
member_count: 138       # len(members)
source_type: person     # present when hub_kind == type (the entity type this hub aggregates)
source_tag: robotics    # present when hub_kind == tag (original tag text)
members:                # ordered list, highest-confidence first, capped at hub_member_cap (default 150)
  - id: figure-ai
    name: Figure AI
    type: company
    confidence: 0.82
    summary: Robotics company building humanoid robots; referenced re humanoid actuation.
  - id: ...
version: 1
---
```

`members[].summary` is a **one-line** (≤140 char) derived blurb — first sentence of the entity body, stripped of wikilinks and markdown, truncated. It is generated **without an LLM call** (pure string slice) to keep hub regeneration free and fast across all entities. `members` is capped at `hub_member_cap` (default 150) ordered by confidence desc so a hub file stays a cheap read even for the 672-member `concepts` hub; the body notes overflow ("… and N more lower-confidence members; query LEANN to find them").

### 2.4 Body (both hub kinds)

```markdown
## People & Contacts

138 people Cicada is tracking. Highest-confidence first. Click a name to open the entity page,
or read `memory/entities/<id>.md` directly.

- [[Figure AI]] (company, 0.82) — Robotics company building humanoid robots…
- [[Rodrigo]] (person, 0.91) — …
- …

> 138 members shown of 138. Generated 2026-06-12 by sleep cycle.
```

The body wikilinks every member by **display name** so a reading LLM can hop, and the frontmatter `members[].id` gives a small LLM the **exact filename** to read next without name→id resolution. Both representations are intentional: prose for humans/large models, structured `members` for small models and the API.

---

## 3. Root `_index.md` (map-of-content)

Single file at `memory/_index.md`, regenerated every sleep cycle (and creatable on demand, see §7). It is the cold-start landing page for any agent that lands in the memory dir.

### 3.1 Frontmatter

```yaml
---
type: index
generated: '2026-06-12'
entity_count: 1882
active_entity_count: 1654
episode_count: 117
edge_count: 4571
hub_count: 38
pending_inbox_count: 72        # nudges + clarifications (read live; harmless if unified-inbox axis renames)
---
```

### 3.2 Body

```markdown
# Cicada Memory — Map of Content

This is a personal knowledge graph. To find something:
1. Skim the hubs below and pick the most relevant topic.
2. Read that hub file in `memory/hubs/`. It lists member entities with one-line summaries.
3. Open the member entity at `memory/entities/<id>.md`.
4. Follow its wikilinks, `related`, or `source_episodes` for more depth.
For fuzzy/semantic search, call the `cicada_recall` MCP tool instead of scanning.

## Type hubs
- [[People & Contacts]] — `hubs/people.md` (138 members)
- [[Projects]] — `hubs/projects.md` (305 members)
- [[Tools]] — `hubs/tools.md` (375 members)
- [[Concepts]] — `hubs/concepts.md` (672 members)
- [[Companies]] — `hubs/companies.md` (157 members)
- [[Places]] — `hubs/places.md` (100 members)
- [[Skills]] — `hubs/skills.md` (95 members)
- [[Deadlines]] — `hubs/deadlines.md` (40 members)

## Topic hubs (cross-cutting)
- [[Robotics]] — `hubs/topic-robotics.md` (23 members)
- … (up to hub_tag_max_hubs, by membership)

## Stats
- 1882 entities (1654 active), 117 episodes, 4571 edges, 38 hubs.
- Last sleep cycle: 2026-06-12.
```

The instruction block at the top is a literal traversal protocol the small LLM can follow verbatim. This is the cheapest possible "how do I use this memory" primer.

---

## 4. Wikilink resolution & the dual-edge-source decision

### 4.1 Canonical vs derived (the decision)

**Declare `graph_edges.yaml` the single canonical edge source.** The `related` frontmatter field becomes a **derived denormalization** of `graph_edges.yaml`, used only for (a) human/Obsidian readability and (b) the MCP one-hop traversal that already reads `related`. The graph builder must **stop** falling back to `related` as an independent source — it always reads `graph_edges.yaml`.

Rationale: `graph_edges.yaml` carries **labels and direction** (`mentions`, `works at`, `depends on`); `related` is an unlabeled bidirectional slug list that loses information. One labeled source of truth + one lossy derived view is the correct shape. `nudge_generator._update_related_fields` already writes `related` from the same relationship list, so it stays a pure projection.

### 4.2 New sleep-cycle step: materialize wikilinks as `mentions` edges

Add **Stage 5.5 — wikilink edge materialization** (runs inside `nudge_generator.generate`, after `apply_changes` and `_write_graph_edges`, before commit). It is a new function `materialize_wikilink_edges(memory_path)` in a new service module `api/services/wikilink_resolver.py`:

1. Build a **name→id resolution map** once:
   - For every `entities/*.md`, read frontmatter `name`. Map `name.lower() → filepath.stem`.
   - Also map `sanitize_id(name) → filepath.stem` and `filepath.stem → filepath.stem` (covers both the clean and legacy-filename cases; see §8).
2. For every `entities/*.md` body, regex-extract `[[Display Name]]` occurrences: `re.findall(r"\[\[([^\]]+)\]\]", body)`. Strip any `|alias` (`[[Real Name|alias]]` → `Real Name`).
3. Resolve each display name to a target id via the map: try `display.lower()`, then `sanitize_id(display)`, then `display.lower().replace(' ', '-')`. Skip unresolved (dangling) links — do **not** invent target nodes.
4. Emit edge `{source: <this entity id>, target: <resolved id>, label: "mentions"}` for each resolved, non-self link. Dedup.
5. Merge these `mentions` edges into `graph_edges.yaml` using the **existing** `_write_graph_edges` dedup logic (`(source, target, label.lower())` key). Existing `mentions` edges from prior cycles are naturally deduped.

This is **idempotent**: re-running produces the same set. It is **additive**: it never deletes relationship edges, only adds `mentions` edges. After the first run, the 681 bodies' worth of links become real, queryable, labeled edges and the graph stops ignoring them.

### 4.3 Why `mentions` and not reusing `related to`

`mentions` is a distinct, weaker edge label so the graph renderer / API can style it differently (thin, low-opacity) from explicit extracted relationships (`works at`, etc.). It also lets a consumer filter "structural mention links" out of "semantic relationship links" when needed.

---

## 5. Hub generation step (sleep cycle)

Add **Stage 5.6 — hub & index generation**, a new service `api/services/hub_builder.py`, invoked from `nudge_generator.generate` **after** wikilink materialization (so member edges are current). One pure function:

```python
def regenerate_hubs_and_index(memory_path: Path, settings: Settings) -> dict:
    """Rewrite memory/hubs/*.md and memory/_index.md from current entity files.
    Returns {"hub_files": [...], "index_file": "_index.md", "hub_count": N}.
    Fully deterministic, no LLM calls. Idempotent."""
```

Algorithm:
1. Load all `entities/*.md` (reuse `markdown_parser.parse`). Skip files whose frontmatter `status` is `archived`/`dropped` for membership (but still count them for `_index.md` `entity_count`).
2. **Type hubs:** group by `frontmatter.type`. For each non-empty type, build the hub member list (sort by confidence desc, cap at `hub_member_cap`), compute `members[].summary` via `_one_line_summary(body)`, write `hubs/<friendly>.md`.
3. **Tag hubs:** count tag membership across active entities. For each tag with count ≥ `hub_tag_min_members`, build a member list the same way. Cap total tag hubs at `hub_tag_max_hubs` (highest membership first). Write `hubs/topic-<sanitize_id(tag)>.md`.
4. **Stale hub cleanup:** delete any `hubs/*.md` not regenerated this cycle (e.g. a tag that dropped below threshold, or a type that emptied out). Guard: only delete files inside `memory/hubs/` whose frontmatter `type == "hub"` — never touch anything else.
5. Write `_index.md` from the hub set + stats.
6. Hub `version` increments if the file already existed (read old `version`, +1), else 1.

`_one_line_summary(body)`:
```python
def _one_line_summary(body: str, limit: int = 140) -> str:
    text = re.sub(r"\[\[([^\]|]+)(\|[^\]]+)?\]\]", r"\1", body)  # unwrap wikilinks
    text = re.sub(r"[#>*`_-]", " ", text)                        # strip md noise
    text = " ".join(text.split())
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0] if text else ""
    return (first[:limit] + "…") if len(first) > limit else first
```

Hub generation over 1882 entities is a single directory scan + in-memory grouping — well under a second. It runs once per sleep cycle, so the cost is amortized.

### 5.1 New `Settings` fields (`api/config.py`)

```python
hub_tag_min_members: int = 5     # min entities sharing a tag to spawn a topic hub
hub_tag_max_hubs: int = 30       # cap on tag-cluster hubs
hub_member_cap: int = 150        # max members listed per hub file
```

---

## 6. How hubs appear in `/graph`

Hubs become **anchor nodes** in the graph response with distinct rendering flags. They are read from `memory/hubs/` and injected into the node/link lists by `graph_builder.build_graph`.

### 6.1 Schema changes (`api/models/schemas.py`)

`GraphNode` gains hub-rendering fields (camelCase on the wire via `CamelModel`):

```python
class GraphNode(CamelModel):
    id: str
    name: str
    type: str                    # CHANGE: widen from EntityType enum to str — must accept "hub".
    status: EntityStatus
    confidence: float
    tags: list[str] = []
    is_hub: bool = False         # NEW. drives distinct rendering (larger radius, ring, label always on).
    hub_kind: Optional[str] = None   # NEW. "type" | "tag" | None.
    member_count: Optional[int] = None  # NEW. node size scaling for hubs.
```

**Why widen `type` to `str`:** the closed `EntityType` enum (8 values) does not include `hub`, and we deliberately do **not** add it (keeps extraction/resolution/decay pipelines, which validate against the 8 types, untouched — adding a 9th type would ripple into the LLM extraction prompt and the Swift enum). `hub` is a node-render concept, not an entity type. Widening to `str` is backward compatible: existing 8 values still serialize identically, and the Swift side already decodes `type` as a string-backed enum that we extend with a `.hub` case + `.unknown` fallback.

`GraphLink` gains nothing structural, but the new `mentions` edges flow through unchanged. Hub membership edges use label `member of`.

### 6.2 `graph_builder.build_graph` changes

```python
def build_graph(memory_path, *, include_hubs: bool = True,
                types: set[str] | None = None,
                statuses: set[str] | None = None,
                min_confidence: float = 0.0) -> GraphResponse:
```
1. Build leaf entity nodes as today (apply optional `types`/`statuses`/`min_confidence` filters — see server-side filtering note below).
2. If `include_hubs`, scan `memory/hubs/*.md`. For each, append a `GraphNode(id="hub:"+stem, name=fm.name, type="hub", status="active", confidence=1.0, is_hub=True, hub_kind=fm.hub_kind, member_count=fm.member_count)`.
   - Hub node ids are namespaced `hub:<stem>` so they never collide with an entity id.
3. For each hub, append `GraphLink(source="hub:"+stem, target=member.id, label="member of")` for every member whose entity node exists in the (possibly filtered) node set.
4. `_load_edges` continues to read `graph_edges.yaml` as the **sole** canonical source (drop the `related`-fallback branch — see §4.1). Filter edges to endpoints that exist in the node set (prevents dangling-edge render errors from legacy slugs).

Hubs give d3 the natural centre-of-gravity anchors the flat graph lacks. The SwiftUI/d3 axis renders `is_hub` nodes larger with a ring; that is out of scope here but the flags are provided.

### 6.3 Server-side filtering (enabling param, light touch)

Extend `GET /graph` with optional query params so hub+media node growth doesn't bloat the payload:
```
GET /graph?types=person,project&statuses=active&min_confidence=0.3&include_hubs=true
```
`graph.py` parses comma-separated `types`/`statuses` into sets and passes them through. Default (no params) = today's behavior plus hubs. This is a small additive change; the SwiftUI client can keep doing local filtering and ignore the params.

---

## 7. Progressive-disclosure API: `GET /entities/{id}/context`

New endpoint in `api/routers/entities.py`. Returns the entity plus the cheap next-hops a small LLM needs to traverse without loading the whole graph.

### 7.1 Response model (`api/models/schemas.py`)

```python
class ContextNeighbor(CamelModel):
    id: str
    name: str
    type: str
    confidence: float
    summary: str          # one-line, same _one_line_summary slice
    via: str              # "leann" | "related" | "wikilink"
    score: Optional[float] = None   # LEANN similarity when via == "leann"

class ContextEpisodeExcerpt(CamelModel):
    episode_id: str
    timestamp: str
    excerpt: str          # ≤400 chars, whitespace-collapsed

class EntityContextResponse(CamelModel):
    id: str
    name: str
    type: str
    status: str
    confidence: float
    markdown_content: str
    hubs: list[str]                       # hub ids this entity belongs to, e.g. ["hub:people","hub:topic-robotics"]
    neighbors: list[ContextNeighbor]      # top LEANN entity neighbors + related + resolved wikilinks, deduped
    episodes: list[ContextEpisodeExcerpt] # excerpts from source_episodes + top LEANN episode hits
    next_hops: list[str]                  # ordered entity ids — the machine-parseable "read these next"
```

### 7.2 Endpoint

```python
@router.get("/entities/{entity_id}/context", response_model=EntityContextResponse)
async def get_entity_context(entity_id: str, top_k: int = 5,
                             settings: Settings = Depends(get_settings)):
```
Assembly (all defensive — see §8):
1. Resolve `entity_id` defensively: try `entities/{entity_id}.md`; if missing, try `entities/{sanitize_id(entity_id)}.md`; if still missing, scan for a frontmatter `name` match (cap the scan, return 404 if no hit).
2. `markdown_content` = entity body.
3. `hubs` = which hub files list this entity id in their `members` (read `hubs/*.md` frontmatter; cheap, ≤38 files).
4. `neighbors`:
   - LEANN `search_entities(name + " " + first 200 chars of body, top_k)` → `via="leann"`, with `score`.
   - `related` frontmatter ids → `via="related"`.
   - resolved `[[wikilinks]]` from body → `via="wikilink"`.
   - Merge, dedup by id, drop self, cap at `top_k*2`. Each gets a `_one_line_summary`.
5. `episodes`:
   - For each id in `source_episodes`, read `episodes/{ep}.md`, take a ≤400-char excerpt.
   - Plus top-2 LEANN `search_episodes(name, top_k=2)` not already included.
6. `next_hops` = ordered ids: LEANN neighbors first (by score), then `related`, then wikilink targets — deduped. This is the **explicit action list** a small model follows.

If LEANN is unavailable, neighbors/episodes degrade to `related` + wikilink + `source_episodes` only (never errors) — exactly mirroring the MCP server's existing graceful-degrade pattern.

---

## 8. Legacy filename / sanitize_id defensiveness

181 of 1882 entity files have filenames that do **not** round-trip through `sanitize_id(name)` (e.g. `#pragma-omp-simd-aligned(grid-32).md`, `$15k-consultant-fees.md`, `atlético-de-madrid.md`, `algorithms-&-data-structures.md`). The invariant `entity_id == sanitize_id(name)` is **false** for these legacy files. Every new code path must treat `filepath.stem` as the authoritative id and resolve names through a **multi-strategy lookup**, never by assuming `sanitize_id(name)` equals the filename.

**Shared helper** — add to `api/services/id_utils.py`:

```python
def build_name_index(entities_dir: Path) -> dict[str, str]:
    """Map every resolvable key -> filepath.stem (the authoritative id).
    Keys: lowercased frontmatter name, sanitize_id(name), the stem itself,
    and stem.replace('-', ' '). Last-writer-wins is acceptable; collisions are rare."""

def resolve_entity_id(entities_dir: Path, ref: str, name_index: dict[str,str] | None = None) -> str | None:
    """Resolve a name-or-id ref to a real filepath.stem. Tries, in order:
    exact file <ref>.md, file <sanitize_id(ref)>.md, name_index[ref.lower()],
    name_index[sanitize_id(ref)]. Returns None if unresolved (caller decides 404 vs skip)."""
```

Used by: `wikilink_resolver` (link target resolution), `hub_builder` (member id is just the stem — no sanitize needed, safe), `entities/{id}/context` (path resolution), and is also the correct fix for the MCP server's `_entity_id_for_name` (which currently only tries `name.replace(' ','-')` and a full scan).

**Hub member ids are always `filepath.stem`** — never recomputed from name — so legacy filenames are listed correctly and their hub links resolve. The graph builder's edge filter (keep only edges whose endpoints are in the node set) defends against `graph_edges.yaml` slugs that point at legacy files under a different sanitized key.

**No file renames.** We do **not** migrate the 181 legacy filenames (renaming would break `git blame` provenance and every existing edge/related slug that references them). We make the lookup tolerant instead. This is zero-data-loss.

---

## 9. MCP server: structured next-hop hints

Update `mcp/server.py` `handle_recall` to emit a **machine-parseable JSON block** at the **top** of its output, before the prose, so small models that ignore prose still get an action list. Also add hub-awareness.

### 9.1 New behavior in `handle_recall`

1. **Hub-first check (cold-start path):** before/alongside LEANN, check if the query matches a hub. Read `memory/hubs/*.md` frontmatter; if `query` token-overlaps a hub `name`/`source_tag`/`source_type`, surface that hub's member list as the primary answer. This gives a reliable answer even when LEANN is cold (fresh install, pre-rebuild) — directly addressing the "zero-LEANN cold start" gap.
2. **Structured hints block** prepended to the text result:

````
```cicada-hints
{
  "suggested_entities": ["figure-ai", "humanoid-robotics", "rodrigo"],
  "relevant_hub": "hubs/topic-robotics.md",
  "hub_members_preview": ["figure-ai", "humanoid-robotics"],
  "next_tool": "cicada_recall_detail",
  "note": "Call cicada_recall_detail with each suggested_entity id for full pages."
}
```
````
   - `suggested_entities`: top entity ids from the merged LEANN+keyword hits (the data `handle_recall` already computes — just surfaced as ids).
   - `relevant_hub`: the best-matching hub file path, or null.
   - This block is fenced with the literal info-string `cicada-hints` so a small model can locate and `json.loads` it deterministically.
3. The existing prose summaries, one-hop, and episode excerpts follow unchanged below the hints block.

### 9.2 New MCP tool `cicada_open_hub`

```json
{
  "name": "cicada_open_hub",
  "description": "Open a Cicada hub page (a topic or type index) and list its member entities with one-line summaries. Use after cicada_recall returns a relevant_hub, or to browse a topic. Pass a hub id like 'people', 'tools', or 'topic-robotics'.",
  "inputSchema": {"type":"object","properties":{"hub":{"type":"string"}},"required":["hub"]}
}
```
Handler reads `memory/hubs/<hub>.md` (try raw, then `topic-<sanitize_id>`), returns the body verbatim (member list with wikilinks + summaries). This is the MCP equivalent of "read a hub file" for clients that prefer tool calls over filesystem reads.

### 9.3 Fix `_entity_id_for_name`

Replace the ad-hoc resolution with `resolve_entity_id` semantics (the MCP server can't import `api.id_utils` reliably in all installs, so inline the same multi-strategy logic using its existing pyyaml-free `parse_frontmatter`). This fixes legacy-filename lookups in `cicada_recall_detail`.

---

## 10. Backward compatibility & migration

- **No entity data touched.** Hubs and `_index.md` are new derived files; the first sleep cycle after deploy creates them. A one-shot migration script `api/scripts/bootstrap_hubs.py` (callable, and run once at deploy) calls `wikilink_resolver.materialize_wikilink_edges` + `hub_builder.regenerate_hubs_and_index` so hubs/edges exist **before** the next sleep cycle, without forcing a full LLM cycle.
- **`graph_edges.yaml` is only appended to** (`mentions` edges merged via existing dedup). Existing relationship edges are preserved.
- **`related` frontmatter unchanged** — still written by `_update_related_fields`, now formally "derived/denormalized."
- **Graph builder dropping the `related` fallback** is safe: `graph_edges.yaml` exists (339KB) in the live dir; the fallback only fired when the file was absent (fresh installs), which the bootstrap script now covers.
- **Nudges/clarifications untouched** by this axis. `_index.md` reads their counts live; if the unified-inbox axis renames the dirs, update one read site.
- **Schema widening** (`GraphNode.type: str`, new optional fields) is additive — old clients ignore unknown fields; the new fields are all optional/defaulted.

---

## 11. Implementation steps (ordered)

1. **`api/config.py`** — add `hub_tag_min_members=5`, `hub_tag_max_hubs=30`, `hub_member_cap=150`.
2. **`api/services/id_utils.py`** — add `build_name_index` and `resolve_entity_id`. Unit-cover the 4 legacy filename shapes.
3. **`api/services/wikilink_resolver.py`** (NEW) — `materialize_wikilink_edges(memory_path)`: regex-extract `[[links]]`, resolve via name index, merge `mentions` edges into `graph_edges.yaml` (reuse `nudge_generator._write_graph_edges` logic — extract it to a shared helper or import it).
4. **`api/services/hub_builder.py`** (NEW) — `regenerate_hubs_and_index(memory_path, settings)` + `_one_line_summary`. Writes `hubs/*.md` and `_index.md`; deletes stale hub files (guarded by `type: hub`).
5. **`api/services/nudge_generator.py`** — in `generate()`, after `_write_graph_edges`/`_update_related_fields`, call `materialize_wikilink_edges` then `regenerate_hubs_and_index`. Pass `settings` into `generate` (currently not a param — thread it from `sleep_cycle.run`’s Stage 5 call, signature `generate(changes, skills, memory_path, settings, relationships=...)`).
6. **`api/services/sleep_cycle.py`** — pass `settings` to `nudge_generator.generate`. Add hub/edge file lines to the commit manifest via `_infer_trigger_for_path` (`hubs/` → `sleep/hub_generation`, `_index.md` → `sleep/hub_generation`).
7. **`api/models/schemas.py`** — widen `GraphNode.type` to `str`; add `is_hub`, `hub_kind`, `member_count`. Add `ContextNeighbor`, `ContextEpisodeExcerpt`, `EntityContextResponse`.
8. **`api/services/graph_builder.py`** — read `hubs/*.md`, inject hub nodes + `member of` edges; drop the `related` fallback in `_load_edges`; filter edges to existing endpoints; add filter params.
9. **`api/routers/graph.py`** — accept `types`, `statuses`, `min_confidence`, `include_hubs` query params.
10. **`api/routers/entities.py`** — add `GET /entities/{id}/context` per §7. Use `resolve_entity_id` for path resolution.
11. **`mcp/server.py`** — prepend `cicada-hints` JSON block in `handle_recall`; add hub-first cold-start check; add `cicada_open_hub` tool + handler; fix `_entity_id_for_name` with multi-strategy resolution.
12. **`api/scripts/bootstrap_hubs.py`** (NEW) — one-shot: run wikilink materialization + hub/index generation against the live `memory/`. Run once after deploy so the 1882-entity graph gets hubs immediately.
13. **Verify:** `python -c "import api.services.hub_builder, api.services.wikilink_resolver"`; run `bootstrap_hubs.py` against a **copy** of `memory/` (or rely on git to revert); confirm `ls memory/hubs/` and `cat memory/_index.md`; hit `GET /graph?include_hubs=true` and `GET /entities/<id>/context`; run `cicada_recall` and confirm a parseable `cicada-hints` block.

---

## 12. Cross-axis contracts (depends_on / provides)

- **Provides to graph-UI/d3 axis:** `GraphNode.is_hub`/`hub_kind`/`member_count` flags + `member of` / `mentions` edge labels for distinct hub anchor rendering.
- **Provides to richer-entity-pages axis:** `_one_line_summary` lives in `hub_builder`; if that axis adds a `## Summary` section, hubs should prefer it over the body-first-sentence slice (one-line change in `_one_line_summary`).
- **Depends on unified-inbox axis:** `_index.md` `pending_inbox_count` reads nudge+clarification dirs; if they merge into `memory/inbox/`, update the one count read site. Non-blocking.
- **Depends on media axis:** `hubs/media.md` type hub stays empty until a `media` entity type/tag exists; reserved name only.
