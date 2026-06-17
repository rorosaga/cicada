# M5 Prep — UX Redesign Proposal (palette + nav)

**Status:** DESIGN ONLY. No code in this doc is applied yet. This is the spec the M5
implementation pass will execute against.

**Problem brief (from Rodrigo):** the current dark theme reads flat and the 8 entity-node
colors look muted/pastel — some blend into the background. We want a *darker, more
deliberate* base, entity colors that **pop** with better contrast, anchored in
**studied, established dark-UI palettes**, plus **clearer, convention-aligned nav names**
and consistent per-page headers.

**Two hard constraints that shaped every choice below:**
1. The d3 graph `<canvas>` is **transparent** (`Resources/graph/index.html` → `background: transparent`),
   so every node sits directly on `CicadaTheme.background`. Node legibility is governed
   entirely by node-fill-vs-background contrast. Darkening the base is the single highest-leverage
   move for "colors that pop."
2. The 8 entity colors + the context colors are **mirrored in two files** that MUST stay
   byte-identical: `Theme/CicadaTheme.swift` and `Resources/graph/graph.js`
   (`typeColors`, `CONTEXT_COLORS`, `OBSERVER_BADGE_COLORS`, plus the `rgba(18,18,22,…)`
   tooltip fills and `#666` edge default). Any hex change here is a two-file change.

---

## Research basis

Surveyed, established dark-UI systems and the principle each contributes:

| Source | What we borrow |
|---|---|
| **Radix Colors** (dark scales, 12-step) | A *base is not one color* — use a 3–4 step elevation ramp (app bg → panel → card → hover) so surfaces read as depth, not noise. Steps 1–3 = backgrounds, 11–12 = text. |
| **Catppuccin Mocha** | A genuinely dark base (`#1E1E2E`) with a *slight cool/violet cast* rather than pure neutral grey; vivid-but-harmonized accent hues that hold saturation on dark. |
| **Tokyo Night** | Deep desaturated-navy base (`#1A1B26`); accents are bright but slightly muted-blue-shifted so nothing vibrates. |
| **GitHub Dark Dimmed** | Calm, low-eye-strain dark that still passes AA; the "dimmed" canvas (`#22272E`) proves you don't need pure black for depth — elevation + border does the work. |
| **One Dark** (Atom) | The canonical "8 syntax hues on dark" set — proves blue/purple/green/teal/red/yellow/orange/grey can all coexist and stay mutually distinct on a `#282C34`-class base. |
| **Linear** | Near-black base, single restrained accent, *everything else is greyscale + type weight*; chrome recedes so content/graph dominates. |
| **WCAG 2.1 AA** | Body/label text must clear **4.5:1** vs its background; large/secondary text **3:1**. All text tiers below are checked against the darkest surface they appear on. |

**Synthesis chosen:** a Catppuccin/Tokyo-Night-style **cool near-black base with a faint
violet cast**, a **Radix-style 4-step elevation ramp**, **Linear-style greyscale chrome**,
and **One-Dark-class saturated-but-harmonized** entity hues. The base goes *darker and
slightly cooler* than today's flat warm `#1A1A1A`; the entity hues go *one notch more
saturated/brighter* (toward Tailwind-400, away from muted-500) so they pop on the darker bg.

---

## 1. Core palette (background tiers, text, accent, borders)

Today's base is a flat warm grey `#1A1A1A` with a single near-flat surface ramp
(`#222 → #2A2A → #2E2E`). Replacing it with a darker, cooler, **violet-cast** ramp:

### Background / surface elevation ramp

| Token | Current | **Proposed** | Role | Note |
|---|---|---|---|---|
| `background` | `#1A1A1A` | **`#0E0F14`** | App canvas / graph backdrop | Darker + faint cool cast. Max contrast under nodes. |
| `surface` | `#222222` | **`#16171D`** | Panels, sidebar fill, cards | +1 elevation step. |
| `surfaceHover` | `#2A2A2A` | **`#1D1F26`** | Row/card hover | Perceptible but quiet lift. |
| `surfaceElevated` | `#2E2E2E` | **`#23252E`** | Popovers, detail cards, modals | Top of the ramp. |
| `border` | `#333333` | **`#262A33`** | Default hairline divider | Cooler, slightly stronger so cards read as cards on the darker bg. |
| `borderLight` | `#444444` | **`#363B47`** | Emphasized/active border | For selected/focused edges. |

