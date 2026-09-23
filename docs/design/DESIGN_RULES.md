# Cicada design rules — Direction D, "Focus columns"

Status: **binding** from 2026-09-23. Owner: Rodrigo. Lives at `docs/design/DESIGN_RULES.md`. It supersedes the round-3 "Calm" draft (`design-rules-draft.md`) and fills that draft's empty §15 slot.

---

## 1. Purpose, the main task, and how to use this file

**Purpose.** This file holds the rules every screen of the companion app must follow: tokens, type, layout, components, provenance wording, motion, and the lints that enforce them. The app had drifted into six drawings of a primary button, four type voices, two accents and a different header on every page (problems P1–P5, §10). One vocabulary, written down once, stops that.

**The main user task.** *Keep what Cicada believes about you true: see what it has learned, check where each belief came from, and settle the ones it is unsure about.* People talk to Cicada in chat, over MCP. The app is where they make the record true, and each inbox resolution is the grounded reward Cicada learns from (G113). Every rule here serves that task first. The Inbox carries that task, so it is the reference screen.

**How to use this file.**

- **Rule ids.** Rules are numbered `DR-1` … `DR-n` and the numbers are permanent. A retired rule keeps its number, is marked *retired*, and the number is never reused.
- **Cite rules in PRs.** Every UI PR lists the rule ids it applies in its body ("Applies DR-12, DR-31, DR-40"). Review checks the screenshots against exactly those rules.
- **Departures need a ruling.** A departure needs a ruling line in §9 (date, rule, decision, why), added in the same PR. A departure without one is a bug.
- **Precedence**, strongest first: the owner's own words → CLAUDE.md rails and rulings → this file → convenience. If a rule here contradicts a CLAUDE.md ruling, the rule is what gets fixed.
- **Enforcement tags:** `[lint]` is a source-scanning test shaped like `FontLiteralLintTests`; `[test]` is a unit or snapshot test; `[review]` is a PR checklist item, for what automation cannot see.
- **Examples** use only the synthetic `demo` bank (Lantern, Meter Sim, Northwind Robotics, Leo Fischer, Helios Labs). Nothing comes from a real bank (the privacy rule).

---

## 2. Principles

| # | Principle | Source |
|---|---|---|
| P-a | **Chrome recedes; the work leads.** Navigation sits a few notches dimmer than content. Selection is brightness plus one neutral fill, never colour. | Linear, "Don't compete for attention you haven't earned" |
| P-b | **Structure is felt, not seen.** Group with a surface one lightness step up, not with rules and borders. | Linear, "Structure should be felt not seen" |
| P-c | **One base, one accent, one contrast.** Surfaces are small lightness steps from one base. Hue is spent on identity (data), never decoration. | Linear's Theme Editor |
| P-d | **Hierarchy comes from brightness steps.** Four text steps; size and weight stay put. | Linear's refresh: title and body unchanged, chrome dimmed |
| P-e | **Keep the density; buy calm with spacing.** Group gaps grow about 8–10%; rows do not get bigger. | Linear's sidebar: +8–10% group gap, same row pitch |
| P-f | **Actions sit in predictable places.** One header anatomy, with fixed slots on every page. | Linear's header blueprint |
| P-g | **Motion has a purpose and a budget.** Keys never animate, UI motion stays ≤ 300 ms, and hover changes fill, not size. | Emil Kowalski's design-eng rules; make-interfaces-feel-better |
| P-h | **Friendly before dense.** Occasional visitors must find their way, so labels are one click away and hover is never the only explanation. | Linear report §4, "what should not transfer" |

---

## 3. Tokens

Direction D takes **Direction C's material** unchanged: the values below are copied from the C mock (`C-Inbox.dc.html`). Contrast figures are WCAG 2.x against `bgBase` unless noted. `CicadaTheme.swift` owns this table (DR-72). Where a token renames today's token, the current name is shown in brackets.

### 3.1 Neutrals: graphite

| Token | Dark | Light | Use |
|---|---|---|---|
| `bgRail` | `#0C0D0E` | `#EFEFEC` | the icon rail and the labelled sidebar |
| `bgBase` [`background`] | `#111213` | `#F7F7F5` | window and content (one surface) |
| `bgPane` | `#141517` | `#FBFBFA` | the Reader column; the Settings panel sidebar |
| `bgHover` [`surfaceHover`] | `#1B1C1E` | `#EFEFEC` | row hover; the command bar in dark mode |
| `bgFocus` [`surfaceElevated`] | `#18191B` | `#FFFFFF` | the focus card and grouped blocks |
| `bgOption` | `#1D1E21` | `#F7F7F5` | option rows at rest, inside the focus card |
| `bgButton` | `#232427` | `#F2F2F0` | neutral button fill (hover `#2C2D30` / `#E3E3E0`); a hovered option row in dark mode |
| `bgSelected` | `#222326` | `#E8E8E5` | selected row, tab and rail cell |
| `bgMenu` | `#1B1C1E` | `#FFFFFF` | menus, popovers, the palette, tooltips |
| `bgKey` | `#26272A` | `#EAEAE7` | keycap fill (glyph `#9A9CA1` / `#5A5B60`) |
| `bgBadge` | `#3A3B3F` | `#D9D9D6` | the rail's pending numeral |

**DR-1. Neutrals are graphite.** `[test]` `ThemeTokenTests` converts each token to LCH and checks the steps and the chroma.
- LCH chroma stays ≤ 4.
- In dark mode, blue exceeds red by at most 3 in sRGB.
- No new steps are introduced between the ones in the table.

### 3.2 Text ladder

| Token | Dark | on `bgBase` | Light | on `bgBase` | Use |
|---|---|---|---|---|---|
| `textPrimary` | `#F5F5F6` | 17.2:1 | `#141415` | 17.2:1 | titles, the question, the quote, selected nav |
| `textSecondary` | `#D0D1D4` | 12.3:1 | `#38393C` | 10.8:1 | body, option descriptions at rest, queue rows |
| `textTertiary` | `#8D8F94` | 5.8:1 | `#6A6B70` | 5.0:1 | meta, labels, eyebrow, inactive nav |
| `textTertiaryOnFill` | = `textTertiary` | 4.9:1 on `bgSelected` | `#5E5F64` | 5.2:1 on `bgSelected` | tertiary text on a selected or hover fill |
| `textQuaternary` | `#6A6C71` | 3.6:1 | `#8A8B90` | 3.2:1 | **disabled only** |

**DR-2. Four text steps, plus one fill variant.** Hierarchy comes from these steps. In light mode, `textTertiary` on `bgSelected` measures 4.33:1, which fails the 4.5:1 bar. Tertiary text on a selected or hovered fill therefore uses `textTertiaryOnFill`. `[test]` `ThemeContrastTests` checks every text token on every surface it is allowed on.

**DR-3. Contrast minimums, in both themes.** `[test]`
- Text a reader needs: ≥ 4.5:1 on the surface it actually sits on.
- Glyphs, rings, focus indicators and kind dots: ≥ 3:1.
- **One disclosed exception:** the light `merge` kind glyph measures 2.98:1 on `bgBase` and 2.60:1 on `bgSelected`. DR-8 forbids moving the hue, so the glyph never stands alone: it carries "Possible duplicate" as its accessibility label and `.help`, and the eyebrow names the kind whenever that row is selected.
- `textQuaternary`: disabled states only.

