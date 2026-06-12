# Graph Visualization Redesign (v2)

**Axis:** Graph visualization — turn the d3-force hairball into a meaningful, navigable map.
**Branch:** `feat/v2-revamp`
**Owner goal coverage:** #2 (small-LLM traversal via hubs/progressive disclosure — mirrored in UI), #4 (hub topics as gravitational anchors), #7 (meaningful graph viz).

This spec is decisive: it picks ONE approach per concern and is sized for a single developer to finish in a few days. It assumes the **hubs axis** ships `is_hub` entities and a `members:` field, and the **inbox axis** ships a unified `/inbox` so the graph can flag entities with pending items. Those cross-axis contracts are listed at the end. Where a contract is not yet in place, the graph degrades gracefully (treats the flag as `false`).

---

## 0. Problem, in one paragraph

Today `graph.js` renders every entity as a peer circle. Size encodes `sqrt(degree)*3 + confidence*4`, color encodes type, `decaying` nodes get 0.55 alpha + a dashed stroke, hover dims non-neighbors. Eight fixed `typeClusterPositions` at strength `0.04` provide near-invisible separation. `updateGraph()` blows away the entire simulation and reseeds from random positions on every refresh (post-sleep = visual explosion). There are no hub anchors, no focus/ego mode, no edge labels, no semantic-zoom tiers beyond a single label threshold, no pending-item signal, no toolbar, and the Swift filter is type-only and not shared with the Topics tab. The fix is **focus+context + hub-anchored layout + semantic zoom + incremental updates**, all on the existing canvas pipeline (no renderer rewrite).

---

## 1. Design principles applied (the "why")

| Principle | Concrete encoding in this spec |
|---|---|
| **Focus + context** | Ego/focus mode: click a node → only its ≤2-hop neighborhood stays at full alpha + runs the sim; everything else fades to context (alpha 0.06, frozen). ESC restores the full graph. |
| **Visual hierarchy** | Hubs are the top tier: distinct ring, larger radius floor, strongest cluster anchor. Members orbit their hub. Leaves are smallest. |
| **Preattentive encoding** | One channel per attribute: **hue = type**, **size = confidence (+ degree)**, **opacity = status**, **dash = decaying**, **pulse ring = pending inbox item**, **double ring + size floor = hub**. No channel does double duty for two meanings. |
| **Semantic zoom** | Three zoom tiers: out = hubs+structure only, mid = node labels for big nodes, in = node labels for all visible + edge labels. Progressive disclosure mirrors the small-LLM hub→entity→episode traversal. |
| **Incremental stability** | New simulations seed from previous node positions; only genuinely-new nodes get a random seed near their hub; alpha is reheated low (`0.3`) so the layout settles instead of exploding. |

---

## 2. Server-side `/graph` changes (API)

### 2.1 New `GraphNode` fields

`api/models/schemas.py` — extend `GraphNode` (all additive, all optional with defaults so old Swift clients keep decoding):

```python
class GraphNode(CamelModel):
    id: str
    name: str
    type: EntityType
    status: EntityStatus
    confidence: float
    tags: list[str] = []
    degree: int = 0          # NEW: computed edge count (server is the source of truth)
    is_hub: bool = False     # NEW: from frontmatter is_hub OR type == hub (hubs axis)
    has_pending: bool = False # NEW: entity_id appears in any unified inbox item
    member_count: int = 0    # NEW: len(members) for hubs, else 0
```

Serialized (camelCase via `to_camel`): `degree`, `isHub`, `hasPending`, `memberCount`.

### 2.2 New `GraphResponse` query params + server-side filtering

`api/routers/graph.py`:

```python
@router.get("/graph", response_model=GraphResponse)
async def get_graph(
    types: str | None = None,          # comma-sep EntityType values
    statuses: str | None = None,       # comma-sep EntityStatus values, default excludes "dropped"
    min_confidence: float = 0.0,
    tags: str | None = None,           # comma-sep; node kept if it has ANY of these tags
    hubs_only: bool = False,           # return only hub nodes + their member edges (zoomed-out tier)
    settings: Settings = Depends(get_settings),
):
    return build_graph(
        settings.memory_path,
        types=_split(types),
        statuses=_split(statuses),
        min_confidence=min_confidence,
        tags=_split(tags),
        hubs_only=hubs_only,
    )
```

