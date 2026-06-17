# D2 Companion-App Showcase — Making the Claim Layer Visible

**Mandate:** the more the companion app can *show*, the better. The new memory architecture
(Cicada Claim Layer — claims keyed by `(observer, context, subject)`, bi-temporally valid,
per-claim provenance, facet sub-nodes, inline transclusion) is only as impressive as the surfaces
that render it. This document specifies five concrete, buildable companion-app surfaces — each a
real SwiftUI view (or d3 layer) plus the exact API it consumes — that make the structure visible:

1. **Inline transclusion** — one page embedding another, rendered inline (`![[claim:…]]`, `![[entity#facet]]`).
2. **The claim graph** — claims/facets/contexts/observers as *visible structure* (context-colored edges, observer badges, facet sub-nodes).
3. **Observer / perspective filter** — a "who believes what" lens over the whole graph and every page.
4. **Belief timeline** — temporal change + contradiction (`valid_from → valid_to`, `superseded_by` chains).
5. **Claim provenance** — source episode, authoring model, confidence ⊥ trust, per-claim.

All surfaces are designed against the *actual* code that exists today on `feat/memory-evolution`:
the SwiftUI `NavigationSplitView` + `AppTab` sidebar (`ContentView.swift`, `SidebarView.swift`),
the `@Observable` ViewModel + `actor APIClient` generic-`get`/`post` pattern, the
`CicadaTheme.entityColor(for:)` / `statusColor(for:)` palette, the `EntityDetailCard` tab card,
and the d3 graph in `WKWebView` whose only Swift↔JS contract is
`webView.evaluateJavaScript("updateGraph(json)")` / `applyFilters` / `setFocus` outbound and
`window.webkit.messageHandlers.cicada.postMessage({type, …})` inbound. **Everything below extends
those seams; it does not rewrite them.** The package builds via `cd app/CicadaApp && swift build`.

---

## 0. Shared data models (one new Swift file: `Models/Claim.swift`)

Every surface reads claims, so they share one model layer. These mirror the CCL claim YAML
(d2-recommendation.md §"The unit: a claim") on the wire as camelCase; all decode defensively
(`decodeIfPresent`) exactly like the existing `Entity` / `GraphNode` / `MediaFeedItem` models, so
an older backend never blanks a view.