### 3.3 Accent: the system accent

| Token | Dark | Light | Use |
|---|---|---|---|
| `accent` = `Color.accentColor` | mocked `#0A84FF` (5.1:1) | mocked `#007AFF` (3.7:1) | rings, focus ring, radio dots, span underline, glyphs |
| `accentText` | = `accent` (hover `#4DA3FF`) | `#0062CC` (5.4:1; hover `#004FA3`) | links, "Recommended", "Show in conversation" |
| `wash` / `washSoft` | accent at 18% / 8% | accent at 10% / 7% | the current cited span / the other spans in the Reader |
| `focusRing` | accent 2 pt at 60%, 2 pt offset | same | keyboard focus |

**DR-4. There is one accent, and it is the Mac's.** `CicadaTheme.accent` returns `Color.accentColor`, and the indigo pair (`#8C9CFF` / `#4A5BD6`) is retired. Native segmented controls, sliders, toggles and `.borderedProminent` then match without a `.tint`, which removes the two-accent problem at its root. `Color.blue` never appears. `[lint]` `AccentSourceLintTests`.

**DR-5. The accent has six uses, and only six:**
1. the focus ring;
2. the one primary action on a surface (DR-40);
3. radio dots and the highlighted option's ring;
4. the cited span's underline and wash;
5. links (`accentText`);
6. "Recommended" (`accentText`).

It is never used for selection, nav, badges, tabs or chips. `[lint]` An allowlist caps the number of `accent` references per file.

**DR-6. Never put small text on an accent fill.** White measures 3.6:1 on `#0A84FF` and 4.0:1 on `#007AFF`. `[test]`
- A label on an accent fill is at least 13 pt medium, and appears only on the one primary button.
- Light-mode accent text always uses `accentText`.
- Accent text sits only on `bgBase`, `bgFocus`, `bgPane` or `bgOption` (dark 4.6:1). On `bgSelected`, `bgHover` or a hovered option row it becomes `textPrimary`, because dark accent measures 4.3:1 on `bgSelected` and 4.25:1 on `bgButton`.

### 3.4 Semantic and data colours

**DR-7. Semantic colours are used once per item.** `[lint]` No `.color.opacity(` background fills in `Views/Inbox`, `Views/Topics` or `ClaimChip`.
- `danger` is for destructive actions only.
- `warning` is for the settings attention dot and for the first clause of a failed source.
- `success` is for the import ✓.
- All three keep today's values.
- "Keep", "Got it", "Not now", "Skip", "Dismiss" and "Archive" are **neutral** buttons (DR-40).
- A conflict is red in its kind glyph and nowhere else on the card.

**DR-8. Data hues do not move.** This covers the hues for entity types, contexts, statuses and inbox kinds, and their twins in `graph.js`. The inbox-kind hues are: `[test]` `GraphPaletteTwinTests` and `ThemeTokenTests`.

| Kind | Dark | Light |
|---|---|---|
| conflict | `#FF5C5C` | `#E43D3D` |
| decay | `#F5A93B` | `#B9740A` |
| clarification | `#8896FF` | `#5A62E0` |
| merge | `#F2C744` | `#B48A00` |

- A kind hue appears once per item: as one glyph (≤ 16 pt) or one dot (≤ 8 pt).
- It is never a rail, a pill fill or a tile.
- Light merge (2.98:1) and light decay (3.5:1) are never text. Their glyph sits beside the kind's name, or carries it as its accessibility label.

### 3.5 Elevation

| Surface | Dark | Light |
|---|---|---|
| Resting ring (focus card, block, option row, command bar) | inset 1 pt white 7% | inset 1 pt black 6–8% |
| Strong ring (hover, highlighted option) | inset 1 pt white 12% | inset 1 pt black 12% |
| Column edge (Reader, Settings detail) | leading 1 pt white 7% | leading 1 pt black 7% |
| Floating (palette, bank menu, popover, tooltip, Settings panel) | ring white 10%, no custom shadow | ring black 8% + **one** shadow `0 12 32` black 14% |

**DR-9. Use rings, not borders.** `[lint]` `ElevationLintTests`: `.stroke(CicadaTheme.border` and `.shadow(` appear only in `Theme/`.
- Depth comes from an inset `.strokeBorder` ring.
- The opaque `border` token never strokes a card.
- Real borders remain only on text inputs (white 14% / black 16%, accent 70% when focused), on the dashed file-drop target, and on `DiffView`'s rules.

**DR-10. No shadows in dark mode.** In light mode, only floating surfaces get a shadow, and only one soft one. `[lint]`
- System menus and popovers keep whatever AppKit draws.
- Rows, lists and grids never cast a shadow.
- The focus card is not a floating surface, so it gets a ring only.

**DR-11. The column edge is the only permitted rule.** `Divider()` between stacked bands is gone: group content on `bgFocus` instead. `[lint]` `DividerLintTests`, with an allowlist.

### 3.6 Radii and spacing

| Token | Value | Use |
|---|---|---|
| `radiusLarge` | 16 (was 18) | focus card, Settings panel, error and empty cards |
| `cornerRadius` | 10 (was 12) | command bar, menus, popovers, the palette, grouped blocks |
| `cornerRadiusSmall` | 8 | rows, option rows, buttons, rail cells, tabs, fields |
| `radiusXS` | 4 | keycaps, the span wash (badges and tags are capsules) |
| spacing | 4 / 8 / 12 / 16 / 24 / 32, plus new `spacingCard` 28 and `spacingGutter` 40 | |

**DR-12. Radii are continuous and concentric.** `[lint]` `ContinuousCornerLintTests`: no bare `RoundedRectangle(cornerRadius:` outside `Theme/`.
- Every rounded rectangle goes through `CicadaTheme.shape(_:)` (new), which draws `.continuous` corners.
- A nested pair derives its outer radius from `CicadaTheme.concentric(inner:padding:)` (new). This is needed because padding scales with `uiScale` and radii do not.

### 3.7 D and Meadow (G137)

**DR-13. Working surfaces are graphite. Nature lives in art and in the reward moments.** `[lint]` `MeadowPlacementLintTests`.
- **Retired as `bgBase`:** the Meadow neutrals (`#F4F6F1` day, `#0D1216` night).
- **Kept:** the nature tokens (`sky`, `meadow`, `dandelion`, `cloud`, `bark`, `soil`, their washes, and the procedural skies).
- **Where they may appear:**
  - painted art on EmptyStateView, Welcome and onboarding, the Home band and the Sleep room;
  - the reward moments those surfaces carry: "all caught up", an import landing, a finished cycle.
- **Where they may not:** behind data, on a row, or as a data encoding.
- **No header wash.** There is no procedural header wash, and `SkyBand.ships` stays off (TODO ruling 10).

**DR-14. Liquid Glass stays in the chrome.** `[lint]` `LiquidGlassLintTests`.
- **Where it is allowed:** the rail, the command bar, floating controls, and the one `PrimaryActionButton` per page.
- **How it is applied:** only through `liquidGlass(_:in:)` in `Theme/LiquidGlass.swift`. It is gated on macOS 26 and becomes opaque under Reduce Transparency.
- **Never glass:** the focus card and the Reader.

