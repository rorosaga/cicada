# Inline Markdown Transclusion for Cicada

**Status:** Research — 2026-06-17  
**Scope:** Syntax design, rendering pipeline, memory-model fit, demo value

---

## TL;DR

Cicada should adopt a two-sigil transclusion system modelled on Obsidian's `![[…]]` but extended
with a claim-ID selector (`![[entity#claim:clm_id]]`) and a context-filtered embed
(`![[entity?context=engineering]]`). Rendering is handled in the existing markdown-in-WKWebView
pipeline: the FastAPI layer resolves every `![[…]]` reference server-side before handing HTML to
the WebView, injecting the transcluded content as a collapsible `<details>` block with a styled
"Transcluded from: …" header. Recursion is capped at depth 3; cycle detection uses a per-render
visited-set so self-referential or mutually-referential pages degrade gracefully to a plain link.
For the companion app this is the highest-yield demo feature: the graph node for an entity now
*shows the claims that back it*, not just its name — making the memory structure viscerally visible.

---

## How Others Do It

### Obsidian — `![[…]]` (production reference)

Obsidian is the closest prior art and the most relevant, since Cicada entities already live in
Obsidian-compatible markdown.

| Syntax | What it transclubes |
|--------|---------------------|
| `![[note]]` | Full page |
| `![[note#Heading]]` | Only the section under that heading |
| `![[note^block-id]]` | One block (paragraph/list item) — requires the target to carry `^block-id` at its end |
| `![[image.png\|300]]` | Inline image with width parameter |
| `![[doc.pdf#page=3]]` | PDF page |

**Rendering:** In reading view, Obsidian replaces the `![[…]]` token with the rendered HTML of the
target content, injected inline. The resolution is dynamic (live re-render on file change).

**Cycle handling:** Obsidian does *not* fully resolve circular embeds — it can freeze on PDF export
with mutual recursion. Community tools (e.g. `obsidian-pandoc`) recommend replacing a cycle with a
plain link. The recommended strategy in the community: replace any embed that would re-introduce an
already-visited page with `[[link]]` (no `!`).

**Portability concern:** The `![[…]]` syntax is Obsidian-specific and does not survive pandoc or
standard markdown parsers. Since Cicada's pages live on disk as plain markdown, any tool other
than Cicada/Obsidian will render `![[…]]` as raw text. This is an acceptable trade-off at
personal-scale — the companion app is the canonical renderer.

---

### Claude Code — `@file` (eager context injection)

Claude Code's `@path` (e.g. `@src/auth.ts`, `@CLAUDE.md`) is a **prompt-time** reference, not a
persistent document feature. When you type `@file` in a message, the CLI reads the file off disk
and concatenates its contents into the prompt before the API call. Key characteristics:

- **Eager, one-shot:** the full file is injected at message construction time.
- **Line-range variant:** `@file.ts#5-10` (noted in GitHub issues) allows partial injection by
  line number, but this is not yet in stable docs.
- **No recursive resolution:** the injected text is not re-scanned for further `@` references.
- **Not a persistent notation:** `@file` is ephemeral in the prompt; it does not persist in any
  stored document.

**Takeaway for Cicada:** The "at-mention" UX is good inspiration for a *chat-layer* reference
(when the Bookworm MCP answers a query it could surface `@entity` as a navigable link in the
companion app response pane), but it is not the right model for a durable in-page transclusion
syntax.

---

### AsciiDoc `include::` — most powerful, lowest portability

AsciiDoc's include directive is the richest in the space:

```asciidoc
include::entities/cicada.adoc[]               // full file
include::entities/cicada.adoc[lines=1..20]    // line range
include::entities/cicada.adoc[tag=summary]    // content between // tag::summary[] markers
include::entities/cicada.adoc[tags=summary;rationale]  // multiple tags
```

**Cycle detection:** processed at parse time; the include chain is tracked as a visited-set;
cycles are detected and an error is emitted (no freeze).

**Why not adopt wholesale:** AsciiDoc `.adoc` format breaks Obsidian-compatibility and the entire
Cicada Markdown substrate. The *concepts* (line ranges, tag regions, visited-set cycle detection)
are worth importing into the design.

---

### PyMdown Snippets (`--8<--`) and MkDocs variants