`_split(s)` → `[x.strip() for x in s.split(",") if x.strip()]` or `None`.

### 2.3 `build_graph` rewrite (`api/services/graph_builder.py`)

Single pass, with degree + flag computation and an in-memory mtime cache. Pseudocode:

```python
_CACHE: dict = {"key": None, "value": None}  # module-level

def build_graph(memory_path, *, types=None, statuses=None,
                min_confidence=0.0, tags=None, hubs_only=False):
    full = _build_full(memory_path)          # cached on (entities_dir, edges_file) mtime
    return _apply_filters(full, types, statuses, min_confidence, tags, hubs_only)

def _build_full(memory_path) -> GraphResponse:
    entities_dir = memory_path / "entities"
    edges_file   = memory_path / "graph_edges.yaml"
    key = (_dir_mtime(entities_dir), _mtime(edges_file), _inbox_mtime(memory_path))
    if _CACHE["key"] == key:
        return _CACHE["value"]

    pending_ids = _load_pending_entity_ids(memory_path)   # set of entity_ids in inbox/
    raw_links   = _load_edges(memory_path)                 # existing logic, unchanged

    # degree from links (string endpoints at this stage)
    degree = Counter()
    for l in raw_links:
        degree[l.source] += 1; degree[l.target] += 1

    nodes = []
    for filepath in sorted(entities_dir.glob("*.md")):
        fm = parse(filepath).frontmatter
        eid = filepath.stem
        members = fm.get("members") or []
        is_hub = bool(fm.get("is_hub")) or fm.get("type") == "hub"
        nodes.append(GraphNode(
            id=eid,
            name=fm.get("name", eid.replace("-", " ").title()),
            type=fm.get("type", "concept"),
            status=fm.get("status", "active"),
            confidence=fm.get("confidence", 0.5),
            tags=fm.get("tags", []) or [],
            degree=degree.get(eid, 0),
            is_hub=is_hub,
            has_pending=eid in pending_ids,
            member_count=len(members),
        ))
    resp = GraphResponse(nodes=nodes, links=raw_links)
    _CACHE.update(key=key, value=resp)
    return resp
```

- `_load_pending_entity_ids`: scan `memory/inbox/*.md` frontmatter for `entity_id` (the unified inbox item schema). If `inbox/` does not exist yet, also scan legacy `nudges/*.md` + `clarifications/*.md` for `entity_id` so the flag works before the inbox migration lands. Returns `set[str]`.
- `_inbox_mtime`: max mtime across `inbox/` (and legacy dirs) so resolving an inbox item invalidates the cache.
- `hubs_only=True`: keep nodes where `is_hub`, plus any node that is a `member` of a kept hub; keep only edges between kept nodes. This is the zoomed-out tier payload — the client fetches it first, then lazy-fetches the full graph.
- Cache keyed on directory mtime means the first `GET /graph` after a sleep cycle pays the ~100–300 ms scan once; every repeat is <5 ms. This directly fixes the "full directory scan on every request" limitation.

**EntityType `hub`:** the hubs axis adds `hub` to the `EntityType` enum (Python + Swift). This spec only *consumes* `is_hub`; if the hubs axis instead uses a boolean flag on existing types, nothing here changes. Add `hub` to `typeColors`/`entityColor` regardless (color `#E879F9`, a bright magenta distinct from project purple).

---

## 3. Swift ↔ JS message contract

### 3.1 Swift → JS (function calls via `evaluateJavaScript`)

| Existing | Keep / change |
|---|---|
| `updateGraph(json)` | **Change semantics** to incremental (see §5). Same signature. |
| `zoomIn() / zoomOut() / zoomReset()` | Keep. |
| `filterTypes(jsonArray)` | **Replace** with `applyFilters(jsonObject)` (see below). Keep `filterTypes` as a thin shim that calls `applyFilters({types})` for one release. |
| `setMinDegree(k)` | Keep (still used by a "hide leaves" toggle). |
| **NEW** `setFocus(id, hops)` | Enter ego/focus mode on `id` with `hops` (1 or 2). `id=null` exits. |
| **NEW** `clearFocus()` | Exit focus mode (ESC). |
| **NEW** `highlightSearch(jsonArray)` | Highlight a set of node ids (search results); pass `[]` to clear. |
| **NEW** `focusOnNode(id)` | Pan/zoom-to + select a node by id (search result click) without entering ego mode. |