---

## 4. Type

**DR-15. SF Pro is the only face for all UI.** `[lint]` `FontLiteralLintTests` bans `.custom(`.
- **Instrument Serif is retired** (owner, 2026-09-23).
- **Display type.** `displayFont(size:)` returns `.system(size:weight: .semibold)`, which renders as SF Pro Display at 20 pt and above. Tracking is −0.3 at 20 pt and −0.4 at 22 pt and above.
- **Minimum size.** `displayMinimumSize` becomes 20.
- **Cleanup.** `CicadaFonts` and the bundled TTFs are deleted once nothing names them.
- **New York** leaves as well (see DR-18).

**DR-16. The ladder.** Every size goes through `CicadaTheme.font(size:weight:)` or a named token, and scales with `uiScale`.

| Role | Size / weight / tracking | Colour | Token |
|---|---|---|---|
| Question H1 (the detail heading) | 22 semibold, −0.4 | `textPrimary` | `displayFont(size: 22)` |
| Reader title / empty-state title | 20 / 22 semibold | `textPrimary` | `displayFont` |
| Error-card title, panel heading | 17 semibold | `textPrimary` | `headingFont` (16 → 17) |
| Quote (the hero) | 15 regular, line height 25 | `textPrimary` | `quoteFont` |
| Body / option label | 14 regular / 14 medium | `textSecondary` / `textPrimary` | `bodyFont` (13 → 14 on detail surfaces) |
| Row title, list question, command bar | 13 medium / 13 regular | `textPrimary` / `textSecondary` | new `rowFont` |
| Meta, eyebrow, source line, links | 12 regular / 12 medium | `textTertiary` / `accentText` | new `metaFont` |
| Section label, key hint, tag | 11 medium, sentence case | `textTertiary` | `labelFont` (no mono, no caps) |
| Rail badge | 10 semibold, tabular | `textPrimary` on `bgBadge` | new `badgeFont` |

Semibold is reserved for the H1, the Reader title, empty and error titles, and the badge. Everything else is regular or medium. `.bold()`, `.heavy` and `.black` appear only in `Theme/`. `[lint]`

**DR-17. `displayFont` has exactly five call sites:**
1. the question H1;
2. the Reader title;
3. EmptyStateView;
4. Welcome and onboarding headlines;
5. the Settings panel's `PageTitle`.

List pages have no page title (DR-25). Apart from the Settings panel, `PageTitle` survives only on the room pages (Sleep and Home). `[lint]` `DisplayFontCallSiteLintTests`.

**DR-18. The quote is the hero.** Every word a person or an agent said passes through one door: `quoteFont`, which is SF 15 regular, not italic and not serif. `[test]` A snapshot of a quote block.
- **The cited span** is washed and underlined: a `wash` fill, a 2 pt `accent` underline offset by 4 pt, a 4 pt radius and 1 pt of padding.
- **A quote block** is indented 16 pt behind a 2 pt rule (white 16% / black 14%).
- **Inside a quote**, there is no bold and no italic.

**DR-19. Monospace is only for what a person would copy:** paths, commands, hashes, and ids shown in a debug or history detail. It is never used for a tag, a pill, a label, a date, a count or a key hint. `[lint]` `MonospaceLintTests`: `design: .monospaced` appears only in `CommandBox`, `DiffView`, path rows and copy-id rows.

**DR-20. There is one section-label style:** sentence case, `labelFont`, in `textTertiary`. No labels are set in all caps with tracking. The roughly 34 places that spell a label by hand become one `SectionLabel` component (new). `[lint]` `.tracking(` appears only in `Theme/`.

**DR-21. Numbers.** `[lint]` `CountLiteralLintTests`, plus a warning for any count `Text` without `monospacedDigit`.
- A count that changes on screen gets `.monospacedDigit()`.
- When the pointer caused the change, it also gets `.contentTransition(.numericText())`.
- Counts go through `UsageFormat.count` and always carry a unit noun (G124).

---

## 5. Layout grammar

### 5.1 The shell

```
┌──────┬──────────────────────── titlebar 52 pt ────────────────────────────┐
│ ● ● ●│ [⇤]        ┌ demo ▾ │ ⌕ Search your memory           ⌘K ┐       [?] │
│      │            └─────────────── command bar 520 pt ────────┘           │
├──────┼───────────────────────────────────────────────────────────────────┤
│ rail │ eyebrow  ·  text tabs with counts                                  │
│ 56pt │ content: progressive columns (§5.3)                                │
│ ⚙ ☾  │                                                                    │
└──────┴───────────────────────────────────────────────────────────────────┘
```

**DR-22. Navigation is an icon rail, 56 pt wide.** `[lint]` `SelectionTintLintTests`: rail and sidebar state uses only `textTertiary`, `textPrimary` and `bgSelected`.
- **Cells.** Each cell is 36 × 36 pt, uses `cornerRadiusSmall`, sits at a 40 pt pitch, and holds an 18 pt glyph.
- **State.** Inactive glyphs are `textTertiary`. The selected cell is `bgSelected` with a `textPrimary` glyph: never the accent, never a filled symbol.
- **Tooltips.** Every cell has a tooltip naming its page and shortcut ("Inbox ⌘5"). The first tooltip waits 450 ms; after that, the next one opens instantly (R-F2).
- **The Inbox badge** is a neutral tabular numeral in a `bgBadge` capsule, with a 2 pt knockout in `bgRail`.
- **While a cycle runs**, the Sleep glyph becomes a spinner.
- **The rail's foot** holds the gear (⌘,), which shows a `warning` attention dot when needed, and the theme toggle, which uses `.symbolEffect(.replace)`.
- **The sidebar toggle** switches between the rail and a labelled sidebar (208 pt wide, same tokens, 32 pt rows). The choice is remembered per viewer.
- **No wordmark.** The chrome carries no "Cicada" wordmark.

**DR-23. The titlebar is a command bar.** The window title is hidden. `[test]` A hit-test confirms the gaps drag the window.
- **The bar.** A 520 × 32 pt bar is centred in the 52 pt titlebar. Its surface is `bgHover` in dark mode and `bgMenu` with a ring in light mode, with `cornerRadius` corners and a strong ring on hover.
- **Contents, leading to trailing:** the memory-bank selector ("demo ▾", a 200 pt menu), the placeholder "Search your memory", and a `⌘K` keycap.
- **Clicking the bar.** A click anywhere on it outside the bank selector opens the existing `FindPalette` (640 pt, `cornerRadius`), anchored under the bar, with no animation.
- **The `?`** is the titlebar's rightmost control. There is one per window, and it answers for the visible page (Track P).
- **The sidebar toggle** follows the traffic lights. Everything else in the titlebar stays a window drag area.

**DR-24. There is one bank selector, and it lives in the command bar.** `BankSwitcher` moves there from the Graph overlay, and the command bar is the only place a bank switch can happen. A second switcher would reintroduce the split-brain bug class. Settings never switches banks. `[test]` `SingleBankSwitcherTests`.