Used for technical documentation, not personal knowledge graphs. Syntax: `--8<-- "path/to/file"`
or `--8<-- "file:tag"`. Processed at build time; no live resolution. Not relevant to Cicada's
runtime-render model.

---

### SilverBullet — `![page](page)` and `![page#header](page#header)`

SilverBullet (a local-first Markdown wiki) uses a standard-image-like syntax for transclusion:
`![page name](page name)`. Header-gated embeds: `![page#Heading](page#Heading)`. Renders inline
in the web editor. No documented cycle-detection mechanism in the public docs. Relevant as another
deployed personal-knowledge-tool, but the double-path redundancy in its syntax (`![A](A)`) is
awkward to type and read.

---

### Hercule — `:[]()` inline transclusion for Markdown

[Hercule](https://github.com/jamesramsay/hercule) extends standard inline-link syntax:
`:[][path/to/file.md]` — the leading colon signals transclusion. Recursive: the included file is
itself scanned for further transclusion links. Cycle detection uses the URL chain as a
visited-set. Depth limit: not documented explicitly; relies on cycle detection to prevent
infinite recursion.

---

### Markdown Preview Enhanced — depth limit of 3

MPE (VS Code/Atom extension) implements file transclusion with an explicit **maximum recursion
depth of 3** and visited-path cycle detection. This is the most cited practical implementation
of a bounded transclusion depth.

---

## Recommended Cicada Transclusion Design

### 1. Syntax

Adopt `![[…]]` as the base sigil (Obsidian-compatible, visually distinct from wikilinks `[[…]]`).
Extend it with three Cicada-specific selectors:

| Syntax | Resolves to |
|--------|-------------|
| `![[entity-id]]` | Full rendered entity card (frontmatter strip + body + active claims summary) |
| `![[entity-id#heading]]` | The section under `## heading` in that entity page |
| `![[entity-id#claim:clm_YYYY-MM-DD_NNN]]` | A single claim rendered as a blockquote card |
| `![[entity-id?context=engineering]]` | All claims for that entity where `context = engineering` |
| `![[entity-id#facet:engineering]]` | The `## facet: engineering` sub-section of the page |

**In-page authoring example** (inside `entities/cicada.md`):

```markdown
## Overview

Cicada is a personal memory system. Its substrate is described below:

![[sqlite-vec#claim:clm_2026-05-05_009]]

The graph layer is documented at:

![[memory-architecture#facet:engineering]]

Related people:
![[raul-perez-pelaez?context=academic]]
```

**Block ID convention for non-claim blocks:** any paragraph or list item can be given a stable ID
by appending `^block-id` at the end of the last line (matching Obsidian's convention exactly):

```markdown
Cicada's awake cycle captures episodes without LLM processing. ^awake-cycle-def
```

Then embedded elsewhere as `![[cicada#^awake-cycle-def]]`.

---

### 2. Rendering Pipeline (Server-Side Resolution in FastAPI)

The existing entity-detail endpoint (`GET /entities/{id}`) already reads the markdown page and
returns it as a rendered string (or passes it to the WKWebView for local rendering). Transclusion
resolution is inserted as a **pre-render pass** in the Python layer:

```
GET /entities/{id}  →  read_entity_markdown(id)
                    →  resolve_transclusions(content, visited={id}, depth=0)
                    →  markdown_to_html(resolved_content)
                    →  return HTML to WKWebView
```

**`resolve_transclusions(content, visited, depth)` algorithm:**

1. Find all `![[…]]` tokens via regex.
2. For each token, parse the `entity-id`, optional `#heading`/`#claim:id`/`#facet:name`/`?context=` selector.
3. **Cycle check:** if `entity-id` in `visited`, replace token with a plain wikilink `[[entity-id]]`
   (degrade to link, never embed). Log a warning.
4. **Depth check:** if `depth >= 3`, replace token with plain link. This is the MPE-proven safe
   limit for personal-scale graphs.
5. Otherwise: load the target page, extract the relevant content slice per selector, recursively
   call `resolve_transclusions(slice, visited | {entity-id}, depth + 1)`.
6. Wrap the resolved slice in a `<details class="transclusion">` block with a styled header.

**Selector extraction logic:**

- `#heading` — scan the page for `## {heading}` (case-insensitive), include all lines until the
  next `##`-level heading or end-of-file.
- `#claim:clm_id` — parse the `claims` fenced block (CCL schema), find the claim by `id:`, render
  as a structured claim card (text + predicate + observer + confidence badge).
- `#facet:name` — find `## facet: {name}` section, same slice logic as heading.
- `?context=X` — parse claims block, filter by `context: X`, render as a compact list of
  claim-text strings.
- `#^block-id` — scan the body for `^block-id` suffix, return that paragraph/list item.

**Rendered HTML output** (per embedded block):

```html
<details class="cicada-transclusion" open>
  <summary class="transclusion-source">
    <a href="/entities/sqlite-vec" class="entity-link">sqlite-vec</a>
    <span class="selector">#claim:clm_2026-05-05_009</span>
  </summary>
  <blockquote class="claim-card">
    <p>"Cicada uses sqlite-vec for its derived semantic index."</p>
    <footer>
      <span class="predicate">uses</span> ·
      <span class="observer">agent</span> ·
      <span class="confidence">0.95</span> ·
      <span class="context">engineering</span>
    </footer>
  </blockquote>
</details>
```

The `<details open>` default shows the content expanded; clicking the `<summary>` collapses it.
This keeps the entity page scannable when there are many transclusions.

---

### 3. WKWebView Integration

The companion app's existing `WKWebView`-based entity detail view receives the pre-resolved HTML
from the FastAPI endpoint. No WKWebView-side changes are needed for basic transclusion rendering —
all resolution happens server-side.

For **live navigation** (clicking "sqlite-vec" link inside a transcluded block should open that
entity in the app), the existing `window.webkit.messageHandlers.entityTapped.postMessage(entityId)`
JavaScript bridge is extended to fire on clicks inside `.cicada-transclusion a.entity-link`.
The CSS class targets are already in scope; add one line to the existing `graph.js` event-listener
block:

```javascript
document.addEventListener('click', e => {
  const link = e.target.closest('a.entity-link');
  if (link) {
    e.preventDefault();
    window.webkit.messageHandlers.entityTapped
          .postMessage(link.dataset.entityId);
  }
});
```

For **partial renders in the graph view** (the d3 node popover that appears when you tap a node),
the same resolved HTML can be injected into the existing popover `innerHTML`, since popover content
is already HTML-rendered markdown. Transclusions inside a node popover are depth-capped at 1 (the
popover itself counts as depth 0; transcluded content is not further expanded, to keep popovers
compact).

---

### 4. How Transclusion Serves the Memory Model

Transclusion is not cosmetic — it directly supports three core Cicada thesis claims:

**a) Claims are the atomic unit of knowledge (CCL)**  
Without transclusion, the claim schema lives invisibly in a fenced YAML block that users never
encounter in normal reading. With `![[entity#claim:clm_id]]` you can surface a specific claim
*inside the narrative of a related entity page*, making the claim-as-unit visible and legible.
Example: the `cicada.md` page transcluding `![[sleep-cycle#claim:clm_2026-04-10_003]]` (which
asserts "Sleep cycle runs nightly at 02:00") makes the dependency explicit and traceable in the
page you are reading.

**b) Observer/context identity**  
`![[rodrigo?context=academic]]` embedded in `raul-perez-pelaez.md` surfaces only the claims
about Rodrigo that were formed in an academic context — from the supervisor's perspective page.
This demonstrates the `(observer, context, subject)` keying *in the rendered document*, not just
in the YAML.