Each step is a clear, ~6–10 luminance lift over the previous — Radix-style depth without
banding. The faint violet/blue cast (`…14`, `…1D`, `…2E` blue channel raised) is the
Catppuccin/Tokyo-Night signature that reads "intentionally dark" vs "grey turned down."

### Text tiers (AA-checked against the darkest surface they sit on, `#0E0F14`)

| Token | Current | **Proposed** | Contrast vs `#0E0F14` | Verdict |
|---|---|---|---|---|
| `textPrimary` | `#F5F5F5` | **`#ECEDF2`** | ~16.5:1 | AAA. Titles, body. Slightly softened off pure-white to reduce halation on the darker bg. |
| `textSecondary` | `#999999` | **`#9BA1AE`** | ~6.9:1 | AA (passes 4.5:1). Subtitles, labels, captions. *Today's `#999` already passes; we keep parity + cool it.* |
| `textTertiary` | `#666666` | **`#6B7180`** | ~3.6:1 | Decorative/disabled only (passes 3:1 large-text floor, not 4.5:1 — never use for primary reading text). Footer "Cicada" wordmark, faint metadata. |

### Accent

| Token | Current | **Proposed** | Note |
|---|---|---|---|
| `accent` | `#7C8FFF` | **`#8896FF`** (keep `#7C8FFF` acceptable) | The existing periwinkle is good and on-brand; nudge ~one notch brighter so it pops on the darker base. Used for selection, active nav icon, badges, `agent` observer, `clarification` inbox, `active` status. Contrast vs `#0E0F14` ≈ 7.4:1 (AA for text, strong for UI). |

---

## 2. Entity-type colors + context colors (retuned to POP)

**Design rule:** keep each type's *hue identity* (the type→color intent users already learned)
but push **saturation + lightness toward the Tailwind-400 band** so fills separate cleanly
from the new `#0E0F14` base. Target: every node fill clears **~4.5:1** vs background (so even
small nodes read), and adjacent hues stay **>15° apart** in hue so the 8 types remain mutually
distinguishable. These hexes go in **both** `CicadaTheme.entityColor(for:)` **and**
`graph.js typeColors` (and the `media`/`hub` graph accents).

| Type | Intent | Current | **Proposed** | Contrast vs `#0E0F14` | Legibility note |
|---|---|---|---|---|---|
| `person` | blue | `#4A9EFF` | **`#5AA8FF`** | ~7.1:1 | Brighter sky-blue; anchor hue, clearly separated from `tool` teal. |
| `project` | purple | `#A855F7` | **`#B57BFF`** | ~5.9:1 | Lift purple off the dark violet base so it doesn't sink; stays distinct from `accent` periwinkle (project = redder-violet). |
| `company` | orange | `#F97316` | **`#FF8A3D`** | ~8.4:1 | Warmer, brighter orange; very high pop. Clearly apart from `deadline` red and `skill` yellow. |
| `concept` | green | `#22C55E` | **`#3BD97A`** | ~8.9:1 | Brighter spring-green; strongest separation from `tool` teal is the hue gap (green ~145° vs teal ~172°). |
| `tool` | teal | `#14B8A6` | **`#2DD4BF`** (Tailwind teal-400) | ~9.1:1 | Brighter teal; reads clearly vs both `concept` green and `person` blue. |
| `deadline` | red | `#EF4444` | **`#FF5C5C`** | ~6.0:1 | Hotter red, urgency-forward; distinct from `company` orange by hue + from `media` pink by saturation. |
| `skill` | yellow | `#EAB308` | **`#F2C744`** | ~11.4:1 | Brighter gold; highest luminance of the set — pops hardest, which suits "skill/preference" salience. Keep distinct from `hub` gold (see below). |
| `location` | grey | `#9CA3AF` | **`#AEB6C4`** | ~7.0:1 | Cool neutral, intentionally *the* desaturated one so "place" reads as backdrop, not a category competing for attention. |