`applyFilters` payload (JSON object string):

```json
{
  "types": ["person","project"],        // [] or null = all
  "statuses": ["active","decaying"],    // null = all except dropped
  "minConfidence": 0.0,
  "tags": [],                            // null/[] = no tag filter
  "minDegree": 1
}
```

JS sets module-level filter state and calls `rebuildVisible()` + a *soft* sim reheat (no full restart). All filtering is client-side over the already-loaded full graph (the server params in §2.2 are used only for the initial hubs-only fetch and for very large graphs — see §7).

### 3.2 JS → Swift (postMessage `window.webkit.messageHandlers.cicada`)

Existing message types: `graphReady`, `nodeClicked`. Add:

| `type` | Payload | Meaning |
|---|---|---|
| `nodeClicked` | `{id}` | **Unchanged.** Single click selects + opens detail card (existing behavior). |
| `nodeFocused` | `{id, hops}` | NEW. Emitted when ego mode is *entered* (double-click or a dedicated focus gesture). Lets Swift update breadcrumb / "focused on X" chip. |
| `focusCleared` | `{}` | NEW. Emitted when ESC/zoom-out exits ego mode. |
| `hubExpanded` | `{id}` | NEW. Emitted when a hub node is clicked in hubs-only view; Swift responds by pushing the full member subgraph. |