**c) Temporal provenance**  
A claim transcluded with `#claim:clm_id` renders its `valid_from` / `valid_to` / `superseded_by`
fields in the card footer. If the claim has been closed (`valid_to: 2026-04-30`), the card
renders with a strikethrough and a "superseded by: clm_…" link. This makes temporal contradiction
visible inline without navigating to a separate history view.

---

### 5. Companion App Demo Value

This is where transclusion most directly serves the new mandate ("the more we can show through
the companion app, the better").

**Demo moment 1 — The living entity page**  
Open `cicada.md` in the entity detail view. The page body contains `![[sleep-cycle#facet:engineering]]`
and `![[rodrigo#claim:clm_2026-05-05_009]]`. The rendered view shows the entity's own narrative
with live embedded slices from two other entities, each with a collapsible handle and a "from:
sleep-cycle" attribution. A reviewer watching a 3-minute thesis demo sees the graph *as structured
knowledge*, not as a folder of notes.

**Demo moment 2 — Claim provenance inline**  
The supervisor entity page (`raul-perez-pelaez.md`) transclubes `![[thesis#claim:clm_2026-06-01_001]]`
(asserts "Thesis defended on 2026-06-17"). The claim card shows `observer: rodrigo`, `source_trust:
user_stated`, `confidence: 1.0`. This single inline block demonstrates observer identity, source
provenance, and confidence scoring simultaneously.

**Demo moment 3 — Contradiction made visible**  
Entity page for a tool (`storage-backend.md`) transclubes two claims:
- `![[cicada#claim:clm_2026-01-10_002]]` → "uses: postgres" (valid_to: 2026-03-15, superseded)
- `![[cicada#claim:clm_2026-03-15_007]]` → "uses: sqlite-vec" (currently valid)

The first renders with strikethrough + "superseded" badge; the second renders as active. The
temporal contradiction that drove belief revision is legible in the page — without opening a
diff view.

**Demo moment 4 — d3 graph node popover**  
Clicking a node in the force-directed graph fires the node-tap handler, which opens a popover
showing the entity's narrative with transclusions rendered (depth 1 only). The graph is no longer
just colored dots — it shows the *content* of the memory, selectively expanded. This is the
single highest-impact UI improvement for the thesis presentation without requiring a new screen.

---

### 6. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| **Circular embeds freeze the render** | Visited-set cycle detection; degrade to plain link at cycle boundary |
| **Deep nesting makes pages unreadable** | Hard depth cap = 3; default `<details>` collapsed at depth ≥ 2 |
| **Stale transclusion after target is deleted** | FastAPI resolver returns a styled error block: `⚠ [[entity-id]] not found`; never a silent gap |
| **Performance: resolving many embeds on page open** | Server-side resolution is synchronous Python (fast for personal scale, <1,882 entities). If a page has >10 transclusions, batch-resolve and cache the HTML with a 60s TTL keyed by `(entity_id, mtime_hash)` |
| **Obsidian portability: `![[…]]` renders as raw text in other parsers** | Acceptable trade-off at personal scale; if portability matters, the `obsidian-export` crate renders transclusions to flat Markdown for export |
| **Author confusion: who wrote the transcluded content?** | The `<details>` header carries `Cicada-Author` attribution from the source page's `git blame`; provenance is not obscured by embedding |
| **Selector drift: renamed headings break `#heading` refs** | Sleep cycle validates all `![[…]]` refs on every cycle; emits a `broken-transclusion` nudge if a selector no longer resolves. Same logic as Obsidian's unresolved-link detection |

---

### 7. What NOT to Implement (Scope Boundary)

- **Write-through transclusion** (editing the embedded content in one place propagates to the
  source): too complex for thesis scope. Transclusion is read-only embed.
- **Query-based live transclusion** (e.g. `![[query:type=tool AND context=engineering]]`): the
  `?context=X` selector covers the most useful case. Full query transclusion is a post-MVP feature.
- **Cross-repo transclusion**: all entities live in one `memory/` repo. No remote refs.
- **Image/PDF/audio embed**: Cicada pages are text-only; the Obsidian image/PDF syntax is not
  needed here.

---

## Summary Table

| System | Sigil | Partial embed | Cycle detection | Depth limit | Runtime |
|--------|-------|---------------|-----------------|-------------|---------|
| Obsidian | `![[…]]` | `#heading`, `^block` | Partial (freeze risk) | None documented | Live |
| AsciiDoc | `include::[]` | lines, tags | Yes (visited-set) | None (relies on cycle det.) | Build |
| Claude Code | `@file` | `#line-range` (experimental) | N/A (one-shot) | N/A | Prompt-time |
| SilverBullet | `![p](p)` | `#header` | Not documented | Not documented | Live |
| MPE (VS Code) | `@import` / `![](!)` | file only | Visited-set | Depth = 3 | Live |
| **Cicada (proposed)** | `![[…]]` | `#heading`, `#claim:id`, `#facet:name`, `?context=X`, `#^block` | Visited-set (server-side) | **3** | Server-side pre-render |