**Graph-only accents (also retune):**

| Token | Current | **Proposed** | Note |
|---|---|---|---|
| `media` (`mediaPink`) | `#EC4899` | **`#F65BA6`** | Brighter magenta-pink; distinct from `deadline` red by hue, from `family` context by being slightly cooler. |
| `hub` (`hubGold`) | `#E6B450` | **`#E0A93A`** | Hub gold must stay **distinct from `skill` `#F2C744`** — keep hub a deeper, more amber gold so a hub ring never reads as a skill node. |
| `pendingPulse` | `#F5C04E` | **`#FFCB57`** | Amber "needs you" pulse, slightly brighter so the pulse pops on the darker bg. |

**Context colors (claim layer — `CicadaTheme.contextColor` + `graph.js CONTEXT_COLORS`).**
These intentionally **reuse the type hues** so the two layers feel like one system; retune to
match the new entity values:

| Context | Current | **Proposed** | Mirrors |
|---|---|---|---|
| `engineering` | `#14B8A6` | **`#2DD4BF`** | = new `tool` teal |
| `family` | `#EC4899` | **`#F65BA6`** | = new `media` pink |
| `philosophical` | `#A855F7` | **`#B57BFF`** | = new `project` purple |
| `career` | `#F97316` | **`#FF8A3D`** | = new `company` orange |
| `cross` | `#EAB308` | **`#F2C744`** | = new `skill` gold (the cross-context bridge stays the loudest) |
| `general` | `#6B7280` | **`#7A8290`** | neutral, slightly lifted to stay visible on `#0E0F14` |

**Open-tail context hash** (`hslHue(...)` → `hsl(hue, 55%, 65%)`): bump lightness `65% → 68%`
**in both `CicadaTheme` and `graph.js` identically** so hashed contexts also pop on the darker
base. This is the one spot where the HSL formula must change in lockstep across both files or
the SwiftUI chrome and the d3 canvas will disagree on an unknown context's color.

**Observer badge colors** (`OBSERVER_BADGE_COLORS`): retune to match — `agent` → new `accent`
`#8896FF`, `rodrigo` → new `person` `#5AA8FF`, `external` → new `media` `#F65BA6`.

**Status colors:** `decaying` `#F59E0B → #F5A93B`, `archived` `#6B7280 → #7A8290`,
`dropped` keeps red-at-opacity (now `#FF5C5C` @ 0.6). `active` follows `accent`.

> Contrast figures above are sRGB-luminance ratios vs the proposed `#0E0F14` base. All entity
> fills clear 4.5:1; the lift comes from *both* darkening the base and brightening the hue, so
> the net pop is multiplicative. Mutual distinguishability holds because we preserved the hue
> wheel positions (blue→purple→pink→red→orange→gold→green→teal→grey) and only pushed
> sat/lightness.

---

## 3. Page names + layout proposals

### 3a. Nav rename (don't over-rename — keep what's already clear)

Current `enum AppTab`: **Memory · Topics · Feed · Sleep · Inbox · Contributors**.
Most are fine. Two are unclear against comparable-app conventions:

| Current | **Proposed** | Convention cited | Rationale |
|---|---|---|---|
| **Memory** | **Graph** | Obsidian "Graph view"; the *canonical* name for a force-directed node view | "Memory" describes the *system*, not the *view*. The thing on screen is a graph; users of Obsidian/Roam expect "Graph." Icon: keep `brain.head.profile` OR move to `point.3.connected.trianglepath.dotted` to read as a graph. |
| **Topics** | **Clusters** | Obsidian groups / Notion; "Topics" undersells that these are *detected* groupings | Optional. If "Topics" tested well, keep it — it's not broken. "Clusters" matches the CLAUDE.md "cluster pages" vocabulary and the graph's cluster-detection feature. Lower-priority rename. |
| **Feed** | **Feed** (keep) | Arc/Notion "Feed"; clear | No change. |
| **Sleep** | **Sleep** (keep) | Project's core metaphor; renaming would erase the thesis's signature concept | No change — but the *page header* should read "Sleep Cycle" (it already does) so the nav label and content agree. |
| **Inbox** | **Inbox** (keep) | Linear/GitHub/Gmail "Inbox" with a count badge — exactly today's pattern | No change. The badge convention is already correct. |
| **Contributors** | **Contributors** (keep) | GitHub "Contributors" (per-author commit/file counts) — this is *literally* the GitHub feature, same name | No change. The name is precisely the right borrowed convention. |