**DR-25. List pages have no page-title band.** Inbox, Clusters, Feed and Sources open straight into an **eyebrow row**: at least 28 pt tall, 20 pt below the titlebar. `[test]`
- **Left:** the eyebrow, in `metaFont` medium, `textTertiary`, tabular. It reads "Inbox · 6 pending", or "Inbox · 1 of 6 · Conflict" when a question is open.
- **Right:** text tabs with counts (DR-45).
- **The old subtitle** moves into the `?` popover and the empty state.

**DR-26. The first content item starts no more than 120 pt below the window top,** at 1× and the default window size. The budget is 52 + 20 + 28 + 12 = 112 pt; today the figure is 211 pt. `[test]` A UI test measures the frame.

### 5.2 Page types

| Type | Anatomy |
|---|---|
| List page (Inbox, Clusters, Feed, Sources) | eyebrow row, then progressive columns (§5.3) |
| Canvas (Graph) | full-bleed; chrome only as floating overlays (§10) |
| Room (Sleep, Home) | one 760 pt column; a `PageTitle` or the room sentence; details as a list |
| Panel (Settings) | in-app panel (DR-33) |

### 5.3 Progressive columns

This is the Inbox's pattern. Any page where a list opens a detail, and the detail opens its source, reuses it.

**STATE 0: nothing selected.** The layout is the rail, then the list alone at full content width (gutter 40).
- **Rows** are one line, 36 pt tall, with no gap between them. Left to right: the kind glyph (14); the question (13 regular, `textSecondary`, truncated, text capped at 760 pt); the entity (12, `textTertiary`); the source mark (12) with the app name and date ("Claude Code · Aug 25"), or the cause line when there is no conversation; the age, right-aligned and tabular; and the Expand chevron (`IconButton`). A click anywhere on the row opens STATE 1.
- **No source.** When there is no source, that slot reads `[ no source recorded ]` (DR-55).
- **No placeholder.** There is no detail pane and no "select something" placeholder.

**STATE 1: a row clicked.** The layout is the rail, a **triage column**, and the **question**.
- **The triage column.** The list collapses to 328 pt at a 1440 pt window and 280 pt at 1200. Rows become two lines, 56 pt tall, 2 pt apart: the glyph, the question (13 regular, `textSecondary`) and the age on the first line; the entity, the mark and "Claude Code · Aug 25" on the second.
- **The selected row** is `bgSelected`. Its text rises one step, and its tertiary text uses `textTertiaryOnFill`. It never uses the accent.
- **The question** takes the rest of the width (40 pt gutter) as C's **focus card**: `bgFocus`, `radiusLarge`, a resting ring and no shadow, `spacingCard` padding, at most 720 pt wide and centred. In order, the card holds:
  1. a header line: the kind glyph, the entity name (12, `textTertiary`) and Close × (Esc);
  2. the H1, stated **once**;
  3. the quote, with its washed span (DR-18);
  4. the source line and "Show in conversation ›";
  5. the extractor's guess ("gpt-5.4-mini's guess at 0.85", in `textTertiary`);
  6. the option rows (DR-42) and Other…;
  7. the hint, with "Open source ↗" at its end;
  8. "Not now — ask again in 7 days · L", a `TextButton` at the card's foot.

**STATE 2: "Show in conversation".** The layout is the rail, the list, the question, and the **Reader**.
- **The Reader** opens to the right of the question, on `bgPane` with its column edge. It is 420 pt wide at 1440 and 360 pt at 1200.
- **The list** narrows to titles only (260 pt, 36 pt rows) so the question keeps at least 440 pt.
- **The gutter** and the card's padding drop to 24 pt.

| Window | Nav | List S1 / S2 | Question S1 / S2 | Reader S2 |
|---|---|---|---|---|
| 1440 | rail 56 | 328 / 260 | 1056 / 704 | 420 |
| 1440 | labelled 208 | 328 / 260 | 904 / 552 | 420 |
| 1200 (min) | rail 56 | 280 / 260 | 864 / 524 | 360 |
| 1200 (min) | labelled 208 | 280 / hidden | 712 / 632 | 360 |

**DR-27. Column priority runs question, then Reader, then list.** The question never drops below 440 pt, and the Reader never drops below 360 pt. When both cannot fit, the list hides, and a "‹ 6 questions" text button at the head of the question brings it back. `[test]` `ColumnLayoutTests` at 1440 × 900 and 1200 × 800, with both the rail and the labelled sidebar.

**DR-28. Esc closes the rightmost open thing,** in this order:
1. an open Other… field;
2. the Reader;
3. the question, which returns the page to STATE 0.

It never animates (DR-60). `[test]`

**DR-29. Selection swaps in place.** `[test]`
- **Clicking another row** swaps the question instantly, and no column width moves.
- **The Reader** closes on a swap, unless the new question cites the same conversation. In that case the Reader stays open and its navigator jumps to the new span.
- **After a resolve**, the next row is selected instantly.
- **Resolving the last item** returns the page to STATE 0's empty state.

**DR-30. Each column scrolls independently.** The list keeps its scroll position across states. A question landed from ⌘K opens STATE 1 with its row scrolled into view. `[test]`

### 5.4 The Reader and Settings