```swift
import Foundation

// Who holds a belief. Drives the observer filter + badges. `external:<name>` is
// the high-value media/RSS provenance case (an opaque associated value here so
// we keep the closed core + open tail without losing the name on the wire).
enum Observer: Codable, Hashable, Identifiable {
    case agent
    case rodrigo
    case external(String)           // "external:karpathy-talk" → .external("karpathy-talk")

    var id: String { wire }
    var wire: String {
        switch self {
        case .agent: return "agent"
        case .rodrigo: return "rodrigo"
        case .external(let n): return "external:\(n)"
        }
    }
    init(wire: String) {
        switch wire {
        case "agent": self = .agent
        case "rodrigo": self = .rodrigo
        default:
            self = wire.hasPrefix("external:")
                ? .external(String(wire.dropFirst("external:".count)))
                : .external(wire)
        }
    }
    init(from d: Decoder) throws { self.init(wire: try d.singleValueContainer().decode(String.self)) }
    func encode(to e: Encoder) throws { var c = e.singleValueContainer(); try c.encode(wire) }

    var label: String {
        switch self {
        case .agent: return "Cicada"
        case .rodrigo: return "Rodrigo"
        case .external(let n): return n
        }
    }
    var sfSymbol: String {
        switch self {
        case .agent: return "cpu"
        case .rodrigo: return "person.fill"
        case .external: return "quote.bubble.fill"
        }
    }
}

// epistemic + source_trust are small closed enums with a forward-compat fallback,
// same tolerance pattern as EntityType/.unknown.
enum Epistemic: String, Codable { case explicit, deductive, inductive, abductive, unknown
    init(from d: Decoder) throws { self = Epistemic(rawValue: (try? d.singleValueContainer().decode(String.self)) ?? "") ?? .unknown } }
enum SourceTrust: String, Codable { case userStated = "user_stated", agentExtracted = "agent_extracted", agentReflected = "agent_reflected", external, unknown
    init(from d: Decoder) throws { self = SourceTrust(rawValue: (try? d.singleValueContainer().decode(String.self)) ?? "") ?? .unknown } }

struct Claim: Identifiable, Codable, Hashable {
    let id: String                    // clm_2026-05-05_009
    let text: String
    let subject: String
    let predicate: String
    let object: String
    let objectKind: String            // "node" | "literal"
    let observer: Observer
    let context: String               // engineering|family|… (OPEN; default "general")
    let epistemic: Epistemic
    let sourceTrust: SourceTrust
    let confidence: Double
    let validFrom: String
    let validTo: String?              // nil = currently valid
    let supersededBy: String?
    let supersedes: String?
    let sourceEpisodes: [String]
    let premises: [String]
    let authoredBy: String            // model id or "user" — same vocabulary as Contributor.author

    var isValid: Bool { validTo == nil }

    enum CodingKeys: String, CodingKey {
        case id, text, subject, predicate, object, objectKind, observer, context
        case epistemic, sourceTrust, confidence, validFrom, validTo
        case supersededBy, supersedes, sourceEpisodes, premises, authoredBy
    }
    init(from c: Decoder) throws {
        let k = try c.container(keyedBy: CodingKeys.self)
        id = try k.decode(String.self, forKey: .id)
        text = try k.decode(String.self, forKey: .text)
        subject = try k.decodeIfPresent(String.self, forKey: .subject) ?? ""
        predicate = try k.decodeIfPresent(String.self, forKey: .predicate) ?? ""
        object = try k.decodeIfPresent(String.self, forKey: .object) ?? ""
        objectKind = try k.decodeIfPresent(String.self, forKey: .objectKind) ?? "literal"
        observer = try k.decodeIfPresent(Observer.self, forKey: .observer) ?? .agent
        context = try k.decodeIfPresent(String.self, forKey: .context) ?? "general"
        epistemic = try k.decodeIfPresent(Epistemic.self, forKey: .epistemic) ?? .unknown
        sourceTrust = try k.decodeIfPresent(SourceTrust.self, forKey: .sourceTrust) ?? .unknown
        confidence = try k.decodeIfPresent(Double.self, forKey: .confidence) ?? 0
        validFrom = try k.decodeIfPresent(String.self, forKey: .validFrom) ?? ""
        validTo = try k.decodeIfPresent(String.self, forKey: .validTo)
        supersededBy = try k.decodeIfPresent(String.self, forKey: .supersededBy)
        supersedes = try k.decodeIfPresent(String.self, forKey: .supersedes)
        sourceEpisodes = try k.decodeIfPresent([String].self, forKey: .sourceEpisodes) ?? []
        premises = try k.decodeIfPresent([String].self, forKey: .premises) ?? []
        authoredBy = try k.decodeIfPresent(String.self, forKey: .authoredBy) ?? "unknown"
    }
}
```

**Context palette (one new theme helper, `CicadaTheme.contextColor(_:)`).** Contexts are an open
set, so we hash unknown ones into a stable hue and hard-code the known core to keep the demo legible:

```swift
extension CicadaTheme {
    static func contextColor(_ context: String) -> Color {
        switch context {
        case "engineering":   return Color(hex: 0x14B8A6)   // teal
        case "family":        return Color(hex: 0xEC4899)   // pink
        case "philosophical": return Color(hex: 0xA855F7)   // purple
        case "career":        return Color(hex: 0xF97316)   // orange
        case "cross":         return Color(hex: 0xEAB308)   // gold — the cross-context bridge
        case "general":       return Color(hex: 0x6B7280)   // gray
        default:
            // Stable hue for any open-tail context so the graph never flickers.
            let h = Double(abs(context.hashValue) % 360) / 360.0
            return Color(hue: h, saturation: 0.55, brightness: 0.85)
        }
    }
}
```