**Recommended minimal set of renames:** **Memory → Graph** (high confidence, big clarity win).
**Topics → Clusters** is optional/lower-priority. Everything else stays. This honors
"don't over-rename."

**Sidebar grouping (Linear/Notion convention):** the sidebar is currently a flat 6-item list.
Add quiet section dividers to group by mental model:
- **WORKSPACE** — Graph, Clusters, Feed
- **MAINTENANCE** — Sleep, Inbox
- **PROVENANCE** — Contributors

Use the existing uppercase `captionFont` + `textTertiary` style already used for in-page
section labels (`SCHEDULE`, `PROGRESS`) so it's visually consistent and zero new tokens.

### 3b. Consistent per-page header (formalize the pattern that already exists)

`SleepView` already establishes a good header: `titleFont` title + `textSecondary` one-line
subtitle, with `spacingXL` outer padding and uppercase `captionFont` section labels. **Promote
this into a single reusable `PageHeader` component** so every page (Graph, Clusters, Feed,
Sleep, Inbox, Contributors) is identical. Convention: **Linear/Notion page headers** (title +
optional subtitle + right-aligned primary action).

```
PageHeader(title:, subtitle:, trailing: { … optional action button … })
  • title    → CicadaTheme.titleFont, textPrimary
  • subtitle → CicadaTheme.bodyFont, textSecondary   (one line, optional)
  • trailing → primary action, right-aligned (e.g. "Run now", filter, search)
  • padding  → .horizontal spacingXL, .top spacingXL, .bottom spacingLG
  • a hairline `border` divider below the header on scrollable pages (GitHub convention)
```

Proposed titles/subtitles per page:
- **Graph** — "Graph" / "Everything Cicada knows, and how it connects."
- **Clusters** — "Clusters" / "Auto-detected groups of related entities."
- **Feed** — "Feed" / "Recently ingested sources and saved resources."
- **Sleep** — "Sleep Cycle" / "Consolidate today's episodes into the memory graph." *(already this)*
- **Inbox** — "Inbox" / "Nudges and clarifications waiting on you." + count badge in trailing.
- **Contributors** — "Contributors" / "Which model or person authored each belief."

### 3c. Spacing / section conventions (formalize, don't add tokens)

The existing `spacing*` and `cornerRadius*` scale is good; just apply it uniformly:
- **Page outer padding:** `spacingXL` (matches SleepView).
- **Card inner padding:** `spacingLG`.
- **Section label:** uppercase `captionFont` + `textTertiary`, `spacingMD` below it
  (the `SCHEDULE`/`PROGRESS` pattern — make it the standard for *all* in-page sections).
- **Card radius:** `cornerRadius` (12) for cards, `cornerRadiusSmall` (8) for chips/rows.
- **`GlassCard`:** on the darker base, drop the stroke from `white.opacity(0.08)` to the new
  `border` token and reduce shadow radius (`20 → 14`) — the darker bg makes heavy glass blur
  read as muddy; Linear/GitHub keep dark cards crisp with a thin border, not a big blur.

---

## Implementation note (for the M5 pass, not this doc)

Every hex in §1–§2 lands in **two files in lockstep**: `Theme/CicadaTheme.swift`
(`Color(hex:)` literals) and `Resources/graph/graph.js` (`typeColors`, `CONTEXT_COLORS`,
`OBSERVER_BADGE_COLORS`, the `hsl(... ,68%)` open-tail formula, tooltip `rgba()` fills, `#666`
edge default → bump to new `border`). Verify with `cd app/CicadaApp && swift build` (exit 0).
Nav rename touches `Views/Sidebar/SidebarView.swift` (`enum AppTab`) + `ContentView.swift`
page switch + each view's header. `PageHeader` is a new `Views/Common/` component.