**Gesture map (decisive):**
- **Single click** on any node → `nodeClicked` (select + detail card). No layout change.
- **Double-click** on a node → enter ego/focus mode (`setFocus(id, 2)` locally + emit `nodeFocused`). This repurposes the current double-click-to-reset; reset moves to the toolbar "Fit" button and the ESC-to-clear path.
- **ESC** (handled in JS keydown) → `clearFocus()` + emit `focusCleared`. Swift's existing `.onKeyPress(.escape)` on the detail card still clears selection; the two are independent (ESC with no focus active just clears selection).
- **Click a hub in hubs-only mode** → emit `hubExpanded`; Swift fetches full graph (or that hub's members) and calls `updateGraph` + `setFocus(hubId, 1)`.

### 3.3 `GraphView.swift` changes

`updateNSView` currently handles `zoomAction`, `pendingGraphUpdate`, `pendingFilterUpdate`. Add:
- `pendingFocusUpdate` → calls `setFocus(id, hops)` / `clearFocus()`.
- `pendingSearchHighlight` → calls `highlightSearch(json)` and/or `focusOnNode(id)`.
- Rename the filter branch to push `applyFilters(jsonObject)` built from the shared filter struct (§6).

Coordinator `didReceive`: add `case "nodeFocused" / "focusCleared" / "hubExpanded"` updating `GraphViewModel`.

---

## 4. The new `graph.js` — functions to add / change

Keep the canvas pipeline, `requestAnimationFrame` loop, quadtree hit-testing (`simulation.find`), and the alpha-gated redraw. Add the following.

### 4.1 Module state additions

```js
let focusNodeId = null;      // ego mode anchor; null = full graph
let focusHops = 2;
let focusSet = null;         // Set<id> of nodes inside the focus neighborhood (incl anchor)
let searchHighlight = null;  // Set<id> from toolbar search, or null
let filters = {              // replaces ad-hoc enabledTypes/currentMinDegree
  types: null, statuses: null, minConfidence: 0, tags: null, minDegree: 1,
};
const prevPositions = new Map(); // id -> {x,y} carried across updateGraph() calls
let pulsePhase = 0;          // animation clock for pending-item pulse rings
```

`enabledTypes` and `currentMinDegree` collapse into `filters`. `filterTypes()` becomes a shim: `applyFilters(JSON.stringify({types: parsed}))`.

### 4.2 `computeFocusSet()` — BFS over `neighborsById`

```js
function computeFocusSet() {
  if (!focusNodeId) { focusSet = null; return; }
  const seen = new Set([focusNodeId]);
  let frontier = [focusNodeId];
  for (let h = 0; h < focusHops; h++) {
    const next = [];
    for (const id of frontier) {
      for (const nb of (neighborsById.get(id) || [])) {
        if (!seen.has(nb)) { seen.add(nb); next.push(nb); }
      }
    }
    frontier = next;
  }
  focusSet = seen;
}
```

`neighborsById` already exists and is rebuilt in `rebuildNeighborsIndex()` — reuse it.

### 4.3 `setFocus(id, hops)` / `clearFocus()`

```js
function setFocus(id, hops) {
  focusNodeId = id || null;
  focusHops = Number(hops) || 2;
  computeFocusSet();
  // Pin context nodes (outside focus) so the sim only relaxes the focused subgraph.
  for (const n of visibleNodes) {
    const inFocus = !focusSet || focusSet.has(n.id);
    if (focusNodeId && !inFocus) { n.fx = n.x; n.fy = n.y; }   // freeze context
    else { n.fx = null; n.fy = null; }
  }
  if (simulation) simulation.alpha(0.4).restart();   // gentle reheat, focused subgraph only
  if (focusNodeId) animateZoomToFocus();             // d3.zoom to the focus bbox
  scheduleRedraw();
}
function clearFocus() {
  for (const n of visibleNodes) { n.fx = null; n.fy = null; }
  focusNodeId = null; focusSet = null;
  if (simulation) simulation.alpha(0.2).restart();
  scheduleRedraw();
}
```

`animateZoomToFocus()`: compute the bbox of `focusSet` nodes, build a `d3.zoomIdentity.translate(...).scale(...)` that fits it with padding, and call `currentZoom.transform` over a 400 ms transition (same pattern as `zoomReset`).

### 4.4 Rendering changes in `draw()`

**Status → opacity (replace the binary decaying check):**
```js
const STATUS_ALPHA = { active: 0.92, decaying: 0.5, archived: 0.28, dropped: 0.0 };
let alpha = STATUS_ALPHA[n.status] ?? 0.92;
```
(`dropped` nodes are normally filtered server-side, but if present they render invisible.)

**Focus dimming (focus+context):** before applying hover/type dimming, if `focusSet` is active:
```js
if (focusSet && !focusSet.has(n.id)) alpha = Math.min(alpha, 0.06);
```
Same for links: a link is full-strength only if *both* endpoints are in `focusSet`, else `0.04`.

**Confidence = size (decisive change to `nodeRadius`):** make confidence the *primary* size channel and degree a secondary bump, the inverse of today, so the encoding "bigger = more confident" is preattentive and not dominated by hub degree (hubs get their size from the hub floor, §below):
```js
function nodeRadius(d) {
  const base = 4;
  const confTerm = (d.confidence || 0) * 8;     // primary: 0–8 px
  const degreeTerm = Math.sqrt(d.degree || 0) * 1.5; // secondary
  let r = base + confTerm + degreeTerm;
  if (d.isHub) r = Math.max(r * 1.6, 22);       // hub size floor
  return r;
}
```

**Hub ring (visual hierarchy):** after filling a hub node, stroke a second concentric ring:
```js
if (n.isHub) {
  ctx.lineWidth = 2 / transform.k;
  ctx.strokeStyle = color;
  ctx.globalAlpha = alpha;
  ctx.beginPath(); ctx.arc(n.x, n.y, r + 4 / transform.k, 0, 2*Math.PI); ctx.stroke();
}
```

**Pending-item pulse ring (preattentive "needs you"):** a slow expanding/fading ring, animated by `pulsePhase`:
```js
if (n.hasPending) {
  const t = (pulsePhase % 1);                 // 0..1
  const pr = r + (6 + t * 10) / transform.k;
  ctx.globalAlpha = (1 - t) * 0.6 * alpha;
  ctx.lineWidth = 2 / transform.k;
  ctx.strokeStyle = "#F5C04E";                // amber attention color
  ctx.beginPath(); ctx.arc(n.x, n.y, pr, 0, 2*Math.PI); ctx.stroke();
}
```
Drive `pulsePhase` only when at least one visible node has `hasPending` (so idle graphs stay at zero CPU): in `scheduleRedraw`'s RAF callback, if `anyPending` then `pulsePhase += 0.016` and keep scheduling frames even when the sim has settled. Gate behind `anyPending` so the "idle CPU goes to zero" property is preserved for graphs with no pending items.

**Decaying dashed stroke:** keep existing dashed-stroke logic, now gated on `n.status === "decaying"` only (unchanged).

### 4.5 Semantic zoom — three tiers (replace the single label threshold)

```js
const ZOOM_HUBS_ONLY   = 0.45;  // below: only hub labels, leaves are dots
const ZOOM_NODE_LABELS = 1.2;   // above: labels for nodes clearing screen-radius
const ZOOM_EDGE_LABELS = 2.2;   // above: edge labels at link midpoints
```

Label loop logic:
- `transform.k < ZOOM_HUBS_ONLY`: draw labels **only** for `isHub` nodes (and only those clearing `LABEL_MIN_SCREEN_RADIUS`). The zoomed-out view reads as a labeled hub map, not an anonymous constellation — this is the "navigational entry points" fix.
- `ZOOM_HUBS_ONLY ≤ k < ZOOM_NODE_LABELS`: hub labels + labels for nodes whose `r * k ≥ LABEL_MIN_SCREEN_RADIUS` (existing behavior, now also always-on for hubs).
- `k ≥ ZOOM_NODE_LABELS`: labels for all visible nodes clearing the screen-radius floor.
- `k ≥ ZOOM_EDGE_LABELS`: **edge labels.** In a new pass over `visibleLinks`, draw `l.label` at the link midpoint with the small background plate (reuse the hover-label plate code). Default alpha `0.3`; `0.85` for edges touching `hoveredNode` or inside `focusSet`. This is the highest information-design win for ~10 lines — `l.label` is already in every link.

When `focusSet` is active, force node + edge labels on for the focus neighborhood regardless of zoom (you focused it; you want to read it).

### 4.6 Incremental `updateGraph()` (position preservation)

```js
function updateGraph(dataStr) {
  const data = typeof dataStr === "string" ? JSON.parse(dataStr) : dataStr;

  // 1. snapshot positions of the current sim before we replace anything
  for (const n of nodes) if (n.x != null) prevPositions.set(n.id, {x:n.x, y:n.y, vx:n.vx, vy:n.vy});

  nodes = data.nodes || [];
  links = data.links || [];
  computeDegree();                 // (existing inline block extracted to a fn)

  // 2. seed positions: reuse previous for known nodes; place new nodes near a hub or neighbor
  for (const n of nodes) {
    const p = prevPositions.get(n.id);
    if (p) { n.x = p.x; n.y = p.y; n.vx = p.vx || 0; n.vy = p.vy || 0; }
    else   { const s = seedPositionFor(n); n.x = s.x; n.y = s.y; }
  }

  rebuildVisible();
  rebuildNeighborsIndex();
  startSimulation({ reheat: prevPositions.size > 0 ? 0.3 : 1.0 });
  if (focusNodeId) { computeFocusSet(); setFocus(focusNodeId, focusHops); }
  scheduleRedraw();
}
```

`seedPositionFor(n)`: if `n` has a hub member-edge, start at that hub's position + small jitter; else at the `typeClusterPositions[n.type]` anchor + jitter; else origin + jitter. `startSimulation({reheat})`: set `simulation.alpha(reheat)` instead of the implicit `1.0` so a post-sleep refresh of a few nodes does a gentle settle, not a full re-layout from random. **This is the fix for "post-sleep layout explodes."**

### 4.7 Hub-anchored layout (gravitational anchors)

Replace the static 8-position `xType/yType` anchoring with **hub-centroid anchoring**:
- Hubs get their own ring of anchor positions on a circle (radius ~400) computed once per `updateGraph` from the set of hubs present (evenly spaced by index). Apply `forceX/forceY` toward the hub's anchor at strength `0.08` for hub nodes only.
- Member nodes are pulled toward *their hub's current position* (not a static type anchor): add a custom force that, each tick, nudges each member toward its hub node's `{x,y}` at strength `0.05`. Implement as a `forceLink`-like closure or a lightweight per-tick force:
```js
.force("hubGravity", hubGravityForce(0.05))
```
where `hubGravityForce` reads a precomputed `memberToHub: Map<id, hubId>` (from the `members` field surfaced as edges, or from a `hubId` on member nodes if the hubs axis sets one). Nodes with no hub fall back to the existing soft `typeClusterPositions` anchor at strength `0.04`. This gives the graph real centers of gravity and makes type clusters legible instead of a uniform blob.

---

## 5. SwiftUI: top toolbar + shared filter state

### 5.1 New shared filter model

Create `app/CicadaApp/Sources/CicadaApp/Models/GraphFilter.swift`:

```swift
struct GraphFilter: Equatable {
    var types: Set<EntityType> = Set(EntityType.allCases)
    var statuses: Set<EntityStatus> = [.active, .decaying]   // hide archived/dropped by default
    var minConfidence: Double = 0.0
    var minDegree: Int = 1
    var tags: Set<String> = []
    var searchText: String = ""
}
```

Move filter ownership into `GraphViewModel` as `var filter = GraphFilter()` and expose `var pendingFilterUpdate`. **TopicsView binds to `graphVM.filter`** (replacing its private `@State enabledTypes`) so filtering on Topics and on Graph are the same state — fixes the "Topics and Graph maintain independent filter state" limitation. `filteredEntities` becomes filter-driven (types ∪ statuses ∪ confidence ∪ tags ∪ degree).

`GraphViewModel.graphDataJSON` gains the new node fields (`degree`, `isHub`, `hasPending`, `memberCount`) — passed straight through from the `GraphNode` decode (degree/flags now come from the server, so the VM stops needing to compute degree on the JS side, though JS still recomputes degree from links for the link-mutation ordering reason noted in the file).

### 5.2 New `GraphToolbar` view

Create `app/CicadaApp/Sources/CicadaApp/Views/Graph/GraphToolbar.swift`. A single horizontal glass bar pinned to the top of `GraphContainerView`, left-to-right:

1. **Search field** (`TextField`, `~240pt`): search-as-you-type. On change (debounced 200 ms) calls `await APIClient.shared.search(q:)` (§5.4). Results populate a dropdown list (name + type chip + confidence). Selecting a result → `graphVM.focusOnNode(id)` (pan/zoom-to + select). While typing, the matched ids are pushed to JS via `highlightSearch(ids)` so matches glow in place.
2. **Type filter** popover (existing `EntityType.allCases` checklist, now bound to `filter.types`; the new `hub` type appears automatically).
3. **Status filter** popover (Active / Decaying / Archived toggles; Dropped never shown).
4. **Confidence slider** (`0.0–1.0`, label "min conf").
5. **"Hide leaves" toggle** → `filter.minDegree` 0↔1 (or a stepper to 2).
6. **Focus chip** (only visible when `graphVM.focusNodeId != nil`): "Focused: {name} ✕" — tapping ✕ calls `clearFocus()`.
7. **Fit button** (`arrow.up.left.and.arrow.down.right`) → `zoomReset()`.

Any change to `filter` flips `pendingFilterUpdate`; `GraphView.updateNSView` pushes `applyFilters(jsonObject)`.

This toolbar is graph-specific and lives *inside* `GraphContainerView`, distinct from the existing app-wide `TopBarControls` (Sleep/Upload/Help) which stays where it is.

### 5.3 `GraphViewModel` additions

```swift
var focusNodeId: String? = nil
var focusNodeName: String? = nil
var pendingFocusUpdate: Bool = false      // (id?, hops) packed in a small struct
var pendingSearchHighlight: Bool = false
var searchResults: [GraphSearchHit] = []

func enterFocus(id: String, hops: Int = 2) { focusNodeId = id; pendingFocusUpdate = true }
func exitFocus() { focusNodeId = nil; pendingFocusUpdate = true }
func focusOnNode(id: String) { selectEntity(id: id); /* push focusOnNode(id) to JS */ }
```

Wire the new postMessage cases (`nodeFocused`, `focusCleared`, `hubExpanded`) in `GraphView.Coordinator` to update `focusNodeId`/`focusNodeName` and, for `hubExpanded`, trigger a full-graph fetch.

### 5.4 Search endpoint (consumed by the toolbar)

The toolbar calls `GET /search?q=&top_k=8&indexes=entities`. This endpoint is **owned by the storage/retrieval axis** (LEANN `search_entities`), but the graph toolbar is its first consumer, so the contract is pinned here:

```
GET /search?q=<str>&top_k=8&indexes=entities
→ 200 { "results": [
    { "id": "<entity_id>", "name": "...", "type": "person",
      "status": "active", "confidence": 0.82, "score": 0.41, "snippet": "..." }
  ] }
```

Swift model `GraphSearchHit { id, name, type: EntityType, status: EntityStatus, confidence: Double, score: Double, snippet: String }` and `APIClient.search(q:topK:) -> [GraphSearchHit]`. If `/search` 404s (endpoint not yet shipped), the toolbar **falls back to local substring match** over `graphVM.entities` so search works before the LEANN endpoint lands. Search results that are not currently in the loaded graph (e.g. archived) are shown but clicking one fetches+adds it.

---

## 6. Performance notes for 2000+ nodes (what exists vs. what to add)

**Already good (keep):**
- Canvas renderer, not SVG/DOM — the per-tick cost is `O(visible)` draw calls, not DOM mutations.
- `requestAnimationFrame` redraw gated on `simulation.alpha() > alphaMin()` → idle CPU drops to zero.
- Quadtree hit-testing via `simulation.find(wx, wy, pickRadius)` for hover/pick.
- Tuned `alphaDecay(0.05)`, `velocityDecay(0.55)`, `alphaMin(0.05)`, `forceManyBody().distanceMax(400).theta(0.9)` — already dense-graph aware.

**Add:**
- **Hubs-only first paint:** initial load fetches `GET /graph?hubs_only=true` (tens of nodes), renders instantly, then fetches the full graph in the background and `updateGraph()`s it incrementally (positions for the hubs are preserved, so no jump). This keeps cold-start snappy at 2000+ nodes.
- **Link culling at low zoom:** when `transform.k < ZOOM_HUBS_ONLY`, skip drawing leaf-to-leaf links (draw only links touching a hub). At 4500+ edges this halves the link draw cost when zoomed out, where individual leaf edges are invisible anyway.
- **Label budget:** cap rendered labels per frame to ~200 (sort candidates by radius, draw the largest). Prevents text-rendering blowup when fully zoomed in on a dense region.
- **`forceCollide` already O(n log n)** via quadtree; keep `strength(0.8)` but consider dropping collide entirely below `ZOOM_HUBS_ONLY` (cosmetic overlap is invisible when zoomed out) — gate via a `simulation.find`-cheap flag, not per-tick.
- Degree now arrives from the server, so JS could skip its degree recompute — but keep the JS recompute (it's needed before `forceLink` mutates endpoints) and treat the server `degree` as authoritative for `nodeRadius` only.

---

## 7. Backward compatibility & migration

- **`GraphNode` new fields are additive + defaulted.** Old Swift `GraphNode` decoder uses `decodeIfPresent ?? default` for `tags` already; add the same defensive decode for `degree`/`isHub`/`hasPending`/`memberCount` so a new app talking to an old API (or vice versa) never crashes.
- **No data migration in this axis.** `is_hub` / `members` come from the hubs axis migration; `has_pending` reads whatever inbox layout exists (new `inbox/` *or* legacy `nudges/`+`clarifications/`). With 1882 entities / 39 nudges / 33 clarifications live, the `_load_pending_entity_ids` dual-path means the pulse ring lights up correctly both before and after the inbox migration. No entity files are written by this axis.
- **`filterTypes` shim** retained one release so any in-flight Swift build still works while `applyFilters` rolls out.
- **`hub` color** added to `typeColors`/`entityColor`; if the hubs axis ships before this one, hub nodes render as `concept` green (harmless) until the color map updates.

---

## 8. Files to create / modify

**Create**
- `app/CicadaApp/Sources/CicadaApp/Models/GraphFilter.swift` — shared filter struct + `GraphSearchHit`.
- `app/CicadaApp/Sources/CicadaApp/Views/Graph/GraphToolbar.swift` — search-as-you-type + filters + focus chip + fit.

**Modify**
- `api/models/schemas.py` — add `degree/is_hub/has_pending/member_count` to `GraphNode`.
- `api/routers/graph.py` — query params + pass-through to `build_graph`.
- `api/services/graph_builder.py` — single-pass build, degree, flags, pending-id scan, mtime cache, `hubs_only`, filters.
- `app/.../Resources/graph/graph.js` — focus mode, semantic-zoom tiers, edge labels, pending pulse, hub ring, status-opacity map, hub-anchored layout, incremental `updateGraph`, `applyFilters`.
- `app/.../Resources/graph/index.html` — add ESC keydown → `clearFocus()` (or handle in graph.js `document.addEventListener('keydown')`).
- `app/.../Views/Graph/GraphView.swift` — handle `pendingFocusUpdate`/`pendingSearchHighlight`; new postMessage cases; push `applyFilters`.
- `app/.../ViewModels/GraphViewModel.swift` — `filter: GraphFilter`, focus state, search state, new JSON fields, double-click→focus wiring.
- `app/.../Models/Entity.swift` — `GraphNode` defensive decode for new fields; add `hub` to `EntityType` if hubs axis hasn't (coordinate to avoid a duplicate enum case).
- `app/.../Theme/CicadaTheme.swift` — `entityColor(for: .hub)` = magenta; amber pulse + hub-ring colors as named constants.
- `app/.../Views/Topics/TopicsView.swift` — bind to `graphVM.filter` instead of private state.
- `app/.../Views/Graph/GraphView.swift` container (`ContentView.GraphContainerView`) — mount `GraphToolbar` above `GraphView`.

---

## 9. Numbered implementation steps (single dev, ~3–4 days)

1. **Schema + builder (API).** Add the four `GraphNode` fields; rewrite `build_graph` with degree, flags, pending-id dual-path scan, and the mtime cache. Add `/graph` query params. Verify with `curl 'localhost:8000/graph?hubs_only=true'` and `?types=person&min_confidence=0.5`.
2. **Swift decode + filter model.** Add defensive decode for new fields; create `GraphFilter.swift`; move filter into `GraphViewModel`; make `filteredEntities`/`graphDataJSON` filter-driven and emit the new node fields. App builds, graph still renders.
3. **graph.js visual encodings.** Status→opacity map, confidence-primary `nodeRadius`, hub size floor + ring, decaying dash (keep), pending pulse ring (gated on `anyPending`). Verify each encoding visually with seeded data.
4. **graph.js semantic zoom.** Three zoom tiers; hub-only labels when zoomed out; node-label tier; edge-label pass at high zoom reusing the hover-plate. Verify labels appear/disappear at the right `k`.
5. **graph.js focus mode.** `computeFocusSet` (BFS over `neighborsById`), `setFocus/clearFocus`, context-node freezing, `animateZoomToFocus`, double-click gesture, ESC keydown. Emit `nodeFocused/focusCleared`. Verify ego mode isolates ≤2-hop neighborhood and ESC restores.
6. **graph.js incremental updates + hub-anchored layout.** `prevPositions` snapshot/restore, `seedPositionFor`, `startSimulation({reheat})`, `hubGravityForce`. Verify a simulated post-sleep `updateGraph` (add 5 nodes) does NOT explode the layout.
7. **graph.js `applyFilters`** replacing `filterTypes` (keep shim). Wire `GraphView.updateNSView` to push it. Verify Topics-tab filter changes reflect in the Graph tab.
8. **GraphToolbar + search.** Build the toolbar; wire search-as-you-type to `APIClient.search` with local-substring fallback; `highlightSearch` + `focusOnNode`; focus chip; Fit button. Mount above `GraphView`.
9. **Coordinator messages.** Handle `nodeFocused/focusCleared/hubExpanded`; hubs-only first-paint then background full-graph fetch.
10. **Perf pass.** Link culling at low zoom, label budget, optional collide-off when zoomed out. Sanity-test with a synthetic 2000-node / 4500-edge payload (script that emits random nodes/links) and confirm pan/zoom stays >30 fps and idle CPU is ~0 with no pending items.

---

## 10. Cross-axis contracts this design assumes

- **Hubs axis** provides: `is_hub: bool` (or `type == "hub"`) and `members: [entity_id]` in entity frontmatter; optionally a `hubId` on member entities (used by `hubGravityForce`; falls back to member-edge inference if absent). Adds `hub` to the `EntityType` enum (Python + Swift) and the `typeColors` map.
- **Unified inbox axis** provides: `memory/inbox/*.md` items whose frontmatter carries `entity_id`, so `has_pending` can be computed. Until then, the builder reads legacy `nudges/` + `clarifications/` for the same flag (no behavior gap).
- **Storage/retrieval axis** provides: `GET /search?q=&top_k=&indexes=entities` returning `{results:[{id,name,type,status,confidence,score,snippet}]}` backed by LEANN `search_entities`. Toolbar falls back to local substring match if absent.