**One new APIClient method set** (mirrors the existing generic `get`):

```swift
extension APIClient {
    func fetchClaims(subject: String, includeSuperseded: Bool = false) async throws -> [Claim] {
        let q = includeSuperseded ? "?include_superseded=true" : ""
        let r: ClaimListResponse = try await get("/entities/\(encodedID(subject))/claims\(q)")
        return r.claims
    }
    func fetchClaimTimeline(subject: String, predicate: String, context: String) async throws -> ClaimTimeline {
        let p = predicate.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? predicate
        let c = context.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? context
        return try await get("/entities/\(encodedID(subject))/timeline?predicate=\(p)&context=\(c)")
    }
    func resolveTransclusion(_ ref: String) async throws -> TransclusionPayload {
        let r = ref.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ref
        return try await get("/transclude?ref=\(r)")
    }
}
struct ClaimListResponse: Codable { let claims: [Claim] }
```

---

## 1. Inline transclusion — `![[…]]` rendered inline (HIGHEST DEMO LEVERAGE)

### The syntax (first-class, three forms)

A memory page body can embed another page's content inline, Obsidian-style. We extend the existing
`[[Wikilink]]` (already rendered by `renderedMarkdownAttributed` in `EntityDetailCard.swift`) with a
leading `!` for *embed* and a `claim:` / `#facet` selector:

| Syntax | Meaning | Rendered as |
|---|---|---|
| `![[cicada]]` | embed another entity's generated summary card | a nested, collapsible mini-card (title + current-valid one-liner) |
| `![[rodrigo#engineering]]` | embed *one facet* of an entity | the facet's valid claims only |
| `![[claim:clm_2026-05-05_009]]` | embed a single claim | a claim chip with its provenance footer |

This serves the memory model directly: an entity page can transclude the *claim* it depends on
(provenance you can see in place), or a hub page can transclude its members' facet summaries without
duplicating text — the page stays DRY and the embed always reflects the current-valid belief.

### The view: `TranscludingMarkdownView` (new file `Views/Common/TranscludingMarkdownView.swift`)

Replaces the flat `Text(renderedMarkdownAttributed(...))` inside `EntityDetailCard.renderedMarkdownView`.
It tokenizes the body into a sequence of `.text(AttributedString)` and `.embed(ref:)` segments
(one regex pass for `!\[\[(.+?)\]\]`, reusing the existing wikilink regex machinery for the residual
text), then renders a `VStack` where each embed is an inline `TransclusionCard`. Embeds are:

- **rendered inline** at one indent level, with a thin left accent bar (`CicadaTheme.accent`) and the
  source title in the corner — visually unmistakably "this is embedded from elsewhere";
- **collapsible** (chevron) so deep transclusion doesn't blow up the card;
- **depth-guarded**: a `depth` parameter (max 2) and a `visited: Set<String>` passed down so
  `A ![[B]]` / `B ![[A]]` cycles render a `"↻ cyclic embed"` stub instead of recursing forever;
- **click-through**: tapping the embed's title calls `graphVM.selectEntity(id:)` (the exact existing
  hook the graph node-click uses), swapping the detail card to that entity.

```swift
struct TranscludingMarkdownView: View {
    let body: String
    var depth: Int = 0
    var visited: Set<String> = []
    @Environment(GraphViewModel.self) private var graphVM

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            ForEach(Array(segments.enumerated()), id: \.offset) { _, seg in
                switch seg {
                case .text(let attr):
                    Text(attr).font(CicadaTheme.bodyFont).textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                case .embed(let ref):
                    if depth >= 2 || visited.contains(ref) {
                        cyclicStub(ref)
                    } else {
                        TransclusionCard(ref: ref, depth: depth + 1,
                                         visited: visited.union([ref]))
                    }
                }
            }
        }
    }
    // segments computed by one regex pass over `body` (see EntityDetailCard's existing
    // renderedMarkdownAttributed for the NSRegularExpression pattern to reuse).
}
```