**DR-31. The Reader is the one provenance surface.** Every "Show in conversation", every evidence chip and every "Where this came from" row opens the same `ReaderInspector`, driven by `ProvenanceRouter`, as the rightmost column of the open page. It is never a sheet or a window, and it never pushes content off-window. From top to bottom it holds: `[test]`
- **The header:**
  - the origin mark (20 pt);
  - the title (`displayFont(size: 20)`);
  - the meta line ("Claude Code · Aug 25, 2026 · 1 turn");
  - **Resume**, a neutral 28 pt button shown only when the session is resumable (checked with `isfile()` only);
  - Close × (also Esc);
  - Back (⌥⌘[), shown when the stack is deeper than one.
- **The capture line.**
- **The navigator:** "↑ 1 of 2 cited here ↓" (⌥↑ / ⌥↓).
- **The speaker blocks.** Each is headed like "You · turn 1", with a time only when one is stored. The current span is shown in `wash` with its underline; the other spans are in `washSoft`.
- **"Noted from this conversation (n)" rows.** Each row jumps to its span and has a trailing "Show on graph". A row whose claim is no longer current says so.

**DR-32. Every Reader state is said in words, never shown as a blank.** `[test]`
- **Loading:** a skeleton in the header's shape.
- **Gone:** "This conversation isn't in this bank any more." (today's `Copy.Provenance.gone`).
- **Failed:** the error, with Try again.
- **Other span states:** stale, grown, derived, inferred and truncated are each said in words (G118 slice 2). A 422 response reads as stale.

**DR-33. Settings is an in-app panel.** ⌘, and the gear open a centred panel inside the main window, like the Claude desktop app's. `[test]` ⌘, routes to the panel.
- **Size and surface.** The panel is 880 × 620 pt at 1440 and is inset at least 40 pt at 1200. It uses `radiusLarge`, is a floating surface (DR-10), and sits over a scrim (black 24% / 12%).
- **Sidebar.** The sidebar is `bgPane`, 220 pt wide. It starts with a `CicadaSearchField` and keeps the G139 groups in the rail's row tokens.
- **Detail pane.** The detail pane has a `PageTitle` and a close ×.
- **Closing.** Esc closes the panel.
- **The old scene.** The `Settings{}` scene is removed. `SettingsSection` raw values do not move.

### 5.5 Density

| Role | Height | Horizontal padding | Notes |
|---|---|---|---|
| Rail cell | 36 (pitch 40) | — | 18 pt glyph |
| Labelled nav row | 32 | 10 | |
| List row, one line (S0) | 36 | 10 / 8 | no gap between rows |
| Triage row, two lines (S1) | 56 | 10 | 2 pt between rows |
| Title-only row (S2) | 36 | 10 | |
| Option row | 48 | 14 | radio 16 pt, 1.5 pt ring, 6 pt dot |
| Button | 28 compact / 32 | 10–14 | |
| Text tab | 26 | 9 | |
| Command bar | 32 | 4 / 6 | |

**DR-34. Each row role has one height, read from tokens.** No view sets its own vertical padding on a row. `[lint]` No literal `.padding(.vertical,` in row components.

**DR-35. Density comes from spacing, not from box size.** `[review]`
- **Gaps:** none between one-line rows, 2 pt between two-line rows and 4 pt between option rows. Blocks inside the focus card are 20–24 pt apart; the source line and the guess stay attached to the quote above them.
- **Group gaps** are always at least 1.5 × the row gap.
- **Calming a screen** means growing the gaps between groups by 8–10%. Row heights stay as they are.

**DR-36. A text column is at most 760 pt wide.** The focus card is 720 pt and the Sleep column is 760 pt. Lists may run wider, but their text stays capped. `[test]`

**DR-37. A single short line never gets a card of its own.** A card holds a group. `[review]`

**DR-38. Remove anything that repeats what is already on screen.** Examples: `[review]`
- a kind stated four times;
- a question printed twice;
- "6 pending" shown twice;
- a type rail that repeats its own rows.

**DR-39. Secondary detail starts collapsed,** and each viewer's choice is remembered. This generalises Sleep's Details. `[review]`

---

## 6. Components: one vocabulary each

**DR-40. There are four kinds of button, and none is hand-rolled.** `[lint]` `WhiteLiteralLintTests`, plus an allowlist of button styles.

| Kind | Look | Where |
|---|---|---|
| `PrimaryActionButton` | accent fill (glass-prominent on macOS 26), 13 medium, 32 pt | **at most one per surface**; the Inbox has none |
| new `NeutralButton` | `bgButton` + resting ring, `textPrimary`, 28/32 pt, `cornerRadiusSmall` | Resume, Retry, Submit, Merge, Got it, Keep, Archive |
| new `TextButton` | no fill; hover `bgSelected`; text `textSecondary` → `textPrimary` | Not now, Skip, Show all, "‹ 6 questions", the bank selector |
| new `IconButton` | 28 × 28 hit area, 13–14 pt glyph (16 in the titlebar), hover `bgSelected` | Close, Back, navigator arrows, Expand, `?`, the sidebar toggle |

- **Destructive actions** (such as deleting a bank or disconnecting) use a `NeutralButton` with a `danger` label, behind a confirmation.
- **`InboxActionButton`** loses its `color` parameter.
- **White text.** Nothing uses `.foregroundStyle(.white)`.

**DR-41. Press, hover and disabled states.** `[test]`
- **Press.** Every pressable control uses a `ButtonStyle`: `CicadaPlainButtonStyle` or one of the four above. It dips to 0.97, and the dip is gated under Reduce Motion.
- **Hover** changes fill or colour only.
- **Disabled** is 45% opacity. The control keeps its label and explains why in `.help`.

**DR-42. Option rows: one tap resolves.** `[test]`

- **Anatomy, left to right:** a 16 pt radio (1.5 pt `textTertiary` ring; a 6 pt accent dot when highlighted); the label (14 medium); the description (12, `textTertiary`, leading with the age phrase); "Recommended" (12 medium, `accentText`); the age as a `Tag` (DR-44, tabular); a `⏎` keycap on the highlighted row; a keycap `1`…`9`.
- **States:** at rest `bgOption` with a resting ring; hover one step up (`bgButton` in dark, `bgHover` in light), where "Recommended" turns `textPrimary` (DR-6); highlighted (by key or pointer) a 1.5 pt accent ring. The first highlight goes to Recommended when one exists. A conflict with no Recommended option highlights row 1 and shows no marker.
- **A click or a number key resolves at once.**
  - The next item swaps in.
  - An inline **Undo row** takes the resolved row's place in the list for 5 s: a ✓ glyph, "Answered · sqlite-vec", the question, and an Undo `NeutralButton` (also ⌘Z). It has a resting ring, no fill and no shadow; with the Reader open it shortens to "Answered · Undo".
  - This keeps UX principle 1, "responding to a nudge = one tap", so C's click-then-Resolve is not used.
- **Undo is a send delay, not a revert.**
  - The answer is applied optimistically.
  - `POST /inbox/{id}/resolve` is sent when the Undo window closes, when the next resolve starts, or on a bank switch or quit, whichever comes first.
  - An undone answer therefore writes no commit and emits no G113 `resolution` event.
  - This is new: `ResolveGrace`, a `Mutation` with a hold.
- **Other…** is a row with the same anatomy, a pencil glyph and the key `O`.
  - It expands the field "What's actually true?".
  - **Submit** is neutral and stays disabled until the field contains text. ⏎ submits.

**DR-43. Every variant stays reachable inside the focus card.**

| Variant | What it shows |
|---|---|
| Informational (G98) | the values with their ages, then Got it |
| Merge | a description field; an existing-entity field; the Keep-as-canonical picker; the "A → B" line; Answer / Merge / Keep separate / Skip, each disabled until it can act |
| Decay | Keep / Archive, no free text |
| Removal | keep / remove |
| Free text | the field, open by default |
| Legacy fallbacks | one row of neutral buttons |

| Page state | What it shows |
|---|---|
| Loading | "Checking what needs you…" over a skeleton in the card's shape |
| Error | "Couldn't load the inbox", the reason and Retry, in a `radiusLarge` card |
| Empty | DR-50 |

Mocks reach every variant and state through the "Preview states" menu. The app reaches them through the demo bank. `[review]`

**DR-44. There is one pill: `Tag`.** `[review]`
- It is 11 medium `textSecondary` on a `bgSelected` capsule, 18 pt tall.
- A colour variant adds a 6 pt dot inside the pill. It never tints the pill itself.
- A tag is never monospaced and never works as a filter.

**DR-45. Tabs are text tabs with counts.** `[lint]` `SegmentedPickerLintTests`: `.pickerStyle(.segmented)` only under `Views/Settings/`.
- **Size.** 26 pt tall with 9 pt padding, set in 12 medium.
- **States:** active `bgSelected` + `textPrimary`; inactive `textTertiary` with no fill; hover `bgHover` + `textSecondary`.
- **Counts** follow each label in tabular figures: "All 6 · Decay 1 · Conflict 2 · Clarification 2 · Possible duplicate 1".
- **Selection.** Tabs are single-select; clicking the active tab returns to All. They carry no kind dots.
- **Retired:** joined segmented bars, underline tabs and filter capsules. The native segmented control remains only inside Settings forms.

**DR-46. There are two search fields, each with one job.** `[test]`
- **The command bar** is global search (⌘K).
- **In-page find** is a `CicadaSearchField` opened with ⌘F. It appears only where a page has something to find, so never on the Inbox.
- **A results dropdown** overlays the layout and never pushes it.
- **The Graph's Search button** is retired.

**DR-47. Every section label uses `SectionLabel`** (DR-20). That includes "Up next", "Waiting" and "Noted from this conversation (n)". `[lint]`

**DR-48. Rows.** This covers list, triage, provenance, palette and Found rows. `[lint]` No `.hoverLift` or `.scaleEffect` on row types.
- Hover is `bgHover` and selected is `bgSelected`.
- A row never scales, lifts or casts a shadow.
- A row carries a kind glyph **or** a dot, never both.

**DR-49. There is one key-hint component: `KeyHint` (new).** `[review]`
- It is at least 18 × 18 pt, uses `radiusXS` and `bgKey`, and is set in 11 medium SF, never mono.
- It appears wherever a key acts.
- Every key it shows also has a pointer equivalent.

**DR-50. Empty states use `EmptyStateView`.** `[lint]` `MeadowPlacementLintTests`.
- **Content:** a `displayFont(size: 22)` title, then the truthful lines ("Last Sleep ran Aug 31. 3 conversations are waiting for the next one."), and at most one action.
- **Art:** the Inbox's "all caught up" may carry the painted meadow; it is the page's one reward moment. Other list pages use the plain variant.
- **Text never sits directly on paint.**

**DR-51. The rail numeral is the only badge.** Counts inside a page are text in tabs or eyebrows, never capsules. `[review]`

**DR-52. Marks follow Track L.** `[test]` `LogoAssetTests`, and every channel in `channel_registry` resolves to a mark.
- **Use the real mark.** Wherever a service is named, show its real mark through `OriginMark` / `LogoImage`. The lookup order is: the installed app icon, then the bundled PNG, then an SF Symbol. Never show a generic glyph when a mark exists.
- **Never alter a mark.** A mark is never recoloured and never sits on a tinted tile. It stands bare: 12 pt in rows, 14 pt in the source line, 20 pt in the Reader header.
- **Marks whose background is the mark** (`claude-code`, `claude-desktop`, `hermes`) are clipped to their own curvature, never recut.
- **Hover.** Marks nod with `markHover`, never `iconHover`.

**DR-53. Icons.** `[lint]` `IconButtonHelpLintTests`.
- **Style.** SF Symbols at regular weight, in outline variants.
- **Sizes** come from `CicadaTheme.icon(_ role:)` (new): rail 18 (the gear and theme toggle at its foot 17), titlebar controls 16, list glyph 14, command bar 13, inline 12, badge 10 (pt).
- **Remove redundant glyphs.** A glyph that repeats the word next to it is removed.
- **Icon-only controls** have a 28 pt hit area, a `.help` naming the action and its shortcut, and an accessibility label.

---

## 7. Provenance language

**DR-54. Name a source the way a person would:** mark, app name, conversation title, date. For example: "Claude Code · Lantern storage: CSV to sqlite-vec · Aug 25". Without a title, it reads "a Claude Code conversation · Aug 25". `[lint]` `ProvenanceIdLintTests`: no raw `ep_`, `harness` or `origin` interpolation in `Views/` outside an allowlist. `[test]` Source-line snapshots.
- Episode ids, harness slugs, file paths and commit subjects never appear at body weight on a main surface.
- They are reachable only through `.help` ("Episode ep_2026-08-25_001"), a Copy id action, or the History detail.

**DR-55. Rail literals keep their words and lose their weight.** `[test]`
- `[ no source recorded ]` (G115) is served exactly as written, in `metaFont` and `textTertiary`, and is never louder than a real source line.
- `—` keeps its hover reason (G125).

**DR-56. Excerpts are clean text.** Markdown structure (`# Episode …`, bullets) is stripped before display. Wikilinks render as names, and a slug renders as its page's name ('energy-anomaly-detection' reads "Energy Anomaly Detection"). All of this goes through `ExcerptText`. `[test]`

**DR-57. Evidence chips say who spoke:** "You said", "<agent> replied", "From the page", "Inferred", "Mentioned here". `[test]`
- The hover preview shows the words washed when quoted, bold when derived, and plain when stale.
- A chip is a `Tag` with the speaker's mark, never a coloured pill.

**DR-58. Relative dates are computed when read, never stored.** `[test]`
- Descriptions lead with the age phrase ("4 weeks ago · last mentioned Aug 25").
- Row ages are compact ("4w", "8mo"), with the absolute date in `.help`.
- A time shows only when the episode stores one.

**DR-59. Copy.** `[lint]` `PriceLintTests`.
- Sentence case and plain verbs; no "!" and no bare "%".
- A meta line is one line.
- A question is stated once per surface.
- No prices, token counts or "$" anywhere (ruling of 2026-09-03).

---

## 8. Motion and interaction

**DR-60. Keyboard actions never animate.** This applies to ⌘1–6, ⌘K, ⌘F, Esc, 1–9, O, L, ⏎, ↑/↓, ⌥↑/⌥↓ and ⏎ in the palette. Their pointer equivalents animate only where the table under DR-61 says so. `CicadaMotion.paletteIn` and `paletteOut` are deleted: the palette appears and leaves in one frame. `[lint]` `KeyboardAnimationLintTests`: no `withAnimation` in any handler reachable from `.keyboardShortcut`, `onKeyPress` or `FindCommands`, with an allowlist.

**DR-61. Durations live only in `CicadaMotion` and `SleepMotion`.** The ceiling for UI motion is 300 ms. Weather, the pile and the camera sit under a separately named `ambientMaxDuration = 0.4`. `[lint]` `MotionLiteralLintTests`.

| Event | Pointer | Keyboard |
|---|---|---|
| Tab switch; selection swap in columns | instant | instant |
| STATE 0 → STATE 1 | `CicadaCurve.drawer(0.25)` on the list width only; the card fades in over 150 ms | instant |
| Reader column opens / closes | drawer: 250 ms in (16 pt offset plus fade), 180 ms out | instant |
| Hover fill | `CicadaCurve.ease(0.15)` | — |
| Press | 0.97 with `CicadaCurve.out(0.12)` | — |
| A resolved row leaves | fade plus 12 pt x-offset, `out(0.15)`; the next row is selected instantly | fade only |
| Undo row | replaces the resolved row instantly; fades out over 120 ms when its 5 s end | instant |
| Cited-span wash | `spanReveal`, a 250 ms fade | fade |

**DR-62. Use custom curves only.** `[lint]` `EasingLintTests`.
- The curves are `CicadaCurve.out`, `.inOut`, `.drawer` and `.ease` (new; Emil's control points).
- Never use `.easeIn`, and never use the built-in `.easeOut` / `.easeInOut` outside `Theme/`.
- Springs have zero bounce, except for rare moments of delight (≤ 0.3).

**DR-63. Hover is a fill change.** `[lint]` `HoverScaleLintTests`.
- A lift of 1–2 pt with no scale is allowed only on sparse tiles that open something: empty-state actions, and Sources and Integrations tiles. This is `hoverLift` with its scale default set to 1.
- A hover `.scaleEffect` lives only in `HoverLift` and `MarkHover`.

**DR-64. Icon hover is binding (the owner's rule).** `[test]` A cooldown test.
- `iconHover` plays on **interactive** glyphs when their control is hovered, at most once every 2 s per icon. The cooldown lives inside `IconHover`.
- It never plays on decorative glyphs or on a keyboard selection. The `selected:` bounce is removed.
- Raster images use `markHover`.
- Under Reduce Motion, a ring replaces the movement.

**DR-65. Entering and leaving.** `[lint]`
- Anything that appears starts at scale ≥ 0.95, combined with a fade.
- Exits are faster than entrances and move 8–12 pt.
- `.move(edge:)` is only for navigation (the Topics push).
- State seeded in `init` never animates on mount.

**DR-66. Reduced motion means gentler motion, not none.** `[test]`
- Movement is removed: scale, offset, rotation and the camera.
- Fades stay, shortened to about 100 ms linear through `CicadaMotion.fade` (new).
- The moving *value* is gated, not only its animation.
- `graph.js` reads `prefers-reduced-motion`.
- Reduce Transparency makes the rail, the command bar and every floating surface opaque.

**DR-67. Stagger only on rare first appearances,** such as Welcome or an empty state. `[review]`
- The timing is 40 ms per row and 80 ms per group, with 300 ms total at most.
- A stagger never replays on a sync refresh.

**DR-68. The keyboard map.**

| Key | Where | Does |
|---|---|---|
| ⌘1–6 | anywhere | switch page (instant) |
| ⌘K | anywhere | open the palette under the command bar; ⌘⏎ inside it toggles Find ↔ Ask |
| ⌘F | pages with something to find | focus the page's `CicadaSearchField` |
| ↑ / ↓ | list focused | move the selection; the question swaps in place |
| ↑ / ↓ | question focused | move the option highlight |
| Tab | columns | move focus: list → question → Reader |
| 1–9 | question | resolve with option n (one tap, then Undo) |
| ⏎ | question | resolve with the highlighted option; in Other…, Submit |
| O / L | question | Other… / Not now — ask again in 7 days |
| ⌘Z | during the Undo window | undo the last answer |
| ⌥↑ / ⌥↓ · ⌥⌘[ | Reader | previous / next cited span · back |
| Esc | anywhere | close the rightmost open thing (DR-28) |
| ⌘, · ⌘+ ⌘− ⌘0 · ⇧⌘I | anywhere | Settings panel · chrome zoom · Import… (via `IntakeRouter`) |

Menu commands stay in `Support/FindCommands.swift` (`HiddenShortcutLintTests`). In an HTML mock, keys are shown as hints only, because the canvas cannot bind them. `[test]`

**DR-69. Hit targets and hover twins.** `[lint]` Via DR-53.
- Icon buttons are at least 28 pt, and nothing is smaller than 20 pt.
- Anything shown on hover has a text twin: `.help`, an accessibility label, or visible text.

**DR-70. Everything scales with `uiScale`:** fonts, spacing, row heights, column widths and icon sizes. Radii stay concentric (DR-12). `[test]` Snapshots at 0.8×, 1.0× and 1.4×.

**DR-71. Light and dark are both first-class.** Every mock and every PR screenshot shows both. `[review]`

**DR-72. Tokens have one source of truth.** `CicadaTheme.swift` owns §3. A token-export script writes the mocks' CSS variables from it, so the mocks and the app cannot drift apart. `[test]` A golden JSON file.

**DR-73. Ship behind a flag, one screen at a time.** `[review]`, plus a `[test]` that the flag exists.
- The new chrome is gated by `cicada.design.focus`, a Debug-menu toggle that stays off until sign-off. Old and new can then be compared on the demo bank in one click.
- A screen is done when its PR has screenshots at 1440 × 900 and 1200 × 800, in both themes and in every column state.
- The PR adds no lint-allowlist entry without giving a reason.

---

## 9. Rulings log

Each ruling is dated. A new ruling is added as a new line, and old lines are never edited. Owner quotes are verbatim.

- **2026-09-23: Direction D is chosen.** Owner: *"in regards to the design pass for the inbox and reader, i like C's minimalist side panel but i also like A's having a column for the inbox, then the open question and the reader to the right. But i do think, if no inbox item is selected, then only the questions should appear, and when clicking on one, it opens to the right. I also like from C the design itself, with the highlights, the resume button and stuff. with the search bar on top and the memory bank selector."*
  - Taken: C's rail, command bar, material and components; A's columns, made progressive (§5.3).
  - Not taken: A's indigo, inset content panel and labelled-sidebar default; B's meadow neutrals, fern accent, header wash and New York quote.
- **2026-09-23: Instrument Serif is retired.** Owner: "i dont like this font … change it to something more minimal".
  - Display type is SF Pro Display through `displayFont` (DR-15). New York goes too, because the quote is now SF 15 (DR-18).
  - This departs from Track Z's Z10 room sentence: its lead becomes SF Pro Display and its tail becomes SF in `textSecondary`, in the same slot.
- **2026-09-23: Settings becomes an in-app panel.** Owner: "a window inside the app, like the one in claude desktop app" (DR-33). The `Settings{}` scene is removed.
- **2026-09-23: One tap wins over C's click-then-Resolve.** UX principle 1 outranks C's two-step flow. Safety comes from a 5 s Undo, implemented as a send delay (DR-42).
- **2026-09-23: The system accent replaces Cicada indigo.** This follows from taking C's material. The Linear report's §4.7 idea of a nature-derived accent is declined, because nature lives in art (DR-13).
- **2026-09-23: The Sleep page gets a quick engine and model menu.** Owner: "there should be a quick and easy way to change which model to use for consolidation" (§10, Sleep).

This file landed on its own, as docs, on 2026-09-23; CLAUDE.md points here. CLAUDE.md's "Meadow (round 3, G137)" (type, accent, neutrals), "Sleep page" (the sentence's typeface), Settings navigation (a panel, not a scene) and "Find palette" (no palette animation) paragraphs keep describing what ships until the track that implements D lands. That track updates each paragraph in the same PR that changes the code.

---

## 10. Extending D to other screens

Each screen below names the problems it fixes: **P1** chrome louder than the work; **P2** colour spent everywhere; **P3** provenance in machine vocabulary; **P4** inverted density; **P5** a forked component vocabulary.

**Home (G108; ⌘1 once built). Fixes P1, P5.** Search comes first, in the command bar's grammar, under the painted Home band (DR-13). The bar grows into a 560 pt field in a 760 pt column. The same palette sits underneath it, so `QuickMatch` stays the one ranker. Below the field come three things:
- "Needs you": the top three inbox rows in STATE 0 styling, each opening the Inbox in STATE 1.
- "Recently learned": claims with their source lines.
- Consolidate, as the page's one `PrimaryActionButton`.

**Graph. Fixes P1, P5.** A full-bleed canvas. The chrome is floating overlays in one `LiquidGlassGroup`: the view switch (text tabs), the Context legend (collapsed by default) and the zoom control. The bank chip, "Find a node" and the Search button retire into the command bar. ⌘K finds nodes, and ⌘F opens an in-canvas find that overlays the canvas and never pushes it. A selected node opens the entity card as the detail column, and its evidence opens the Reader column: the same progressive columns as the Inbox.

**Clusters. Fixes P2, P4.** A list page. The eyebrow reads "Clusters · 957 entities", the type filter is text tabs with counts, and the duplicate type-chip rail goes. STATE 0 rows are one line (type dot, name, count). A row opens the entity card as the detail column. "11/11" and "Labels" fold into one View menu.

**Feed. Fixes P1 (the header-under-titlebar bug), P4, P5.** A list page. The eyebrow is followed by text tabs: Recent · Relevance, then the kinds. Rows are 56 pt: mark, title and source line, with a thumbnail only for media. A video plays in the detail column (`MediaPreview`). Intake comes in through ⇧⌘I, a drop or the Dock, never through a page button.

**Sources. Fixes P2, P4.** A list-and-grid page. The eyebrow reads "Sources · n connected", with "Add a source" as a `NeutralButton` in the eyebrow row. The G124 cards stay but are restyled: `bgFocus` with a resting ring, no shadow, and a hover lift (each card is a sparse tile that opens something). Dropping the duplicate "Nothing yet" lines takes a card from 128 pt to 104 pt or less. The contributor strip becomes a labelled bar, and a card opens its source detail as a column.

**Sleep. Fixes P3, P4.** The study room stays: the art, the worm, one sentence, and Consolidate as the page's only `PrimaryActionButton`.
- **New (owner, 2026-09-23): a quick engine/model menu** beside Consolidate. It is a `NeutralButton` that reads the current engine ("Claude plan · Sonnet ▾") and writes the same `PUT /sleep/engine` that `EngineChooser` writes. It shows both the `preview.manual` and `preview.scheduled` lines, so ruling 4 (a scheduled cycle never spends plan quota) stays visible rather than applying silently.
- **Details** (Last cycle · What's waiting · Readout · Past nights) use the list grammar: rows and section labels, no bordered cards.
- **"Rested 0%"** becomes a sentence instead of 26 empty boxes.

**Settings panel. Fixes P1, P5.** Built per DR-33. Each pane is one group of rows on `bgFocus` (DR-37), and native controls follow the system accent. Integrations shows real marks: its chat-bubble fallback for Claude Code and Cursor is a bug (DR-52).

**Entity card. Fixes P3, P4, P5.** A detail column, opened from Graph, Clusters or ⌘K.
- **Header:** the name (`displayFont(size: 22)`), the type as a `Tag` with a dot, and a one-line summary.
- **Body:** one scroll replaces the four underline tabs. It shows, in order:
  - beliefs as rows (the claim in 14 regular, its evidence chip, its age);
  - "Changed recently";
  - "Where this came from" (DR-54), which opens the Reader column;
  - "Look it up at";
  - History, with commit subjects behind a disclosure.
- **Chips:** at most two per claim (speaker and age). Everything else goes in `.help`.
- **Nothing to show:** a page with nothing readable says so in words and never shows raw YAML.

**Projects (future page; backlog row added 2026-09-23). Fixes P3, P4.** The first screen designed for D from the start. It uses the same columns: projects list → project → Reader.
- **Timeline band.** A project opens on a 96 pt band: dated claims and episodes on a horizontal track, a "Today" marker in `textPrimary`, and planned dates (G17 `due`, G140 `expected_end`) as hollow ticks. A project with no plan shows only what has happened. The band carries no painted art, and its dots use data hues.
- **What's happening.** Under the band sit sentences that carry their provenance, for example: "Yesterday · You got a PDF setup guide for the Northwind lab cluster from Leo Fischer, and are connecting to run the Lantern demo."
  - Each noun links to its entity: the PDF opens as media, and the cluster's page holds its specs as claims.
  - The sentence's evidence chip opens the Reader.
  - Dates are relative, computed at read time (DR-58).

---

## 11. Lints that enforce these rules

**Existing lints and tests.** All of these stay; some are retuned.

| Lint / test | Enforces | Change for D |
|---|---|---|
| `FontLiteralLintTests` | DR-15, DR-16 | ban `.custom(` entirely once Instrument Serif is deleted |
| `CountLiteralLintTests` | DR-21 | none |
| `LiquidGlassLintTests` | DR-14 | allow the rail and the command bar |
| `MeadowPlacementLintTests` | DR-13, DR-50 | allowlist unchanged (EmptyStateView) |
| `HiddenShortcutLintTests` | DR-68 | none |
| `MotionLiteralLintTests` | DR-61 | add `ambientMaxDuration`; UI ceiling 0.3 |
| `SettingsRowLintTests` | DR-33 | point at the panel's rows |
| `SleepNumbersLintTests` | §10, Sleep | none |
| `ThemeTokenTests` / `GraphPaletteTwinTests` | DR-1, DR-8 | the graphite table |
| `LogoAssetTests` | DR-52 | add "every channel resolves to a mark" |

**Proposed new lints and tests.** Each is a source scan plus an allowlist file.

| New lint / test | Enforces |
|---|---|
| `ThemeContrastTests` | DR-2, DR-3, DR-6: every text token on every permitted surface |
| `AccentSourceLintTests` | DR-4, DR-5: `accent` = `Color.accentColor`; no `Color.blue`; a per-file cap |
| `SelectionTintLintTests` | DR-22, DR-45: no `accent` in rail, sidebar or tab files |
| `ElevationLintTests` | DR-9, DR-10: `.shadow(` and `.stroke(CicadaTheme.border` only in `Theme/` |
| `DividerLintTests` | DR-11: `Divider()` only on the allowlist |
| `ContinuousCornerLintTests` | DR-12: no bare `RoundedRectangle(cornerRadius:` outside `Theme/` |
| `DisplayFontCallSiteLintTests` | DR-17: `displayFont(` only at its five call sites |
| `MonospaceLintTests` | DR-19: `design: .monospaced` only on the allowlist |
| `SectionLabelLintTests` | DR-20: `.tracking(` only in `Theme/`; no all-caps labels |
| `WhiteLiteralLintTests` | DR-40: `.white` only in `Theme/` |
| `SegmentedPickerLintTests` | DR-45: `.pickerStyle(.segmented)` only under `Views/Settings/` |
| `ProvenanceIdLintTests` | DR-54: no raw `ep_`, `harness` or `origin` interpolation in `Views/` |
| `KeyboardAnimationLintTests` | DR-60: no `withAnimation` on keyboard paths |
| `EasingLintTests` | DR-62: no `.easeIn(`; no built-in `.easeOut` / `.easeInOut` outside `Theme/` |
| `HoverScaleLintTests` | DR-48, DR-63: hover `.scaleEffect` only in `HoverLift` and `MarkHover` |
| `IconButtonHelpLintTests` | DR-53, DR-69: an image-only `Button` needs `.help` |
| `PriceLintTests` | DR-59: no "$", token or cost strings in `Copy*` or `Views/` |
| `ColumnLayoutTests` | DR-26, DR-27, DR-36: widths and first-content offset at 1440 and 1200 |
| `SingleBankSwitcherTests` | DR-24: exactly one `BankSwitcher` in the tree |