`TransclusionCard` calls `await APIClient.shared.resolveTransclusion(ref)` on appear and renders the
returned `TransclusionPayload` (title + a short body or a single `Claim`). For a `claim:` ref it shows
the claim chip from §5; for an `entity#facet` ref it renders that facet's valid claims; for a bare
entity it shows the generated one-liner.

### The API it needs

```
GET /transclude?ref=<urlencoded>     → TransclusionPayload
```

```jsonc
// TransclusionPayload (camelCase wire)
{
  "kind": "entity" | "facet" | "claim",
  "ref": "rodrigo#engineering",
  "title": "Rodrigo · engineering",
  "summary": "Values shipping fast and iterating.",   // generated card line, for entity/facet
  "claims": [ /* Claim[] for facet/claim kinds; [] otherwise */ ],
  "resolved": true                                     // false → render a soft "missing embed" stub
}
```

Backend implementation is thin: parse the ref, dispatch to the same `parse_claims` / facet reader the
`/entities/{id}` route already uses, return the current-valid slice. **Demo payoff:** open `rodrigo.md`,
see `![[cicada#engineering]]` render as a live nested card; edit the embedded page, reopen — the embed
reflects the change. This is the single most visually-novel surface and reads instantly in a thesis
defense screenshot.

---

## 2. The claim graph — claims/facets/contexts/observers as visible structure

This upgrades the existing d3 `/graph` view *without* breaking its contract. Three additive visual
layers, all driven by new optional fields on the existing `links`/`nodes` payload and rendered by
small additions to `graph.js`'s `draw()` (which today strokes every link flat `#666`).

### (a) Context-colored edges

`graph_edges.yaml` already gains an optional `context` per CCL. The `/graph` payload adds `context`
and `claimId` to each link; `graph.js` colors the stroke via a JS mirror of `contextColor()` instead
of the hard-coded `"#666"`:

```js
// graph.js, inside the link loop (replaces `ctx.strokeStyle = "#666";`)
ctx.strokeStyle = CONTEXT_COLORS[l.context] || "#666";
```

A floating **context legend** (new SwiftUI overlay `ContextLegend`, sibling to the existing
`ZoomControls` in `GraphContainerView`) lists each active context with its swatch and a toggle that
calls `applyFilters` with a `contexts` array — reusing the *exact* existing filter pipeline
(`viewModel.filterJSON` → `applyFilters(json)`), just adding a `contexts` key the JS `rebuildVisible`
honors. Edges whose context is filtered out drop, so "show me only the engineering subgraph" is one tap.

### (b) Observer badges on nodes

The `/graph` node payload gains `observers: [String]` (the distinct observer wire-strings asserting
claims about that subject). `graph.js` draws a tiny badge cluster at the node's upper-right in `draw()`
(it already computes `nodeRadius` and per-node screen position) — a filled dot per observer using a
fixed 3-color key (Cicada = accent, Rodrigo = blue, external = pink, matching `Observer` symbols).
A node with an `external:` observer is the "someone else told me this" signal, visible at a glance.

### (c) Facet sub-nodes

When a subject has claims in ≥2 contexts, the `/graph` payload emits the parent node **plus** one
small `isFacet:true` satellite node per context (`id: "rodrigo#engineering"`, `parentId: "rodrigo"`,
`context: "engineering"`), linked to the parent by a short `facetOf` edge. `graph.js` gives facet
nodes a smaller radius and the context color as *fill* (not just edge), and pins them near the parent
via the existing hub-gravity machinery (`hubGravityForce`) re-parameterized for `parentId`. Tapping a
facet node posts `{type:"nodeClicked", id:"rodrigo#engineering"}` — the existing
`selectEntity(id:)` path, which the detail card now resolves to a facet view (§3). **No new message
type, no new Swift handler** — the facet id flows through the same channel a normal node click does.

### The API it needs

`GET /graph` extends its existing JSON (all fields optional/defaulted, decode-tolerant per
`GraphNode.init(from:)`):

```jsonc
{
  "nodes": [
    { "id":"rodrigo", "name":"Rodrigo", "type":"person", /* …existing… */
      "observers": ["rodrigo","agent","external:karpathy-talk"],
      "contexts": ["engineering","family","cross"] },
    { "id":"rodrigo#engineering", "name":"engineering", "type":"person",
      "isFacet": true, "parentId":"rodrigo", "context":"engineering",
      "confidence":0.8 /* drives radius */ }
  ],
  "links": [
    { "source":"rodrigo", "target":"cicada", "label":"builds",
      "context":"engineering", "claimId":"clm_2026-05-05_001" },
    { "source":"rodrigo#engineering", "target":"rodrigo", "label":"facetOf",
      "context":"engineering" }
  ]
}
```

`GraphNode` / `GraphEdge` (in `Models/Entity.swift`) gain matching optional fields decoded with
`decodeIfPresent`. **Demo payoff:** the graph stops being a uniform gray hairball and becomes a
*colored* belief structure — you can literally see the engineering subgraph, the facet satellites
around `rodrigo`, and the external-observer badge on a claim Karpathy made.

---

## 3. Observer / perspective filter — "who believes what"

Two coordinated surfaces realize the observer/perspective philosophy: a global filter and a per-page
perspective switch.

### (a) Global observer filter (graph-level)

A new `ObserverFilterBar` overlay (sibling to `FilterButton` in `GraphContainerView`) offers a
segmented control: **All · Cicada · Rodrigo · External**. Selecting one calls `applyFilters` with an
`observers` array; `graph.js` `rebuildVisible` keeps only nodes/edges with a matching observer in
their claim set, *dimming* (not deleting) the rest via the existing focus-alpha mechanism so the
contrast reads as "this is the slice Rodrigo personally asserts vs. what the agent inferred." This is
the headline epistemics demo: toggle to **Cicada-only** and watch the agent's *inferred* beliefs
(abductive bridges, agent-reflected generalizations) light up distinct from Rodrigo's stated facts.

### (b) Per-page perspective switch (`EntityDetailCard` new tab)

`EntityDetailCard`'s `DetailTab` enum (today `.content` / `.history`) gains `.perspectives`. The tab
shows the subject's claims **grouped by observer**, each group a labeled section
(`Observer.label` + `sfSymbol` badge) with the claims as chips (§5). Where two observers disagree on
the same `(predicate, context)`, the card draws a **divergence callout** ("Rodrigo asserts X; Cicada
inferred Y") — the literal "who believes what" contradiction-across-observers view. Data comes from
`fetchClaims(subject:)` grouped client-side by `claim.observer`.

### The API it needs

- Reuses `GET /entities/{id}/claims` (§0).
- `GET /graph` gains a top-level `observers: [String]` roster (distinct observers in the graph) so the
  filter bar can populate its segments without a separate call.

---

## 4. Belief timeline — temporal change + contradiction

The flagship C3 demo: a single belief's life, `valid_from → valid_to`, with `superseded_by` chains
drawn as a vertical thread. The existing `EntityDetailCard` history tab shows *file commits*; this is
different — it shows *one claim line's* temporal evolution as a belief.

### The view: `BeliefTimelineView` (new file `Views/Graph/BeliefTimelineView.swift`)

Reachable two ways: (1) clicking any claim chip's clock icon (§5) opens it for that claim's
`(subject, predicate, context)` key; (2) a new `.timeline` tab on `EntityDetailCard` lists the
subject's *contested* keys (any `(predicate, context)` with ≥2 claims over time) and drills in.

It renders a **vertical superseded-chain**: each claim is a row with a colored left rail; the
currently-valid claim (`validTo == nil`) is solid green at the top, each superseded claim below it
fades and shows a strikethrough on its object plus its closed window `[valid_from → valid_to]`. A
connecting line with a downward "superseded by" chevron links each closed claim to its replacement.
This reuses the existing history-tab timeline geometry (the `Circle` + `Rectangle` rail in
`EntityDetailCard.historyTab`) almost verbatim — only the row content changes.

A compact horizontal **validity-bar** strip at the top draws each claim as a segment on a shared time
axis (`valid_from` → `valid_to`, open claims extend to "now"), context-colored — so contradiction reads
as "the orange segment ends exactly where the green one begins." That single image *is* the bi-temporal
story.

```swift
struct BeliefTimelineView: View {
    let subject: String
    let predicate: String
    let context: String
    @State private var timeline: ClaimTimeline?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            if let t = timeline {
                ValidityBarStrip(claims: t.claims)              // horizontal time axis
                ForEach(t.claims) { claim in                     // newest→oldest superseded chain
                    SupersededRow(claim: claim, isCurrent: claim.isValid)
                }
            } else { ProgressView() }
        }
        .task {
            timeline = try? await APIClient.shared
                .fetchClaimTimeline(subject: subject, predicate: predicate, context: context)
        }
    }
}
```

### The API it needs

```
GET /entities/{id}/timeline?predicate=<p>&context=<c>   → ClaimTimeline
```

```jsonc
// ClaimTimeline — claims for one (subject,predicate,context) key, newest first,
// including superseded ones (this is the historical view, so valid_to != null are included).
{
  "subject": "cicada", "predicate": "uses", "context": "engineering",
  "claims": [
    { "id":"clm_2026-05-05_009", "object":"sqlite-vec", "validFrom":"2026-05-05",
      "validTo":null, "supersedes":"clm_2026-01-15_002", "authoredBy":"gpt-5.4-mini", /* …full Claim… */ },
    { "id":"clm_2026-01-15_002", "object":"postgres", "validFrom":"2026-01-15",
      "validTo":"2026-05-05", "supersededBy":"clm_2026-05-05_009", "authoredBy":"gpt-5.4-mini" }
  ]
}
```

Backend builds this from the page's claims fence filtered by `(predicate, context)` — the same
mechanical key Sleep Stage 3 already uses to supersede. **Demo payoff:** "what did Cicada use before
SQLite?" becomes a *visible thread* — Postgres in orange ending on 2026-05-05, SQLite in green
beginning the same day, the supersede chevron between them, each annotated with the model that retired
the belief.

---

## 5. Claim provenance — source episode, authoring model, confidence ⊥ trust

The atomic unit of the whole demo: a **`ClaimChip`** view used everywhere above (transclusion, the
perspective tab, the timeline rows). It makes per-claim provenance *always visible*, never hidden
behind a click.

### The view: `ClaimChip` (new file `Views/Common/ClaimChip.swift`)

A claim renders as a rounded card:

- **Body line**: the claim `text`, with `[[wikilinks]]` highlighted (reuse `renderedMarkdownAttributed`).
- **Provenance footer** (a single `HStack` of pills):
  - **observer badge** — `Observer.sfSymbol` + label, colored by observer (the "who").
  - **context pill** — `CicadaTheme.contextColor(claim.context)` swatch + name.
  - **trust pill** — `source_trust` (`user_stated` = solid green, `agent_reflected` = hollow amber, etc.).
  - **confidence ring** — a tiny circular gauge for `confidence`, *separate* from trust (the two
    orthogonal axes the architecture insists on — a low-confidence user-stated fact and a
    high-confidence agent guess look visibly different).
  - **authored-by pill** — the model id or `user`, reusing the existing author-badge styling from
    `EntityDetailCard.historyTab` (purple for a model, blue for `user`) so attribution is consistent
    app-wide with the Contributors view.
  - **source episode** — `ep_…` chip; tapping it is the provenance jump (future: opens the raw episode).
  - **clock icon** — opens the §4 timeline for this claim's key.
- **superseded styling**: if `claim.validTo != nil` the whole chip dims and the object renders with a
  strikethrough + a `"superseded \(validTo)"` caption — so a stale belief is never mistaken for current.

```swift
struct ClaimChip: View {
    let claim: Claim
    var onOpenTimeline: (() -> Void)? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(claim.text).font(CicadaTheme.bodyFont)
                .strikethrough(!claim.isValid)
                .foregroundStyle(claim.isValid ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
            HStack(spacing: 6) {
                ObserverBadge(claim.observer)
                ContextPill(claim.context)
                TrustPill(claim.sourceTrust)
                ConfidenceRing(claim.confidence)
                AuthorPill(claim.authoredBy)                  // same styling as Contributors
                if let ep = claim.sourceEpisodes.first { EpisodePill(ep) }
                Spacer()
                if let onOpenTimeline {
                    Button(action: onOpenTimeline) { Image(systemName: "clock") }
                        .buttonStyle(.plain).foregroundStyle(CicadaTheme.textSecondary)
                }
            }
        }
        .padding(CicadaTheme.spacingMD)
        .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
        .opacity(claim.isValid ? 1 : 0.6)
    }
}
```

### The API it needs

`ClaimChip` is pure-render over a `Claim` — no dedicated endpoint; it consumes whatever
`fetchClaims` / `fetchClaimTimeline` / `resolveTransclusion` already returned. This is why §0's `Claim`
model carries the full provenance set: every surface that shows a claim shows its provenance for free.

---

## Build / wiring summary (what actually changes in the app target)

| New / changed file | Kind | Touches |
|---|---|---|
| `Models/Claim.swift` | new | `Claim`, `Observer`, `Epistemic`, `SourceTrust`, `ClaimTimeline`, `TransclusionPayload` |
| `Theme/CicadaTheme.swift` | +helper | `contextColor(_:)` |
| `Services/APIClient.swift` | +methods | `fetchClaims`, `fetchClaimTimeline`, `resolveTransclusion` (reuse generic `get`) |
| `Views/Common/ClaimChip.swift` | new | provenance chip (§5) — used by §1,§3,§4 |
| `Views/Common/TranscludingMarkdownView.swift` | new | inline transclusion (§1) |
| `Views/Graph/EntityDetailCard.swift` | +tabs | `.perspectives` + `.timeline` cases; swap `renderedMarkdownView` to `TranscludingMarkdownView`; facet-id awareness |
| `Views/Graph/BeliefTimelineView.swift` | new | belief timeline (§4) |
| `Views/Graph/ContextLegend.swift`, `ObserverFilterBar.swift` | new | graph overlays (§2,§3), siblings to existing `ZoomControls`/`FilterButton` |
| `Resources/graph/graph.js` | +draw layers | context-colored strokes, observer badges, facet sub-nodes (all behind optional fields) |
| `ViewModels/GraphViewModel.swift` | +filter keys | `contexts`, `observers` in `filterJSON` (existing `applyFilters` pipeline) |

**New backend endpoints** (all additive; the markdown+git filesystem stays the single source of truth):
`GET /entities/{id}/claims`, `GET /entities/{id}/timeline`, `GET /transclude`, plus optional fields on
the existing `GET /graph`. Every Swift model decodes the new fields with `decodeIfPresent`, so the app
**compiles and runs against today's backend** (empty claims → views show graceful empty states) and
lights up incrementally as the CCL endpoints land — the same forward-compat discipline the codebase
already follows for `GraphNode`/`MediaFeedItem`.

**Compile guard:** none of these introduce a new dependency, a new target, or a resource that isn't a
`.swift` file or an edit to the existing bundled `graph.js`; `swift build` continues to work unchanged.
