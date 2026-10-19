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
  - ~~painted art on EmptyStateView, Welcome and onboarding, the Home band and the Sleep room~~ — **painted art is retired (2026-10-16, §9)**. The study room, pixel art, is the one illustration: the Sleep page and onboarding;
  - the reward moments the room carries: a finished cycle, an import landing.
- **Where they may not:** behind data, on a row, or as a data encoding.
- **No header wash.** There is no procedural header wash, and `SkyBand.ships` stays off (TODO ruling 10).

**DR-14. Liquid Glass stays in the chrome.** `[lint]` `LiquidGlassLintTests`.
- **Where it is allowed:** the rail, the command bar, floating controls, and the one `PrimaryActionButton` per page.
- **How it is applied:** only through `liquidGlass(_:in:)` in `Theme/LiquidGlass.swift`. It is gated on macOS 26 and becomes opaque under Reduce Transparency.
- **Never glass:** the focus card and the Reader.

### 3.8 Progress fill: the Projects band

| Token | Dark | Light | Use |
|---|---|---|---|
| `progressFill` (new) | `#6FB57B` | `#37753D` | the Projects band's fill, from the project's first moment up to Today (the list row's mini bar retired with Projects v2, 2026-10-19); solid, never a gradient |
| `progressOpenEnd` (new) | white 22 % | black 22 % | an unplanned project's open end, on the band — drawn only past Today, never a remainder |
| track (existing `bgBadge`) | `#3A3B3F` | `#D9D9D6` | the unfilled part of the same bar |

Both values come from the Meadow `meadow` hue (H ≈ 130). Light is `meadow` itself. Dark is `meadow` (`#7FC98A`) with less lightness and chroma, so it sits calmly on graphite instead of glowing. Contrast, measured as a graphical object (≥ 3:1):

| Pair | Dark | Light |
|---|---|---|
| fill on track | 4.57:1 | 3.93:1 |
| fill on `bgBase` | 7.65:1 | 5.19:1 |
| `bgBase` knockout ring on fill (around every node that sits inside the green) | 7.65:1 | 5.19:1 |
| `textSecondary` planned-diamond outline on track | 7.33:1 | 8.16:1 |

- **One exception to DR-13.** This is the only place a Meadow hue encodes data: progress on the Projects band (ruling of 2026-09-23, §9). It never appears as a row fill, a tag, a tint or behind text.
- **Nodes stay neutral.** Everything drawn on the band is in the text ladder, as a shape: `textPrimary` for done dots, done diamonds and the Today marker ("You, today"); `textSecondary` for planned diamonds and ongoing spans; `textTertiary`, dashed, for a moved milestone's earlier date and the bracket that joins it to the new one. Each node inside the green gets a 2 pt `bgBase` knockout ring. The fill is the band's one hue. Selection is a `textPrimary` ring, never the accent (DR-5).
- **No plan, no track.** An unplanned project's bar (band and list row) is the fill plus a dashed open end, never a grey remainder: a remainder would read as "almost done". "N of M done" is shown only when there is a plan; there is never a percentage (G141 R-PJ11).
- **Disclosed:** the unfilled track is not held to 3:1 against its surface: `bgBase` 1.68:1 dark / 1.32:1 light, and `bgSelected` (a selected list row's mini bar) 1.40:1 / 1.15:1. Nothing depends on seeing its end: the plan's end carries the last milestone's `textSecondary` diamond (≥ 7:1) on the band, and "N of M done" or "Next · …" says it in words on the row and in the bar's `.help`.

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

List pages have no page title (DR-25). Apart from the Settings panel, `PageTitle` survives only on Home (the Sleep page lost its "Sleep Cycle" title on 2026-10-16, §9; it opens on its eyebrow). `[lint]` `DisplayFontCallSiteLintTests`.

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
- **Tooltips.** Every cell has a tooltip naming its page and shortcut ("Inbox ⌘6"). The first tooltip waits 450 ms; after that, the next one opens instantly (R-F2).
- **Pages, in ⌘ order:** Home ⌘1, Graph ⌘2, Clusters ⌘3, Skills ⌘4, Sleep ⌘5, Inbox ⌘6, Sources ⌘7, Projects ⌘8 (ruling of 2026-09-23, §9), Looks ⌘9. The Feed retired into Sleep and Skills took its cell (⌘ map A, ruling of 2026-10-16, §9). The rail's order is its ⌘ order, so a new page joins at the end and no shortcut moves. The first tooltip waits 450 ms; after that, the next one opens instantly (R-F2).
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

**DR-25. List pages have no page-title band.** Inbox, Clusters, Sources and Projects open straight into an **eyebrow row** (and so does Sleep, a room-over-list page, §5.2): at least 28 pt tall, 20 pt below the titlebar. `[test]`
- **Left:** the eyebrow, in `metaFont` medium, `textTertiary`, tabular. It reads "Inbox · 6 pending", or "Inbox · 1 of 6 · Conflict" when a question is open.
- **Right:** text tabs with counts (DR-45).
- **The old subtitle** moves into the `?` popover and the empty state.

**DR-26. The first content item starts no more than 120 pt below the window top,** at 1× and the default window size. The budget is 52 + 20 + 28 + 12 = 112 pt; today the figure is 211 pt. `[test]` A UI test measures the frame.

### 5.2 Page types

| Type | Anatomy |
|---|---|
| List page (Inbox, Clusters, Sources, Projects) | eyebrow row, then progressive columns (§5.3) |
| Canvas (Graph) | full-bleed; chrome only as floating overlays (§10) |
| Room (Home) | one 760 pt column; a `PageTitle`; details as a list |
| Room-over-list (Sleep, 2026-10-16) | the eyebrow, a fixed-height art band (whole points per cell, no card), the room's three lines in the 760 pt column, then a list page's tab row (sticky once the room scrolls away) and progressive columns |
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

**DR-39. Secondary detail starts collapsed,** and each viewer's choice is remembered. This generalised Sleep's Details, which retired on 2026-10-16 (its sections are the Sleep page's tabs now, §9). `[review]`

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
| Name (a placeholder person, 2026-10-14) | the name field, Submit, "I'd rather not say" |
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
- **Art:** none (2026-10-16, §9). Every empty state is the plain variant — the Inbox's "all caught up" included — set as text alone, centred in the space its page gives it, with no card around it (DR-37).
- **Text never sits directly on art.**

**DR-51. The rail numeral is the only badge.** Counts inside a page are text in tabs or eyebrows, never capsules. `[review]`

**DR-52. Marks follow Track L.** `[test]` `LogoAssetTests`, and every channel in `channel_registry` resolves to a mark.
- **Use the real mark.** Wherever a service is named, show its real mark through `OriginMark` / `LogoImage`. The lookup order is: the installed app icon, then the bundled PNG, then an SF Symbol. Never show a generic glyph when a mark exists.
- **Never alter a mark.** A mark is never recoloured and never sits on a tinted tile. It stands bare: 12 pt in rows, 14 pt in the source line, 20 pt in the Reader header.
- **Marks whose background is the mark** (`hermes`) are clipped to their own curvature, never recut.
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
- **One source-line label joins them on the Projects page (G141 PJ-5):** "Set by you in Cicada", for an event the person wrote in the app with no sentence behind it. It is a source line, never a chip — it opens nothing.
- A chip is a `Tag` with the speaker's mark, never a coloured pill.

**DR-58. Relative dates are computed when read, never stored.** `[test]`
- Descriptions lead with the age phrase ("4 weeks ago · last mentioned Aug 25").
- Row ages are compact ("4w", "8mo"), with the absolute date in `.help`.
- A time shows only when the episode stores one.

**DR-59. Copy.** `[lint]` `PriceLintTests`.
- Sentence case and plain verbs; no "!" and no bare "%".
- A meta line is one line.
- A question is stated once per surface.
- No prices, token counts or "$" anywhere except the Sleep page's Past reads run detail and engine menu (ruling of
  2026-09-03, narrowed 2026-09-28, surface renamed 2026-10-16, §9); there a figure carries its basis in words and a
  percentage its noun.

---

## 8. Motion and interaction

**DR-60. Keyboard actions never animate.** This applies to ⌘1–9, ⌘K, ⌘F, Esc, 1–9, O, L, ⏎, ↑/↓, ⌥↑/⌥↓ and ⏎ in the palette. Their pointer equivalents animate only where the table under DR-61 says so. `CicadaMotion.paletteIn` and `paletteOut` are deleted: the palette appears and leaves in one frame. `[lint]` `KeyboardAnimationLintTests`: no `withAnimation` in any handler reachable from `.keyboardShortcut`, `onKeyPress` or `FindCommands`, with an allowlist.

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
- The motion is one small grow-and-settle (scale 1 → 1.05 → 1, no rotation) on every glyph, the rail's included; never SF Symbols' `.wiggle` (2026-10-06 ruling).
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
| ⌘1–9 | anywhere | switch page (instant) |
| ⌘K | anywhere | open the palette under the command bar; ⌘⏎ inside it toggles Find ↔ Ask |
| ⌘F | pages with something to find | focus the page's `CicadaSearchField` |
| ↑ / ↓ | list focused | move the selection; the question swaps in place |
| ↑ / ↓ | question focused | move the option highlight |
| Tab | columns | move focus: list → question → Reader |
| 1–9 | question | resolve with option n (one tap, then Undo) |
| ⏎ | question | resolve with the highlighted option; in Other…, Submit |
| O / L | question | Other… / Not now — ask again in 7 days |
| ⌘Z | during the Undo window | undo the last answer |
| L / M / D | Projects, a project open | focus Log progress / add a milestone / mark the selected thread or milestone done (Projects only: on an Inbox question, L is still "Not now") |
| ← / → | Projects, the band focused | step along the band's nodes; ⏎ opens the node's source in the Reader |
| ⌥↑ / ⌥↓ · ⌥⌘[ | Reader | previous / next cited span · back |
| ⌘Y | Looks, a look open | enlarge its screenshot over the board, in one frame (as Quick Look); Esc closes it first |
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
- **2026-09-23: The Projects band is a green bar that fills up, and its nodes are clickable.** Owner: *"as to the timeline colors, maybe like a green bar that fills up? something that fits the aesthetic. make nodes in the timeline clickable and stuff."*
  - The band's progress is `progressFill` (§3.8), a meadow green that fills the track from the project's first moment up to Today. With a plan, the track ends at the latest target and "N of M done" sits beside it in words. With no plan, the fill runs to Today and the track ends in an open end.
  - Every node on the band is clickable: dots, diamonds and spans. A click selects the node (a `textPrimary` ring) and opens its card in the detail column. A hover shows the sentence's first words and the date.
  - This is the one place a Meadow hue encodes something (an exception to DR-13). It replaces §10's "dots use data hues" and settles the spec's R-PJ21: nodes are neutral shapes, and the fill is the only colour.
- **2026-09-23: Projects is the eighth rail page, ⌘8, after Sources.** Owner, on G141's open decisions: *"on the things you mention as my decision, i'd go with your suggestions"*. The suggestion was the first free cell after Sources, so that no existing shortcut moves; Home took ⌘1, which makes that cell the eighth (DR-22, DR-68).
- **2026-09-23: DS-1 ships without the `cicada.design.focus` flag (DR-73).** The tokens are static reads several hundred call sites share, the `Settings{}` scene and the panel cannot both own ⌘,, and a dual chrome doubles the surface the live check must cover. Comparison is the orchestrator's installed build against the branch on the demo bank. Revisit if the owner asks for side-by-side.
- **2026-09-23: DR-1's "blue exceeds red by at most 3" holds for the window family, not the fills.** `bgOption`, `bgButton`, `bgButtonHover`, `bgSelected` and `bgKey` measure 4 and `bgBadge` 5, copied from the approved mock; the table wins. `ThemeTokenTests` pins ≤ 3 for `bgRail`…`bgMenu`, ≤ 5 for fills, chroma ≤ 4 for all.
- **2026-09-23: `accentText` follows the Mac's accent (DR-4, DR-5).** For the default blue it is exactly §3.3's values; for any other accent `AccentInk` darkens (light) or lightens (dark) in 5 % steps until it clears 4.5:1 on `bgBase`, capped at 60 %.
- **2026-09-23: The pre-D token names stay as aliases (§3.1).** `surface` has no D row and maps to `bgFocus`; `border` / `borderLight` are the opaque composites of the resting ring and the input border over `bgBase`, because AppKit and graph.js need opaque colours; graph.js's dark edge twins `borderLight`.
- **2026-09-23: The retired indigo stays as a data hue (DR-8).** `statusColor(.active)` and the usage heat ramp keep `#8C9CFF` / `#4A5BD6`: data hues do not move when the chrome's accent does.
- **2026-09-23: `bodyFont` stays 13 (DR-16).** "13 → 14 on detail surfaces" is `detailBodyFont` (14), adopted by the focus card and the Reader; a global 14 would resize every list body the ladder wants at 13.
- **2026-09-23: The rail's light hover is `#E3E3E0` (DR-22).** Light `bgHover` equals `bgRail` (`#EFEFEC`) and would not show; `bgButtonHover`'s light step is the mock's value.
- **2026-09-23: The command bar is a SwiftUI toolbar's principal item, and the palette hangs 4 pt under the titlebar (DR-23).** AppKit owns the titlebar, so the drag area and double-click-zoom are its own; macOS 26's shared toolbar platter is hidden so the bar draws its own surface. The mock's palette overlaps the titlebar strip by 6 pt; drawing into AppKit's titlebar risks hit-testing fights, so it starts just under it.
- **2026-09-23: The palette's "Switch to <bank>" row and the intake card's switch stay (DR-24).** They act on the same `BanksViewModel` in the same window; split-brain is two switcher views drifting apart, and `SingleBankSwitcherTests` holds the view to one.
- **2026-09-23: ⌘, and ⌃⌘S live in `Support/ShellCommands.swift`, not `FindCommands.swift` (DR-68).** DR-68's "menu commands stay in FindCommands" is about ⌘K / ⌘F, which stay there (`HiddenShortcutLintTests`); the shell's two commands get their own file with the same one-home lint (`ShellCommandsTests`). ⌃⌘S is inserted before the system's View-menu sidebar group, never replacing it, because that group also carries Enter/Exit Full Screen.
- **2026-09-24: When neither floor fits, the question and the Reader share the width 440 : 360 (R-DI7, DR-27, DR-31).** With the list already hidden, a question at 440 and a Reader at 360 still overflow at ≥ 1.3× zoom with the labelled sidebar in a 1200 window. They split what there is in that ratio rather than push the Reader off-window: DR-31 wins over DR-27's floor.
- **2026-09-24: STATE 0 can sit beside a Reader (R-DI8, §5.3).** A Reader opened elsewhere (an evidence chip, the palette's Conversations, another page before a switch) stays beside the full-width list of one-line rows. The page never closes a Reader it did not open. Esc closes it (DR-28); a row click applies DR-29, and the Reader stays only if the question cites that conversation.
- **2026-09-24: A mention found by name is semibold and unwashed, captioned "Found by searching the conversation" (R-DI11, DR-57).** Only an asserted span gets the wash and the underline (`CitedSpan.current`). This follows DR-57's "bold when derived" and CLAUDE.md's provenance rail over §5.3 item 3's unconditional wash, in the focus card's quote and in the Reader alike.
- **2026-09-24: The Inbox's in-page search field retires (R-DI14, DR-46).** This is DR-46 applied ("never on the Inbox"), and it reverses G136 S5's Inbox field. ⌘K's Inbox group is its twin: it indexes every question with the same `InboxSearch.fields` and lands in STATE 1.
- **2026-09-24: The demo bank has no removal, divergence, normalization or informational item (R-DI21, DR-43).** DR-43 has the app reach every variant through the demo bank; adding the four is a `demo_bank.py` change outside DS-2. Until a backend batch adds them, `InboxFocusCardFitTests` renders every variant from the server's own shapes.
- **2026-09-24: A held answer is also sent when the window closes, and a page switch does not send it (R-DI3, DR-42).** The flush points are the window ending, the next answer, `ActivateBank` (before the bank moves), the main window closing and quit (capped at 3 s). A held answer whose question left the snapshot inside the window is dropped, not sent: an agent or Sleep already settled it, and a 404's rollback toast would misreport the person's answer as reverted.
- **2026-09-24: `ResolveGrace` is a held `InboxResolve` in the `Store`, not a new `Mutation` (R-DI2, DR-42).** DR-42 sketches "a `Mutation` with a hold". The send is the unchanged `InboxResolve`, so its optimistic hide, rollback toast and refresh are reused and no second rollback path exists.
- **2026-09-24: `ReaderInspector` is renamed `ReaderColumn` (R-DI6, DR-31).** DR-31 names the old type; it is no longer an inspector. `ReaderColumn` is the Inbox's third progressive column, and pages that have not adopted `ProgressiveColumns` host it through `ShellReaderHost`, which sizes it before the page.
- **2026-09-24: With the list hidden, the Undo row sits at the head of the question column (R-DI25, DR-42).** DR-42 places it in the list; when DR-27 hides the list, the row moves above the card in its short form so Undo and ⌘Z stay reachable for the whole window. One Undo row is on screen at a time.
- **2026-09-24: No check line on the focus card until G61 S3 serves a result (R-DI13).** `check` on the wire is S2's read-only census, which nothing acts on yet; the mock's "Check now" and "Checked by Cicada" line render a result S3 will serve. The hint row keeps "Open source ↗".
- **2026-09-24: DS-2 ships without the `cicada.design.focus` flag (R-DI1, DR-73).** R-DS1's reasons hold unchanged; comparison is the installed build against the branch on the demo bank.
- **2026-09-24: Home is the D-Home mock (R-HS2, DR-13, DR-17, DR-50).** The band is the bundled `hero-day` painting (its `-dark` sibling at night), 120 pt, the meadow line kept in view and faded into `bgBase` from 40 % down. The headline is one line, "What would you like to remember?", in `PageTitle` on the row under the band, so text never sits on paint. The italic second line and the drifting cloud retire. The field is 640 pt, the approved mock's value, over §10's 560.
- **2026-09-24: No Consolidate on Home (R-HS3, G125 R10).** §10's bullet contradicted a CLAUDE.md ruling (one Consolidate, on the Sleep page), and §1 says the rule is what gets fixed, so §10 is corrected. The waiting count stays a link to Sleep. "Recently learned" waits for a backend field: the claims a cycle wrote, with their spans.
- **2026-09-24: The Sleep page's "Runs on …" caption retires into the engine button (R-HS9, DR-38).** The caption and the button would say the same words twice. The button stays while a cycle runs, beside Cancel's caption, because a change applies to the next cycle.
- **2026-09-24: The engine menu is a `NeutralButton` and a popover, with a native menu `Picker` for the model (R-HS10, DR-40, DR-45).** A popover carries marks, both previews and a model picker that a native `Menu` cannot. The mock's model text tabs are not used: a model roster is the plan's own list, of any length, and DR-45's tabs are single-select filters that deselect on a second tap. The free-text model id stays in Settings → Engines.
- **2026-09-24: One preview wording app-wide (R-HS11, DR-38).** "When you start a cycle" and "Scheduled cycles", in the menu, in `EngineChooser` and in Settings → Sleep, where there were two wordings for one pair of facts.
- **2026-09-24: Sleep's Details use the list grammar (R-HS15, DR-7, DR-21, DR-37, DR-48).** Section labels over rows, no cards. Last cycle's failure and warning rows wear the `warning` glyph with no fill (DR-7), "Rested" is a sentence with its breakdown on hover, the readout is key–value rows whose counts go through `UsageFormat`, and an episode row carries one glyph.
- **2026-09-24: Settings raises sheets, never popovers (R-HS16, DR-33).** The panel is modal and inset only 40 pt, so a popover anchored at a row's edge could open past the screen (owner-reported: a folder's Manage). Manage, Wispr Flow and a connector's Connect/Manage open in one `SettingsSheet`; a lint holds `Views/Settings/` to no `.popover(`.
- **2026-09-24: ⏎ on a Settings row in ⌘K opens it (R-HS20, DR-60).** It lands on the row through `AppRouter.openSettings`. R-SU12's explain-only row existed because a closure could not open the `Settings{}` scene; that scene is gone, so the hint and the row's "Open" link go too.
- **2026-09-24: DS-3b ships without the `cicada.design.focus` flag (R-HS1, DR-73).** R-DS1's reasons hold unchanged; comparison is the installed build against the branch on the demo bank.
- **2026-09-24: DS-3a ships without the `cicada.design.focus` flag (R-DG1, DR-73).** R-DS1's reasons hold unchanged; comparison is the installed build against the branch on the demo bank.
- **2026-09-24: The Graph's floating group is an opaque floating surface, not glass (R-DG2, DR-14, §10 Graph).** `LiquidGlass.swift` keeps glass off the canvas until the G109 frame-time check has run (R-SU17's precedent). Revisit when an in-app p95 frame time with glass on measures under 16.7 ms on the live bank.
- **2026-09-24: On the Graph, a swap keeps the Reader and × takes it (R-DG7, DR-29).** DR-29 closes the Inbox's Reader on a swap; the Graph's canonical flow is the Reader's "Show on graph", which exists to swap the entity beside the sentence, so a node click keeps it. The column's × and a click on empty canvas close the column and its Reader together (the approved mock). Esc still closes one thing at a time (DR-28).
- **2026-09-24: The entity card keeps four text tabs with counts (R-DG17, §10 Entity card).** §10 sketched one scroll; the owner-approved mock keeps Content · Perspectives · History · Timeline as DR-45 text tabs. Underline tabs are retired.
- **2026-09-24: DR-68 gains the Graph's keys (R-DG6, R-DG11).** ⌘F finds on the canvas (an overlay); Esc closes find, the Legend, the Reader, then the entity column; ⌘[ goes back along the entity trail. The Graph's `?` lists them with the canvas's gestures.
- **2026-09-24: Under 340 units of canvas the Graph's floating group hides rather than clip (R-DG3).** 340 is the widest group ("Legend · filtered", − + fit, pan) plus its inset each side, pinned by a fit test. At 1× only the labelled sidebar with the Reader and the column open at 1200 pt reaches it; the group returns when either closes. Disclosed, not fixed.
- **2026-09-24: DS-3c ships without the `cicada.design.focus` flag (R-DL1, DR-73).** R-DS1's reasons hold unchanged; comparison is the installed build against the branch on the demo bank.
- **2026-09-24: A quote's markup is stripped, not rendered, and its role labels go at every line start (R-DL2, R-DL3, DR-18, DR-56).** DR-18 allows no bold or italic in a quote (semibold is the found mention's), and the strip deletes only, so every span still maps exactly. The Reader keeps a turn's lines and draws a bullet as "•".
- **2026-09-24: A label that is exactly a page's id reads as that page's name (R-DL5, DR-54).** It is display only; the wire is unchanged, so a resolve still sends the id.
- **2026-09-24: Clusters' "11/11" and "Labels" fold into one View menu, tabs are navigation, and find is ⌘F (R-DL9, DR-46).** §10 asks for one filter per page; two controls that both narrowed the list read as two filters.
- **2026-09-24: Clusters rows carry no logo and no age (R-DL11, DR-8, DR-48).** The approved mock draws no logo, and `/graph` nodes carry no `lastReferenced` to age a row by. §10's row anatomy is otherwise kept.
- **2026-09-24: The Feed's sort tabs read "Relevance · Recent", and one sort is always on (R-DL13, DR-45).** The approved mock draws them in that order (§10 lists Recent first). DR-45's tap-again-for-All does not apply to a sort, which has no "none".
- **2026-09-24: The Feed keeps its `+` as an eyebrow `IconButton` opening the one intake's Add-a-source sheet (R-DL14, G126).** This departs from §10's "never through a page button"; the owner's DS-3c brief and the approved mock keep it.
- **2026-09-24: The Feed's detail column has no "Show in conversation" (R-DL15).** `/sources` items do not carry the episode that saved them; the row returns when they do.
- **2026-09-24: A Sources tile's live dot keeps `success` (R-DL20, DR-7).** This departs from DR-7's list, as the approved mock draws it: it is state, shown once per tile. Failures speak in `warning`, never `danger`.
- **2026-09-24: A contributor's drill-down is a detail column, not a sheet (R-DL22, DR-31).** The sheet hid the Reader its "from conversation" opens.
- **2026-09-24: Text tabs give way rather than overflow the eyebrow row (R-DL25, DR-45).** They drop their counts first, then fold into a menu, so a tab is never clipped at a narrow width or a large zoom.
- **2026-09-24: PJ-5 ships without the `cicada.design.focus` flag (R-PP1, DR-73).** R-DS1's reasons hold unchanged; comparison is the installed build against the branch on a freshly generated demo bank.
- **2026-09-24: The open end of an unplanned bar is `progressOpenEnd` (R-PP9, §3.8).** §3.8 asks for "a dashed open end" and named no token; the approved mock's dash (white 22 % / black 22 %) joins the table.
- **2026-09-24: A band pick scrolls its row into view; the sections above do not fold (R-PP11, DR-30).** The mock folded them; a folded story hides the context a reader came for.
- **2026-09-24: The band's label is "Progress of …", never "Timeline" (R-PP12, G141 R-PJ22).** The entity card's Timeline tab (contested beliefs) can share the screen in the third column; a lint holds the page's strings to it.
- **2026-09-24: The owner reads as the sentence's own word with a small "you" tag, and opens nothing (R-PP15, DR-44).** A literal "You" would break the sentence; the tag sits on `bgBase` because `Tag`'s `bgSelected` would vanish on the chip's own fill.
- **2026-09-24: "Set by you in Cicada" is DR-57's sixth label, as a source line (R-PP16).** `EvidenceChip` keeps its five: an app-written event has no sentence to open.
- **2026-09-24: A quiet thread's follow-up links to its Inbox card; it is not answered inline (R-PP18, DR-42, DR-59).** The brief asks for the link; the Inbox owns answering and its Undo, and a question is stated once. The mock's inline options are not built.
- **2026-09-24: The Log's Undo withdraws what the server wrote; it is not DR-42's send delay (R-PP21).** The day comes back from the server (`when.py`) and is shown before Undo; the note keeps the person's words.
- **2026-09-24: A milestone's date comes from a native date picker, never typed words (R-PP22, G141 R-PJ6).** Python decides every date from words; a second date grammar in the app would drift. There is no Move yet; a moved milestone's chain still shows.
- **2026-09-24: G150 ships without the `cicada.design.focus` flag (R-B23, DR-73).** R-DS1's reasons hold unchanged; comparison is the installed build against the branch on a freshly generated demo bank.
- **2026-09-24: A project's Backlog section reads Open · Doing · Done · All, and a dropped item shows only under All (R-B19, DR-45).** The "resting projects only under All" precedent (R-PP6). Folded, the section says "n open" beside its label; open, the tabs carry the counts — the brief's "count in the eyebrow" without saying it twice (DR-38).
- **2026-09-24: A backlog item's id is on its row, as a G-id is (R-B24, a DR-54 departure).** DR-54 keeps machine ids in `.help`; a backlog id is the address the person and agents cite ("cite `G74a` the way you would cite a ticket"), so it is shown — in `metaFont`, `textTertiary`, tabular, never monospace (DR-19). The file path stays in `.help`.
- **2026-09-24: A backlog item's description and notes render as page prose, not in the quote face (R-B20, DR-18).** DR-18's door is for words someone said in a conversation; a note is a written document that may hold lists and code, so it goes through `MarkdownBody`. Each note still says who wrote it, with their real mark (DR-52).
- **2026-09-24: The Projects page's third column is one slot — the Reader, else a backlog item, else an entity's card (R-B21, DR-28, DR-31).** Opening one replaces the other; opening an item closes a Reader the old selection opened (DR-29); Esc closes the Reader, then the item or card, then the project.
- **2026-09-24: The Home band and the Welcome hero follow the clock, not the theme (owner, round-4 D4; G144; DR-13, DR-50).** The hero paints `hero-day` from sunrise to sunset in the Mac's time zone and its `-dark` sibling, painted as dusk or night, at dusk and at night, whatever Appearance says; Settings → General → Scene offers Automatic, Always day and Always night. This overrides R-M2's "the dark theme always gets the `-dark` painting" for the hero alone: every other painting, the empty states and the Sleep room still follow the theme. It does not touch TODO ruling 10 — `SkyBand.ships` stays off. Text never sits on the paint (DR-13, DR-50), so no contrast pair changes.
- **2026-09-24: An agent's chip names its model when capture recorded one (round-4 D1, C3; DR-57).** "<agent> replied" becomes the agent line — "Claude Code · Opus 5.5 · high effort · Sep 24" — when the span's turn carries a model; without one the chip is unchanged. The model is a fact about who spoke, so it rides the label rather than a second chip. The hover's header, the Reader's meta line and its turn labels say the same line (`ModelNames`); an app with no capture says "model not shared by this app" in the hover, never a guess.
- **2026-09-24: Settings → Agents' one-click actions are `NeutralButton`s (round-4 D5; DR-40, DR-44).** Connect for me, Copy setup prompt, Open in Cursor and Set up Claude. The brand-tinted capsule that carried Cursor's deeplink was a tinted pill (DR-44) and goes; the setup prompt sits in a read-only box, in the body face, before it can be copied, so the person reads what their agent will run.
- **2026-09-24: The afternoon is golden hour, and Scene has four choices (owner, round-4 decision 8; R-HO1, G144).** Automatic · Day · Afternoon · Night. The afternoon runs from two hours before sunset (never before solar noon) to the end of civil dusk; dawn's twilight is night, because there is no dawn painting. `SceneTime` sits beside `SkyPhase`, which the Sleep room keeps. This supersedes the three-way Scene of the clock ruling above (round-4 D4).
- **2026-09-24: One painting view, three framings, one crop rule each (C10; R-HO2, DR-13).** `.hero(band:)` owns the band's height, crop and fade and puts the meadow line at two thirds of it; `.fullBleed` aspect-fills with the meadow line at 0.66 of the height, so the Welcome card's zone stays on the low meadow at any window shape; `.pane(_)` centres ART_DIRECTION §4's focal point and shifts as little as possible to keep its keep-box in view. No framing ever shows the painting's edge. Phase B builds on these and never draws a second painting view.
- **2026-09-24: Home's painting moves (owner: "animated, keeping its realism"; R-HO3, DR-66).** One `PaintedScene` (C10) draws the painting with slow one-way clouds, grass swaying ±0.75° from its roots, seeds by day, fireflies and stars by night, a light that breathes and a 52 s camera breath. This overrides R-HS2's "the drifting cloud retires" and R-M6's "grass never moves" and 8 pt drift for `PaintedScene` alone; the empty states keep R-M6. Reduce Motion and Low Power make it gentler, never frozen: the camera, the clouds and the seeds' travel stop, while the grass keeps a ±0.25° sway and the stars and fireflies their glow. That one slow rotation departs from DR-66's "movement is removed" bullet, as rationale-F's approved Reduce Motion column draws it.
- **2026-09-24: A scene change crossfades in 1.2 s, 0.6 s under Reduce Motion (R-HO4, DR-61, DR-62).** Opacity only, over the same composition, on `CicadaCurve.ease`. It sits outside DR-61's 0.4 s ambient ceiling on purpose: the owner asked that switching be smooth, and two lights of one painting are not a layout change.
- **2026-09-24: The scene always draws at 1.01 overscan (R-HO5).** The grass plates are not paintings on their own (the art review, §3), so a swaying clump must never uncover the plate's edge; the camera drifts only within the breath above 1.01.
- **2026-09-24: Clouds draw at `MeadowRules`' opacities, 0.85 by day and afternoon and 0.4 at night (R-HO10, DR-13).** ART_DIRECTION §5's values, not rationale-F's CSS stand-ins. In Home's band they are high clouds whose lower half peeks in at the top, sized so they never reach the hills.
- **2026-09-24: Home's band is 208 pt and fades from 72 % down (F-09; R-HO6, DR-26).** The band is paint, not content, so DR-26's 120 pt budget does not bind it; the headline row stays the first content. The fade starts below the meadow line, which sits at two thirds of the band; rationale-F's 58 % would dim it.
- **2026-09-24: A living painting rests when nobody can see it (R-HO7).** One `TimelineView` at ≤ 30 fps, 15 under Low Power, paused while the window is occluded, minimised, hidden or on another Space, while the Welcome covers Home, and absent off-tab. A visible window that is not key keeps moving. Budget: Home adds at most 10 points of one core over a static page.
- **2026-09-24: The pastel set replaces the round-3 art, and `-dark` retires (owner, round-4 decision 13; R-HO8, DR-13).** Thirty-six files in three scenes of one composition — the delivered set with its retouch pass (both moons, the afternoon highlights, the night clouds) — held to their bytes and to per-role caps within a 20 MiB budget, up from 4 MiB for the resolution the owner asked for. The heroes ship at 2376 × 1485, the generator's ceiling, which is under ART_DIRECTION's 2880. An empty state picks day under light and night under dark.
- **2026-09-24: The painting's particle colours live beside the art, not in `CicadaTheme` (R-HO9, DR-13, DR-72).** ART_DIRECTION §2 keeps its swatches out of the theme; they are the same in both themes because the painting does not follow the theme.
- **2026-09-24: Home follows F-09 (owner, round-4 decision 8; R-HO11–R-HO13, R-HO15, R-HO18).** Today is one row that opens Sources, with the three busiest origins' marks, names and counts. Needs you is the Inbox's glyph, question and age, with *Open Inbox* at the label's right, so "All N" retires. Last read stays under it. The field stays 640 pt. *Make it yours* appears once after the Welcome's Start, never for the demo, and × or Hide dismisses it for good.
- **2026-09-24: Getting started keeps its rows this round (R-HO14).** Its "Last synced …" comes through T-Sources' `SourceRow` and F-09's two-column grid through phase B's `SetupProgress`; a second last-sync line here would fork the words.
- **2026-09-24: Settings → General follows F-10, where F-10 is true (owner, round-4 decision 6; R-HO16, DR-40).** The groups are Look, Startup and When Cicada is closed, then Setup. *Show in menu bar* is new and on by default; the Dock icon stays, so hiding the bookworm never strands the app. F-10's "Starts quietly: no window" is not used, because Cicada opens its window at login today. "Calendar polls keep going after you quit" is not used either, because the Calendar read is app-side and stops with the app.
- **2026-09-24: The command bar's stack glyph goes (owner, round-4 decision 11; R-HO17, DR-24).** The bank's name and its chevron remain, as in B's search bar.
- **2026-09-24: Clusters is mock A's icon-led cards (owner, round-4 decision 9: "i like the clusters page from A the most, and i'd have the ability to add a picture"; F-11; G146 plan R-PE12; DR-8, DR-25, DR-45, DR-48, DR-63).** With nothing open, All is a card per type — People, Projects, Companies, Tools, Concepts and Media two to a row, the rest three to a short row — each its outline glyph in its hue, its plural name, its count and "Show all ›"; tiles are 56 pt with the page's picture, its name and one line in words, six in the first row of cards and four after. No tags, no percentages, no confidence. A type tab is one card with every tile. While ⌘F is open the list's rows (with pictures) stand in for the cards, so the find field is never rebuilt mid-word. The eyebrow, text tabs as navigation, ⌘F find, the one View menu (its *Expand all* shows every tile, a card per row), DR-68's keys and the progressive columns are unchanged; beside a card the list keeps its rows, now with a picture and an age, recently mentioned first. This replaces DS-3c's STATE 0 rows and reverses R-DL11 ("no per-row logo"): `/graph` nodes now carry a picture and `lastReferenced`.
- **2026-09-24: Every entity avatar is `EntityPicture` (C11; G146 plan R-PE14; DR-8, DR-12, DR-52, DR-53).** 20–88 pt; a circle for a person, a 3:2 well for media, a continuous square otherwise. With no picture a person is initials in a 1.5 pt hue ring, a company a monogram in its hue on `bgOption`, every other type its outline glyph in its hue — never a solid hue fill (R-08's must-fix). A logo stands bare; a photo, a Contacts picture and a thumbnail carry the resting ring. A hover over an editable picture dims it under a camera (`CicadaMotion.hover`); a tile adds nothing more — the picture itself is the button (2026-09-30).
- **2026-09-24: A person's card opens with mock C's top (owner, round-4 decision 10: "for the person page, i like option C's top part of the page with the name of the person, the pic, and everything honestly"; F-12; G146 plan R-PE16; DR-16, DR-17, DR-20, DR-44, DR-52, DR-54, DR-57).** An 88 pt `EntityPicture` — a button: pick, drop, right-click, its hover veil saying "Change…" — the name in `displayFont(size: 24)` (C-09 had 28, R-09 22; 24 keeps the display role and matches Home's headline), the Summary as a two-line standfirst, the picture's source in words with what can be done about it ("Photo from your Contacts · Use initials instead"), and the facts strip on `bgOption`: Works at · Role · Known since · Last mentioned · Conversations · Contacts, each cell only when it has something true to show, each over its compressed provenance line. Every other type keeps DS-3a's header with a 40 pt picture beside the 22 pt name and the source line only when a picture exists. In the card style (Clusters) the header adds "Show on the graph"; there a person's card may grow to 1024 units.
- **2026-09-24: A person's card has F-12's body (owner, round-4 decision 10, "and everything"; G146 plan R-PE17 … R-PE19; DR-36, DR-38, DR-39, DR-57, DR-58, §3.8).** Two columns when the card is at least 880 units wide, one below. The main column: *What Cicada believes · N* (newest first, four then "Show N more"), each belief signed — "Written by [mark] Claude Code · Opus 5.5 · high effort · Sep 24", the model from the captured turn and never a guess — the signed line taking the age `Tag`'s place, since it carries the day; *Where this came from*; *The page* — the Rendered/Source body behind a remembered disclosure, closed by default (DR-39), because the hero shows the Summary and the beliefs carry the facts; then Look it up at and Details. The aside: *How you know <first name>*, a radial map of up to six graph neighbours on neutral wells with hue rings around the person's picture, the owner first at the top, with one plain sentence ("Connected to N pages in your memory") — never generated prose; and *What's happening*, the person's projects' next milestones and happenings in the Projects band's marks (a hollow diamond, a `progressFill` span, a dot), from the Projects page's own cache. Every other type's body is unchanged.
- **2026-09-24: Claude Code wears the Claude mark with an app-drawn ">_" badge (owner addendum 2, R-AG8, DR-52).** The Claude app keeps the plain mark. The badge is SF Symbol terminal.fill on a bgMenu plate with the resting ring, bottom-trailing at half the mark (never under 7 pt), composed in LogoImage — the mark file is never edited or recoloured. The two byte-identical Claude rasters are deleted; nothing drew them any more.
- **2026-09-24: The agent selector selects in neutral and confirms in green (R-AG16, DR-5, DR-7).** The selected pill is bgSelected with the strong ring, sliding under CicadaMotion.standard; the live ✓ is success — DR-7's import ✓ extended to "an agent Cicada has seen connect", the same kind of fact.
- **2026-09-24: Ollama wears a Local tag and the leaves-your-Mac note is a pure function (decision 5, R-AG14, DR-44).** No card says "slower"; the note names where reads go and is absent for Ollama.
- **2026-09-24: Onboarding is pages, not one scroll (owner, round-4 decisions 1–7; G145; R-OB1).** Owner: *"I definitely like A's welcome page."* This reverses round 3's "two surfaces, not steps" (`docs/specs/2026-09-23-round3-design-onboarding-intake-home.md:189`): Welcome and You're set on the full painting with a card; four working pages in a split frame whose pane gives way before the column; the topbar under the titlebar band (R-OB23). DR-13, DR-17, DR-40, DR-60.
- **2026-09-24: A tick starts a source; × only where a run can stop (owner: "start syncing as soon as connected … do give an x button to cancel sync right there"; R-OB2, R-OB8, R-OB10).** Nothing is pre-ticked; an untick stops keeping up and keeps what came in; a one-time read and an import finish on their own. DR-41, DR-58.
- **2026-09-24: *See how* is a drawn wireframe, never the vendor's UI; its camera glides 0.9 s in 3 s steps (R-OB21, a DR-61 exception like R-HO4).** The vendor appears as its real mark and name only (DR-52); Reduce Motion crossfades each step in place (DR-66).
- **2026-09-24: You're set's quote is SF 17 regular with no rule (G153; R-OB15; DR-11, DR-17, DR-18).** Not the quote face (a person's or agent's words only) and not a display line. This departs from F-07's mock (quote face with a rule) and from G153's first wording ("the display face for the line"), which the G153 row now states as shipped.
- **2026-09-24: The quiet login start (R-OB18; G143).** A launch macOS makes as a login item opens no window: the menu-bar bookworm and the watchers run, the Dock icon stays, and any click on it, *Open Cicada* or a file open shows the window. Supersedes R-HO16's note that F-10's "no window" is not used; F-06 and F-10 now say it, split by the menu-bar switch.
- **2026-09-24: Onboarding v2 ships without `cicada.design.focus` (R-OB22, DR-73).** R-DS1's reasons hold unchanged.
- **2026-09-24: The demo banner sits under the page, never over it (owner, round-4 decision 1; T-Demo R-DT8; DR-5, DR-9, DR-10, DR-40).** F-08's bar is a floating surface laid out as a safe-area inset under the page area and the Reader, so no row hides behind it and the tour's scrim, an overlay on the page area, never covers it. Its one primary is *Finish setting up →*; on the Sleep page the demo shows two accent fills, one per surface. F-08's "nothing you do here is kept" became "nothing you do here reaches your own memory": the demo keeps its own edits until it is deleted.
- **2026-09-24: Coach marks are floating surfaces over a page-area scrim (G152; T-Demo R-DT9, R-DT10, R-DT13; DR-5, DR-9, DR-10, DR-40, DR-60, DR-66, DR-68, DR-69).** The scrim is `scrimPanel`, the Settings panel's, with a hole around the stop's target and the focus ring on its edge; the command bar, a titlebar item, draws that ring itself. The rail, the page and the Reader are inert under it; the titlebar is inert but lit. Next is a `NeutralButton` (⏎), Skip tour a `TextButton` (Esc), ← / → step, and every glyph has a text twin. A step changes in one frame; only the first appearance moves — 6 pt over 240 ms, a fade under Reduce Motion; the scrim fades in on the same 240 ms token rather than F-08's 300 ms. The stops are the owner's brief (command bar, Home, Inbox, a person card, Projects, Sleep), not F-08's rationale list.
- **2026-09-24: The demo bank now holds every Inbox variant (T-Demo R-DT16; closes R-DI21, DR-43).** A removal, a divergence and a normalization are written by `demo_showcase`, the merge card is served (its subject now has a page), and the informational conflict was there all along (`uses` is multi-valued).
- **2026-09-28: Plan usage and model prices show on the Sleep page's Details and engine menu, nowhere else yet (owner; TODO ruling 12; DR-21, DR-51, DR-58, DR-59).** Narrows the 2026-09-03 no-price ruling. Past nights and Last cycle carry one line per cycle in the list grammar (no capsule, DR-51); an opened cycle lists Models with calls, tokens in and out through `UsageFormat.count` with a unit noun (DR-21), and cost with its basis in words ("charged", "at list price"). A plan cycle reads as its window's before → after with the note that it includes anything else used meanwhile; a ChatGPT plan call says its tokens were not reported rather than showing zero. The engine menu's plan rows say "18% of 5-hour window · resets 3:40 PM" (relative words from an absolute time at read, the absolute one in `.help`, DR-58) and key rows their model's price per million tokens. One currency formatter, `UsageFormat.currency` (locale, two decimals, "< $0.01"). Every string is built in `Copy` and `CycleUsageText`, so no `%` sits on a `Text(` line under `Views/Sleep` (`SleepNumbersLintTests`).
- **2026-09-30: The video boards ship (owner: "I also like the watch video designs, apply them."; G162; DR-5, DR-6, DR-28, DR-34, DR-37, DR-40, DR-44, DR-45, DR-48, DR-50, DR-51, DR-60, DR-69).**
  - Density (§5.5): a video in the picker is `RowMetrics.videoPick`, 64 pt, with an 88 × 50 frame and a 400-unit picker column; a Feed video row stays 56 pt with a 64 × 36 frame and its length in a corner badge, the triage row a 48 × 27 one. A page with no stored thumbnail shows the neutral play tile; no thumbnail URL is ever derived from an id.
  - The picker's check is `NeutralCheckToggleStyle`, a `ToggleStyle` (VoiceOver keeps checkbox semantics): a `textPrimary` tick on `bgSelected`, a `textSecondary` ring, never the accent. The existing native `.checkbox` uses stay.
  - The Videos tab's strip is one plain 44 pt row on `bgBase` with *Choose videos…* as a `NeutralButton` (no card, no glyph). It stands where the Connected strip stands on every other tab and scrolls with the list.
  - While choosing or running, the picker's text tabs (Not yet read · Queued · Read, disjoint, with counts) replace the sort and kind groups, so the eyebrow never holds three tab groups. *Copy for an agent* is the card's one primary (⏎).
  - The run card's meter is one segment per video up to ten and a continuous bar above, always with its noun. Above ten the rows group as Couldn't do · Picked up · Waiting · Recorded. The card's body scrolls inside it and its footer (*Copy for an agent*, or *Copy the prompt again* while running) stays pinned under the body at every size; the Feed does not wrap the card in a second scroll view (VideoRunLarge).
  - A video's detail column puts "Why it's saved" and "Saved from" side by side under the block, filling the column (VideoDetailLight), and stacks them only when the column is too narrow for both at 220 units each.
  - The Sleep page's Details › What's waiting gains one Videos row: a play glyph, the one queue wording as text (DR-51), and a trailing *Choose videos ›* link. It starts nothing.
  - Not taken from the boards: every string that names a provider or model as the one doing the job (owner 2026-09-30, TODO ruling 17). A name reaches the screen only as data, such as the harness a record carries.
  - Not yet done: comparing each board with captures of the running app (1440 and 1200 wide, dark and light, rail and labelled sidebar). The layout above was checked against the boards by reading the code only, so a capture pass is owed before the branch is called finished.
- **2026-09-30: A site's mark is drawn like a browser tab's icon (G166, reading the web; DR-12, DR-52).** `SiteIcon` shows a site the agent reads for the person — a site, not a service Cicada connects to, so DR-52's Track L sizes do not bind it. It is 20 pt as a Settings row's leading mark and 16 pt inline beside a line of text (the Feed's Read section, Home's reading line): the sizes a browser gives a tab's favicon, which is the object being shown. The favicon Cicada's own API serves gets a 4 pt continuous corner, so a square icon never bleeds; it is never a circle and never ringed. Until it arrives, a known family (LinkedIn, X, Instagram, TikTok, Reddit) shows its bundled Track L mark, bare and unclipped at the same size, so the row does not move when the favicon lands; any other site shows a ring monogram, never a solid fill. On Home the reading line's marks overlap by 4 pt, like a stack of tabs, so a few sites read as one group beside the count; each stays whole and unaltered.

- **2026-10-01: The study room's sprites play per frame from their sheets (owner: "all the sprites with the animations"; TODO ruling 18 — R-BW3, R-BW4, R-BW11; DR-61, DR-66, DR-13).** Frame timings are data in each sheet's JSON, read by one `SpriteLayerView` / `BookwormView` clock that fires only at frame boundaries; `CicadaMotion` spells the caps (shortest and longest frame, loop range, beat ≤ 800 ms, perk ≤ 400 ms, transition ≤ 1.6 s, the Low Power slowdown). The weather crossfade stays 0.4 s. Reduce Motion holds each sprite's key frame — the worm's R7, kept for the room rather than DR-66's gentler profile, because a sprite's key frame already carries its state — and the sprites rest while their window cannot be seen, like Home's band (R-HO7). Nothing painted enters the room (DR-13): the environment behind the window is pixel art on the lattice.

- **2026-10-01: Error is black X eyes plus the drop; the menu bar keeps one dark-outline sheet (owner; G176; ruling 18; DR-50, DR-66).** The reference's error expression has one diagonal X in each lens, never red pupils. The menu-bar art is unchanged between appearances; no dark-bar variant.
- **2026-10-02: The study room has independent scenery and night-or-rain lighting (owner; G176; R-Z11/R-A13 amended; DR-13, DR-50, DR-61, DR-65, DR-66).** `SceneClock` supplies day/dusk/night unless Choose pins it; the chosen source supplies the base weather. Running adds calm mist, completion a rainbow or shooting star. Room props relight on the existing 0.4 s opacity crossfade, instant under Reduce Motion. The worm uses a separate lighting-sheet fade, suppressed while a transition or beat is active (integration re-review amendment below). A flash stays refused. The lamp still means schedule and art never starts work.
- **2026-10-02: Settings → Sleep → The scenery uses labelled sprite thumbnails (owner; G176; DR-13, DR-33, DR-37, DR-40, DR-48, DR-65, DR-69).** Source, Choose-only time/weather rows and Preview form one existing Settings group. The three time and five weather choices use native focusable buttons, text below the key-frame art, a neutral selected ground/ring and VoiceOver labels/selected traits. This explicitly permits pixel-art selection thumbnails and an inert live room preview in Settings; no text or data sits on art and no painting enters a form. Keyboard selections never animate. Local weather's disclosure names the public city's weather read; changing the source turns its separate app-side gate off.
- **2026-10-02: The wall clock is real-time state art (owner; G176; DR-13, DR-50, DR-61, DR-66).** Black hour/minute hands and a thin red second hand select whole-pixel sheet frames from the Mac's time; dark-room tags darken the dial and hands. Its own leaf ticks once a second only while visible; the room has no new timer. Reduce Motion removes the second hand while hour/minute keep time. The clock is inert, with help and a VoiceOver text twin after the window. These angle frames are state choices, outside the ambient-loop duration caps.
- **2026-10-02: G176 integration retains ruling 18's 1,800-boundary/minute cap (DR-13, DR-50, DR-61, DR-65, DR-66).** Rain holds its 48 unchanged frames for 100 ms rather than 80 ms, preserving the seam and no-flash check. Worst steady state across all 240 environment/mood/lamp combinations is rainy-night + digesting + lamp lit: 1,758/minute including 60 clock ticks, down from 1,908. Settings pauses room sprites as well as weather and the clock. The clock follows the verified art placement (94,34). App composites cover both zooms, every environment/mood/lamp, overlays and three fixed clock times; ImageRenderer panes cover all scenery sources in both appearances. The art integration report records exact paths and snapshot limitations; owner motion and CPU acceptance remain the merge gate.
- **2026-10-02: Mascot selector names Bookworm (G176/G127; owner).** Settings → Sleep → Mascot sits beside The scenery in the existing list/tile grammar, with room/menu key frames, a neutral selection ring and checkmark, keyboard focus and selected VoiceOver text. One pure registry and per-viewer preference route sprite names/cache identity; a later character adds its own art and one entry. No state meaning changes. DR-13, DR-50, DR-61, DR-65 and DR-66 apply under TODO ruling 18; tile choices never animate.
- **2026-10-05: The rail starts under the titlebar; the window controls sit on the titlebar band (owner; DR-22, DR-23).** Owner: *"the black side panel bar extends to the top of the window going through the window control buttons. Shouldnt be the case. there should be some type of background for the window controls."* This amends §5.1's diagram, whose rail column ran up into the titlebar: the 52 pt titlebar is one band across the full width, on the window's own `bgBase` (`syncWindowChrome`), holding the traffic lights, the sidebar toggle, the command bar and `?`; the rail (and the labelled sidebar) fills only below it — `.background(CicadaTheme.bgRail, ignoresSafeAreaEdges: [])`, pinned by `NavRailTests`. A bare colour background ignores the safe area and was what ran the fill behind the controls.
- **2026-10-05: A queued episode row copies what Sleep would read (owner; DR-48, DR-38, DR-54).** Owner: *"clicking on sleep queue entries should copy whatever it is we are consolidating to the clipboard and say smth like Copied to clipboard! briefly … a day when it was added/last modified for conversations … the whole rectangle should be clickable."* `EpisodeRow` is one plain button over its whole rectangle (hover stays a fill, R-HS15): a click copies the backend's `copyValue` — a page's link, a conversation's session id, a tab group's links, a folder file's path, else the episode id — through `AppPasteboard`, and a brief toast names it ("Conversation ID copied", "Link copied"; `CicadaTiming.copiedConfirmation`, announced to VoiceOver). The meta line names that target instead of the time; the row ends with its day (a conversation's last capture, else when it arrived), and the tooltip carries both full times. The `url` origin reads "Link", never `"url".capitalized`.
- **2026-10-06: The Home band is off behind `HomeBandLayout.showsBand` (owner; G189(a); DR-13, DR-17, DR-26, DR-50).** Owner: *"remove the picture banner for now."* `HomeView` draws `HomeHeroBand()` only when the constant is true, and it is `false`: the code, `bandHeight` and the `PaintedScene(.hero(band:))` call stay, the same move as `SkyBand.ships` (TODO ruling 10). Welcome and onboarding keep their `PaintedScene`. The headline is now Home's first content, in `PageTitle` (DR-17) at the room pages' 24 pt top inset (`HomeLayout.headlineTopInset`), so DR-26's 120 pt first-content budget is met on Home by the headline. This does not retire the earlier Home band rulings (2026-09-24: D-Home mock, the clock-not-theme scene, the three framings, the clouds); they apply again when the constant flips. A Home revamp (G189(b)) is a separate decision.
- **2026-10-06: Every glyph hovers like the rail (owner; DR-64).** Owner: *"the animation of the help icon wiggles way too much. Make all the icons that wiggle like that the same as the ones in the side panel."* `IconHover` drops SF Symbols' per-layer `.wiggle` (its strength cannot be set) and the `subtle:` switch: every `iconHover` is the rail's 1 → 1.05 → 1 nod over `CicadaMotion.iconNodDuration`, with no rotation. The `selected:` bounce is unchanged.
- **2026-10-06: The rail wraps the content with a rounded join, and Home scrolls as one page under a soft top edge (owner; amends 2026-10-05; DR-12, DR-22, DR-23, DR-9, DR-10, DR-13, DR-14, DR-36, DR-60).** Owner: *"i dont like how the boxes get clipped with the portion of the search bar. also the 90 degree cut corner of the side panel doesnt look that good."* (1) The content's top-leading corner, where it meets the rail and the titlebar band, is a rounded join at `CicadaTheme.contentCornerRadius` (= `radiusLarge`, 16 pt, fixed under zoom like every radius, DR-12). It is decorative, not concentric: the corner sits a whole rail (or labelled sidebar) width in from the window's edge and under the titlebar, so it shares no centre with the window's own corner. The rail's own `bgRail` fill reaches into the corner (`RailCornerFillet`, no hit testing) — a fill, never a shadow or glass. The titlebar band, the window controls and the rail's `ignoresSafeAreaEdges: []` background stay exactly as the 2026-10-05 ruling set them. (2) Home's headline, field and blocks share one scroll view, so no card is cut flush under the field; the first block sits one `HomeLayout.blockGap` under it. With results showing, the page pins to the viewport by its height and the results fill the rest; the page never uses `scrollDisabled` (inherited, it could freeze the results' and Ask's own scroll views), and the field keeps its place in the tree. The swap is instant: typing and Esc drive it (DR-60). (3) Where the page meets the titlebar band, macOS 26's soft scroll edge (`scrollEdgeEffectStyle(.soft, for: .top)`, through the one helper `softTopScrollEdge()` in `Theme/ScrollEdge.swift`, SDK- and runtime-gated; earlier systems keep the plain edge) eases content out instead of a hard cut. It is the system's edge treatment of the chrome boundary — not a glass material on content (DR-14), not a shadow (DR-9/10), not a header wash (DR-13) — and it changes nothing about the opaque titlebar band.
- **2026-10-07: The rail and titlebar are one frame; the page is a panel with a rounded top-leading corner (owner picked variant A over a rounded rail; amends 2026-10-06 (1) and (3); DR-9, DR-12, DR-14, DR-22, DR-23).** Owner: *"the fix of the side panel corner is wrong. Its like the app has rounded corners which makes the side panel have a weird pointy end."* — then, shown both answers offscreen, *"go variant A."* Cause: the 2026-10-06 fillet painted `bgRail` into the page's top-leading corner while the titlebar band above stayed `bgBase`, so the rail ended in a horn along the band's line; `RailCornerFillet` is removed. The band takes the rail's surface (`CicadaTheme.titlebarBackground`, the window colour `syncWindowChrome` sets; `windowBackground` stays `bgBase`), so band and rail read as one L-shaped chrome; this amends 2026-10-05, which put the band on `bgBase`, and the rail itself keeps its `ignoresSafeAreaEdges: []` background. The page host is a panel (`shellContentPanel()`): its top-leading corner alone is rounded at `contentCornerRadius` (`radiusLarge`, fixed under zoom, DR-12), filled with the page's `bgBase` and clipping what it holds, so a page no longer scrolls up into the band — the panel's edge is the boundary 2026-10-06 (3)'s soft scroll edge used to ease. The rejected answer (B: band unchanged, the rail column's own top-trailing corner rounded) is not kept as code. A fill and a clip, never a shadow or glass; the traffic lights, the toggle, the command bar and `?` do not move. Pinned by `NavRailTests`; `RailCornerSnapshotTests` renders it offscreen on request.
- **2026-10-07: An old page's header says when it was last mentioned, not how sure Cicada is (owner, G194 D4; DR-58, DR-59).** When the page's newest source is more than 90 days before the viewer's today, the entity card's meta line reads "Active · last mentioned Feb 2025": the confidence word is replaced, not joined, so the line stays one line (DR-59), and confidence is never shown as freshness. The month is absolute (`RelativeDay.monthYear`, the viewer's language); DR-58's age phrase leads descriptions, and this is a meta line, so `.help` carries the number and the full day ("Confidence 99 out of 100 · last mentioned Feb 6, 2025") with the fading reason kept. A missing, unreadable or future day keeps the confidence words. The 90 days is the backend's `source_dates.OLD_AFTER_DAYS`, pinned on both sides.
- **2026-10-09: An entity card opens on its wiki page; everything else waits behind a click (owner; replaces the 2026-09-24 "A person's card has F-12's body" and the 1024-unit Clusters width in the 2026-09-24 person-card top; departs from the d-graph plan's R-DG16; DR-32, DR-36, DR-38, DR-39, DR-45).** Owner: *"when i open a node like Rodrigo's it's extremely slow and laggish. i think there is things we could just load when requested, I think the main thing i'd like show when i open an entity is its 'wiki page'."* Every type, a person's included, opens Content on its prose read as an article (`WikiArticle` / `WikiPageView`, drawn lazily), one column capped at DR-36's 760. Below it, each section is a remembered disclosure, closed until its viewer opens it (DR-39; `CardDisclosure`), that reads its data only when opened: *What Cicada believes* (a person's signed and newest first), *Where this came from*, a person's *How you know <name>* / *What you're connected to* with *What's happening*, *Look it up at*, and *Details*. Inside a disclosure the section does not repeat its own label (DR-38). A page whose prose is at most its Summary still shows its beliefs open, as R-FX11 set. A person's two-column body and the "Show the page" disclosure retire, and in Clusters every card keeps the focus width (the 1024 units retire with the two columns). The person card's top (picture, name, standfirst, facts strip) is unchanged. Each article line offers *Where this line came from* on hover and as an accessibility action, opening its section item's evidence in the Reader (DR-31), else the page's *Where this came from*. Loading is said in words (DR-32). **R-DG16 departure:** Perspectives and Timeline show their counts only once the claims are read — when a section or tab asks — not when the column opens (DR-45: a count only once it is known). On an owner-sized page the claims are megabytes, and reading them on every open is the lag this ruling removes. Do not restore the open-time claims read to bring the counts back.
- **2026-10-14: A placeholder person's question is a name field, not an option list (brief 2026-10-14; DR-40, DR-41, DR-43, DR-49).** "What's the name of your partner?" carries one option, "I'd rather not say", and takes a typed name. Drawn as options it would open on a radio row with the name behind Other… ("What's actually true?"), two steps for the one answer the card exists for. `NameBody` is free text's anatomy: the field ("Their name…", open, not auto-focused, so L and Esc work and O focuses it), a neutral Submit disabled until there is a name (its `.help` says so), and "I'd rather not say" as a `TextButton` beneath, which sends the item's own option key in one tap. An older build without the variant draws the same item as options with Other… and still answers it.
- **2026-10-14: Home's front door gets out of the way — Getting started graduates and Needs you leads for a returning person (owner ruling "Graduate + Needs you first", picked from the Home design review; amends Track I R-IB17/R-IB18 and §10's Home block order; DR-5, DR-9, DR-16, DR-35, DR-37, DR-38, DR-39, DR-40, DR-41, DR-45, DR-48, DR-60, DR-69).** Owner: *"the How to Export button … is very hard to click. I think a lot of things can be improved."* (1) **Order by state** (`HomeArrangement`): while the whole Getting started card is up and the person has no chats in memory, the column is Getting started → Today → Needs you → Needs your browser → Last read; otherwise Needs you → Needs your browser → Today → Last read, with setup's line last. *Make it yours* always comes after Needs you; the tour offer leads the first week (above the tall setup card, so never off-screen) and follows Needs you otherwise. (2) **Graduation:** "chats in memory" is a conversation source (an imported export or a connected agent) whose conversations fed at least one page — `/sources/overview`'s existing per-source page count, a fact of the bank. Then the card is one line, "Setup · N things left · Show ›" (rows not On; the schedule question and *Also on this Mac* never count), and with nothing left it is gone; its open/closed choice is remembered per bank (DR-39), and only Settings → General's *Show setup checklist* opens it whole (the Welcome's record never does). (3) **Export rows** are onboarding's 36 pt provider rows, each one button opening the drawn walkthrough (*Open … export page* and *Remind me* live in the sheet); a vendor whose export is in the bank is not asked again; a wait line leads with "Check your email for the … link" above the vendors still to ask. (4) **Targets:** `InlineLink` hits 28 pt with 6 pt of slop and a `bgSelected` hover fill, layout-neutral; a line with one destination is one row button (the waiting line opens Sleep, Last read opens that read in Details — no repeated "Sleep ›"); a page `Tag` sits in a 24 pt hit frame; schedule answers are compact `NeutralButton`s; no `.link` buttons. (5) **Empty:** an empty block is its label plus a note ("Needs you · nothing right now"), never a card holding one grey line; all three empty is one block with one action, or nothing while Getting started already says it. (6) *Make it yours* lasts one session and drops Scene while the band is off (DR-13); `PillPicker` is a recessed ringed track with a ringed `bgSelected` pill, 12 medium, 28 pt (DR-9, DR-16). (7) Find/Ask is DR-45 text tabs inside the field with a `textTertiary` glyph and no animation (DR-5, DR-60). Getting started's insides are three labelled groups (Connected, Your past chats, First read) 20 pt apart.
- **2026-10-14: The ask-why panel is the notch growing — a chrome-layer surface in notch black, not the default material (owner direction; G191 v2; DR-9, DR-10, DR-14, DR-40, DR-61, DR-66).** Owner: *"As soon as I bookmark I see the thing coming down out of the notch or the page that is the same black as the notch. It kind of is seamless and it's like liquid glass of sorts and it has the mascot."* The panel stays in the chrome layer (a non-activating floating panel, never content), but departs from DR-14's default material: its body is pure black in both appearances (`CicadaTheme.Notch.surface`), its text the dark ladder's fixed steps (`CicadaTheme.Notch`), so light text always sits on black; the only sheen is a 10 % white hairline on the grown edge (`CicadaTheme.Notch.edge`, the one `.white` it needs, in `Theme/`). Its top edge is the screen's, flush with the hardware notch; its outline (`SaveWhyNotchShape`) starts as the notch exactly — outward ears where it meets the top edge, the notch's own corners — and springs down and out into the panel with continuous bottom corners (`CicadaMotion.notchGrow`/`notchShrink`, inside the 400 ms budget; Reduce Motion draws it grown and only fades, DR-66). Without a notch the same shape grows from the top centre. Depth stays a shape, never a shadow (DR-9/10). The bookworm rides in its header as `curious` room art on the sheet's own frame timings (ruling 18, DR-61). Nothing else may use the notch tokens.
- **2026-10-15: The tenth page, Skills, has no ⌘ digit (owner, via the coordinator; amends DR-22).** The rail's order is still its ⌘ order and a new page still joins at the end, but the digit row ends at ⌘9 (Looks) and ⌘0 is Actual Size, so nothing moves to make room: Skills opens from the rail and ⌘K ("Go to Skills"), its tooltip shows no shortcut, and `RailItem.key` is nil past nine (`NavRailTests`, `SidebarTabTests`). A later page joins the same way.
- **2026-10-15: The Graph looks like an Obsidian vault at rest (owner: "Right now it looks like a weird circle. Can you look at pictures of an Obsidian vault and make it look different?"; G109; DR-8, §10 Graph).** Size is how connected a page is (distinct neighbours), confidence a small second term — this departs from `graph-viz-redesign.md`'s "confidence = size", and the Legend's key now reads "Bigger means more connected". Nodes are small dots (median ~3.5 wu, the owner's page ~6.7× that); hubs lose their ring and size floor; every pair draws one hairline at every zoom; unlinked pages form a loose halo, hidden by the Legend's *Show unlinked* switch; the pending pulse hugs its dot; names fade in with zoom, biggest first, budgeted and never overlapping (departs from "no ambient labels"). No hue moved (DR-8): only size, spacing, link alpha and width, and ring treatment. **Amended the same day (owner: "the lines connecting nodes are too big compared to the size of the nodes, they should be super thin. And nodes can be a bit bigger, relative to the amount of nodes"):** "median ~3.5 wu" is now the size at scale 1; one scale per layout puts the median dot at √(6 % of the fitted view ÷ (π × nodes)) on screen, clamped to 2.2–8 pt, and a resting link is 0.12 of the smallest dot's on-screen diameter, at most 0.75 pt (one device pixel at lower alpha when thinner); a hovered or focused link is 1 pt.
- **2026-10-15: A Looks type specimen is data, not interface type; a screenshot enlarges over the board (owner: "Having an Aa with the font and the name would be cool, or fonts if several"; "clicking the pic should expand the view smoothly, like an overlay"; DR-9, DR-15, DR-19, DR-60, DR-61, DR-66, DR-68).** The "Aa" in a look's *Type* section is the page's own drawing of its face (a transparent PNG from the capture, tinted to `textPrimary`), the same kind of thing as the screenshot. When a look has none, a stand-in "Aa" is set in the system design for the family's generic kind (serif, sans, monospace, rounded) through `CicadaTheme.font(size:design:)` and labelled as a stand-in in words; this is the only place a non-default design shows outside the ladder's own uses, it is never interface type, and no face a page names is ever loaded (DR-15 stands for every UI word). The enlarged screenshot grows from its thumbnail over the board's `scrim` on `CicadaMotion.morph` (inside the 400 ms budget), its depth a ring (DR-9); Reduce Motion fades on `CicadaMotion.fade` (DR-66); ⌘Y on the open look, Space on a focused picture and Esc act in one frame (DR-60). DR-68 gains ⌘Y (Looks: enlarge the open look's screenshot, as Quick Look).
- **2026-10-16: A Messages bubble's monogram reads as a picture; its's ground ring sits outside its face (live report on the Sleep page in dark appearance: "a near-black disc with a hairline letter"; G179; C11, DR-8, DR-9, DR-12).** In a bubble below 24 units a person's initials are half the picture's height, semibold (`EntityPictureLayout.initialsType(compact:)`); every other picture — the 20 pt rows sit beside their own name — keeps the 0.36 medium proportion. The Messages bubbles (`MessageBubbleFace`, the Sleep page's 20 pt and Home's 18 pt) inset the face 1.5 pt inside a disc of the ground's colour instead of stroking that ring over the face, which had hidden the monogram's own 1.5 pt hue ring. No fill was added, no hue moved, and depth is still a ring, never a shadow. Pinned offscreen in light and dark by `MessageBubbleFaceTests`.
- **2026-10-16: Sleep is a room-over-list page, and the Feed retires into it (owner approval of the Sleep redesign proposal, 2026-10-16; DESIGN §3, §5; DR-9, DR-10, DR-13, DR-22, DR-25, DR-26, DR-28, DR-36, DR-38, DR-39, DR-40, DR-45, DR-60, DR-68; rulings 12 and 18, R3).** Owner (2026-10-15): *"rethink the design of the Sleep page, and have the bookworm animation bigger, not inside that rectangle thing it has right now"*; *"remove the title Sleep Cycle"*; *"the Feed page would make sense to merge into Sleep"*. (1) **Room-over-list** joins §5.2: the eyebrow, the art band, the room's three lines, then a list page's tab row and progressive columns; Home stays the only pure Room. (2) **The Feed retires** (`AppTab.feed`, `FeedPage`): its list, sort and kind filter, detail column, *Save its look*, the Videos watch run and ⌘N are Sleep's Saved and Videos tabs; its Connected strip goes to Sources (whose cards already sync each source) and its export waits stay at the head of Saved (Home's Getting started shows them only until it graduates); a stored "Feed" or "Capture" selection restores to Sleep; every route to a saved item (⌘B's bookmark rows, the palette, a source's page) lands on Sleep › Saved. §10's Feed block moved under Sleep. (3) **No title:** `Copy.sleepPageTitle` retires and the page opens on its eyebrow; `PageTitle` survives on Home alone of the pages (DR-17). (4) **The art's scale** is a whole number of points per lattice cell chosen by the width the art may take — 5 pt from 880, 4 pt from 720, else 3 pt (2 pt only under ⌘+ zoom with the Reader open) — never fractional, so a resize never blurs a pixel; the art sits on the page ground with no card, its floor fading into it over its bottom five cells (a mask on the art layer, never the pile, never a shadow), and no text sits on it (DR-13). (5) **Details retires** into the tabs (DR-39 no longer has a Sleep instance): What's waiting → Waiting; Last cycle, Readout and Past nights → Past reads, where a read opens in place under its row; Details' Videos row retires (the Videos tab is the queue's one place, DR-38). (6) **⌘ map A:** Skills takes the Feed's ⌘4 and nothing else moves; for one release the first time ⌘4 lands on Skills a toast says "The Feed is now part of Sleep (⌘5) → Saved.", once per viewer (a click on the cell never shows it). DR-22's list and DR-60/DR-68's ⌘1–9 follow. (7) **Ruling 12's surface** is renamed from "Details" to "the Sleep page's Past reads run detail"; prices and plan usage still show nowhere else but the engine menu (`PriceLintTests`).
- **2026-10-16: The Sleep room's running block is one centred column, and the stage strip is a compact stepper (owner, live during a run: "those stages of reading and stuff are kind of ugly … center it"; DR-5, DR-7, DR-16, DR-36, DR-38, DR-61, DR-66).** Every row under the room — the sentence, the control group, its whisper on its own line, the notes, the schedule, the stepper and the bar — is centred in the 760 pt column; the stepper and the bar both span it. The stepper is a 14 pt marker and a 12 pt word per stage on stretching connectors: done a check in a `bgBadge` disc, current an accent ring with a live dot — the accent here is DR-5's focus-ring use, marking where the machine's attention is, and the stepper's only accent — to come an empty `textTertiary` ring, failed a `danger` cross with the word "failed" for VoiceOver. The live dot breathes on a Core Animation layer (`SleepMotion.liveBreathHalfPeriod`), lit and still under Reduce Motion. The sentence's tail leaves the display face for the ladder's 17 pt regular italic (15 pt before it wraps): it is the one secondary line, not a second title. DR-38: the stage caption ("Filing. It cannot be stopped now.") and the tail's "Batch 3 of 12 · 62 of 287 filed." retire — the legend under the bar leads with the batch, and what a stop does while it files is the control's whisper and tooltip.
- **2026-10-16: The waiting pile is pixel-art books, and the Messages row is one row (owner pick "A · Stack" from the pile mocks; DR-9, DR-13, DR-34, DR-52; ruling 18).** Owner: *"I think I would like to change the book layout of stuff … it looks kind of weird."* (1) Each waiting source is a book lying flat on the room's lattice, drawn from the `room-books` sprite sheet at the room's cell size and in its lighting — never a SwiftUI slab; thickness by count in four steps, a colour per source kind from existing palette keys (conversations with people get leaf green), two stacks before a "+N" fold. (2) Counts are UI, never paint: each sits on a whole-cell plate of the page ground inside its book's outline (DR-13), or, when the plate does not fit at the current scale, only in the tooltip, popover and Waiting tab. (3) The books are static art (one frame per step), so ruling 18's redraw budget is untouched. (4) The Messages chats' pictures ride the Messages source row (one row, no second line); a monogram bubble is a filled hue disc, because a hue ring round one letter read as an info glyph (DR-9: depth stays a ground ring, never a shadow).
- **2026-10-16: The Sleep page at rest is one headline, one row of controls, one schedule sentence (owner decision after the app QA; DR-7, DR-16, DR-38, DR-40, DR-45).** (1) The lead keeps the word — "23 to read — overdue." — in its own `textPrimary`: DR-7 keeps `warning` for the gear's dot and a failed source's first clause, never body text. (2) The one secondary line is SF regular, **not italic**, at rest and while a run reads — this amends the running block's ruling above ("the ladder's 17 pt regular italic"); the owner: no italics. (3) The lamp-off fact is said once, as the schedule sentence under the controls ("The lamp is off — I read when you ask."); the tail rungs that said it again above the controls (T11) and named the biggest pile the room already draws (T12) retire (DR-38). (4) "Reading options…" joins the control row as **Options…**, a `NeutralButton`; the engine menu and Options are drawn at Consolidate's height (28 pt compact), so the row is one height. (5) Waiting and Saved hide at a count of zero, per §10 and DR-45 (Saved stays while an export is being waited on: its strip heads Saved, R-IB22); a fresh page opens on Past reads, and "All caught up" is not said twice. The running block (centred column, stepper) is unchanged.
- **2026-10-16: Tabs that do not fit keep All and the selected one; the rest go under More (owner decision after the app QA; amends 2026-09-24 R-DL25 for the Inbox; DR-45, DR-69).** The Inbox's kind tabs truncated at 1200 pt with the Reader open ("Conf… 2 · Clarif… 1") and ran to the window's edge at 1100. `OverflowTextTabs`: every tab with its count while they all fit; otherwise All and the selected kind stay as text tabs and the rest fold into one "More ⌄" menu, drawn as an inactive text tab, listing each kind with its count. A label is never truncated, the active filter never hides inside a menu, and All is always one click away. The eyebrow keeps its words (`EyebrowRow(adaptiveTrailing:)`): the tabs are measured against the width it leaves. Pages that already fold with `AdaptiveTextTabs` (Clusters, Projects) are unchanged.
- **2026-10-16: Painted art is retired; the study room is the one illustration (owner: "I would remove the painted grass actually. Remove it from everywhere", and "In onboarding maybe doing bookworm pixel room in detail would be better, no?"; DR-13, DR-50; supersedes the painted-art rulings of 2026-09-24 — the D-Home band, the clock-not-theme hero, the four Scene choices, the moving painting, its overscan — and the 2026-10-06 band-off ruling).** (1) **Empty states** are plain, well-set text everywhere, the Inbox's "all caught up" included: a 22 pt display title, the truthful line, at most one action, centred in the space the page gives them; no grass, no cloud, no worm, no card (`EmptyStateViewTests`). (2) **Onboarding** draws the study room: the Sleep page's art (`SceneryRoomArt`) at a whole number of points per lattice cell — up to 4 over the Welcome's and You're set's card, up to 3 centred in the working pages' `bgPane` pane — its floor fading into the ground, in the person's own scenery from what is already known (no fetch), and the worm's mood set by the step (awake, reading, happy, asleep for Keep it running). No word sits on it and nothing in it is a control. A short window drops the room before it scrolls the card. (3) The Home band, the Welcome hero, the paintings (`Resources/art`) and **Settings → General → Scene** (it picked a painting) are removed. (4) `MeadowPlacementLintTests` now fails on any painted component or a bundled painting; a new painting needs a dated ruling here. The nature tokens stay, for the room's reward moments and §3.8's progress fill.
- **2026-10-17: The Sleep headline holds no empty line (owner, from the 2026-10-16 QA; amends R-Z5's reserved tail line and the 2026-10-16 "one tail line" amendment; DR-26, DR-38, DR-60).** The sentence slot is as tall as the line it shows: a line with no tail is the lead alone, and a tail takes one line (two only when a long one cannot fit at 15 pt). The cost, accepted: when a poke brings up an answer with a tail, the control row steps down by that line as the answer appears, and back up once the answer's cross-fade has finished (the outgoing line holds its place while it fades) — a step, never a slide, since a key can poke the worm (DR-60). `SleepRoomFrameTests`.
- **2026-10-17: The entity card has one row of tabs, and says a day once (QA 2026-10-16; DR-38, DR-45, DR-58).** (1) The Rendered/Source switch and Copy markdown leave the Content tab's own text-tab row and sit at the end of the header's tab row while Content shows: a sticky source `IconButton` (selected fill, never the accent — the Graph pan button's grammar) and Copy. Where tabs and tools do not fit one row (the 440 pt floor with every count showing), the tools step down to their own line, trailing — a tab label is never cut (DR-45). (2) Timeline is drawn only while a belief is contested or a belief's clock has it open — no "Timeline 0"; while the count is unknown it stays, so the row never jumps. (3) Known since gives its span from one day on, never "Oct 16 · 0 days". (4) A belief row's age `Tag` steps aside when an evidence chip it draws already names the day the belief became true ("You said · Oct 16" beside "today"). `EntityCardPolishTests`.
- **2026-10-17: What arrived is labelled by its source in the Reader and on every chip (DR-57, DR-52; follows the 2026-10-16 ⌘K fix).** A feed item's and a calendar entry's text is stored on the person's side of the episode, but nobody said it: the Reader's turn reads "From the feed" or "On your calendar" with that source's mark, never "You", and so do evidence chips, the Reader's Noted rows and Where this came from (one function, `EvidenceSpeaker.sourceSpeaker`). `ArrivedSpeakerTests`.
- **2026-10-16: The gear's attention dot is for the engine the person chose (owner decision after the app QA; DR-7).** The dot lit whenever any plan was installed but signed out, so anyone with that plan's CLI on the PATH saw "a connection needs you" for a plan nobody picked, permanently. It now lights only when the chosen engine's card is a plan that is installed and signed out; a key never set is still "not set up", and no engine read yet is no dot.
- **2026-10-16: A selectable cited passage draws its washes from a copy behind it (DR-18, DR-31; QA P1).** A selectable `Text` on macOS never reaches a `TextRenderer`, so the Reader's turns and the Inbox's quote showed no wash or underline while the navigator counted "1 of 3 cited here". `CitedPassage` keeps the words selectable and carries the wash and the underline as attributes of the one `Text` that draws them (R-DS12's attributed form, now on every macOS version for a selectable passage): a renderer-drawn copy laid out behind the words was tried and breaks lines differently from them at some widths and scales (27 of 136 measured layouts), putting the wash on the wrong words. This departs from DR-18's shape for selectable passages only: a square fill with no 1 pt padding or 4 pt radius, the text system's underline instead of 2 pt at 4 pt below, and no DR-61 fade. `.citedSpans()` is never put on selectable text; a non-selectable passage keeps the renderer.

This file landed on its own, as docs, on 2026-09-23; CLAUDE.md points here. As of DS-3b, DS-3a and DS-3c (2026-09-24), CLAUDE.md's Inbox paragraph (Features §2/3, "The page"), its "Provenance viewer" paragraph, its Home paragraph, the Sleep page's control row and Details, the Settings panel's Integrations and search, its Graph Explorer and entity-card paragraphs (Features §1), its Clusters, Feed and Sources paragraphs, and (PJ-5) its Projects paragraph describe D as it ships; every other page paragraph keeps describing what ships until that page's DS track lands. That track updates each paragraph in the same PR that changes the code.

---
- **2026-10-19: Sources answers "where did my stuff come from" in two clicks; the v2 tile grid retires (owner ruling, verbatim: *"The Sources page needs an urgent redesign. It has these graphs and stuff, and it's not intuitive … Redesigning this would be nice so that in two clicks I click on something, then I click on Chrome, and then I can see all the things that I've saved in Chrome. Instead of putting the Chrome logo maybe put the website's logo in this case. Clicking again on Sources takes me back to the main Sources page also."*; DR-5, DR-9, DR-20, DR-21, DR-25, DR-34, DR-35, DR-36, DR-38, DR-39, DR-48, DR-52, DR-58, DR-60, DR-61, DR-63; supersedes §10's Sources block and the v2 tile rulings of R-DL19/R-DL20).** (1) **Two groups, not seven kinds:** *Saved by you* (what the person saved on purpose) then *Captured for you* (what Cicada captures on its own), the split served by the backend (`intent`); rows, not tiles — mark, brand, one line of count and state (DR-34, DR-35, DR-38); a failure speaks in `warning` (DR-7). (2) **Statistics are one quiet disclosure** (DR-39): who wrote the memory and the counts, collapsed and remembered; no sparkline, week-dots or delta anywhere on the page's first screen. (3) **The second click is the list:** a saved source's detail is everything saved from it, newest first, paged; each row is the site's mark (DR-52's "use the real mark" applied to the site, not the browser: the site's own icon, asked of that site only — owner ruling 2026-10-19, `storage.md` — else a bundled family mark, else a ring monogram), the title, the day (DR-58) and the person's own why, words first; hover is a fill (DR-48, DR-63). (4) **The rail re-tap pops to the root**, on the columns' curve for a click and in one frame for ⌘ (DR-60). No accent is spent (DR-5); no shadow (DR-9).
- **2026-10-19: Projects v2 — Current and Past, one signal per row, parts that fold, a detail that says each thing once (owner ruling, verbatim: *"The project page is extremely dense: too much stuff, super unintuitive UI, too many projects, and kind of shit. It would be better to have historical and current projects. If the projects have subsections, then it should actually be a dropdown that moves if I press again. For every page in the app, if I press the button in the side panel again, it should take me to the main page of that page. The project page needs a complete redesign."*; DR-7, DR-16, DR-20, DR-21, DR-22, DR-25, DR-34, DR-35, DR-36, DR-38, DR-39, DR-45, DR-46, DR-48, DR-58, DR-59, DR-60, DR-61; supersedes §10's Projects block and the list rulings R-PP6 (Active · Quiet · All) and R-PP7 (the five-column row)).** (1) **Two text tabs, Current · Past** (DR-45), each with its count; tapping the selected one keeps it (there is no All). Which tab holds a project is `ProjectState`'s section — the agent's own rule, so the app and `cicada_project` never disagree: in motion → Current; quiet past its rhythm but heard within 90 days → **Fading**, one folded, remembered disclosure at the foot of Current (DR-39); resting — a decaying or archived page, or nothing heard for 90 days — → Past. (2) **A row is a name, one line and one signal** (DR-38, DR-48): the name over the project's one-liner, and at the end where it stands — the next milestone ("Next · First grasp, Oct 1", overdue in words, never red — DR-7), else the plan's count, else when it was last heard; Fading says how long it has been quiet, Past when it was last heard. The type dot, the mini `progressFill` bar, the next-milestone column, people, the questions count and the age column retire from the row. (3) **Parts fold under their parent:** a parent wears a chevron; a click opens it and unfolds its parts, the open parent clicked again folds them (the owner's "dropdown that moves if I press again"); the chevron folds without opening. A part whose parent sits in another group is a row of its own. (4) **Past is the archive:** its find field is always there (DR-46's page find, not opened by ⌘F), rows newest heard first under year labels, 50 at a time with "Show 50 more" — never hundreds at once. (5) **The detail says what it is, where it stands, what happened last and what's next — once each:** the name (no Project tag: the page says it) over the one-liner; three label–value rows, *Where it stands* ("In motion · 1 of 4 milestones done"), *Last* (the newest happening, its day from `RelativeDay`) and *Next* (the next milestone with its day, else the newest thread still going that Last did not already say, else "Nothing planned" with Add a milestone); Last and Next select their row on the band and unfold its section. The band stays; its header line (since · progress) retires — the summary says it. Log progress follows; then the sections — In progress, What happened, Plan, Backlog, Around this project — start folded, each with what it holds in words, and the viewer's opened set is remembered (DR-39). The eyebrow no longer says Planned / No plan yet. (6) **Projects clicked again in the rail returns to its root** (the Sources v3 mechanism, `AppRouter.reselect`): the Reader, the card or item and the project close, the find clears, the page shows its default tab; ⌘8 on Projects does it without animation (DR-60). The wire, `cicada_project` and the CLI are unchanged.

## 10. Extending D to other screens

Each screen below names the problems it fixes: **P1** chrome louder than the work; **P2** colour spent everywhere; **P3** provenance in machine vocabulary; **P4** inverted density; **P5** a forked component vocabulary.

**Home (G108; ⌘1). Fixes P1, P5.** No art: the painted band is retired with every painting (2026-10-16, §9), so the page opens on its one-line headline, "What would you like to remember?", in `PageTitle` (DR-17) at the room pages' 24 pt top inset — Home is the one page that keeps a title. Under it sits the palette's own field (`FindPanelBody` in `.page` placement), 640 pt in a 760 pt column, so `QuickMatch` stays the one ranker; Find and Ask are DR-45 text tabs inside it. The first keystroke replaces the blocks with results and Esc brings them back, never animated (DR-60). The headline, the field and the blocks scroll as one page under the soft top scroll edge. Below the field come labelled blocks of 36 pt rows, ordered by the person's state (2026-10-14 ruling): in the first week the tour offer and "Getting started" lead; for a returning person "Needs you" leads and setup is one line at the foot.
- "Getting started", while it lasts. Once the person has chats in memory it graduates to one line, "Setup · N things left · Show ›", and is gone when nothing is left.
- "Needs you": the top three inbox rows, the Inbox's own STATE 0 rows, each opening the Inbox in STATE 1.
- "Needs your browser": the pages waiting for the person's own agent to read (G166), only while any wait.
- "Today": what was captured today, and how much is waiting (a row to Sleep).
- "Last time Cicada read": the newest Sleep read and the pages it touched (a row to that read in Sleep's Past reads).
- *Make it yours* (Appearance) is a row after Needs you for the one session that follows onboarding.

Each number appears once, and each is a link to the page that owns it. An empty block is its label and a note ("Needs you · nothing right now"); all three empty is one block with one action, or nothing while Getting started already says so. There is **no Consolidate** on Home: the one Consolidate lives on the Sleep page (G125 R10). "Recently learned" (claims with their source lines) waits for a backend field.

**Graph. Fixes P1, P5.** A full-bleed canvas. The chrome is floating overlays in one `LiquidGlassGroup`: the view switch (text tabs), the Context legend (collapsed by default) and the zoom control. The bank chip, "Find a node" and the Search button retire into the command bar. ⌘K finds nodes, and ⌘F opens an in-canvas find that overlays the canvas and never pushes it. A selected node opens the entity card as the detail column, and its evidence opens the Reader column: the same progressive columns as the Inbox.

**Clusters. Fixes P2, P4.** A list page. The eyebrow reads "Clusters · 957 entities in 9 groups", the type tabs are text tabs with counts and plural names, and one View menu holds the Graph's types, labels and *Expand all*. With nothing open (F-11, 2026-09-24 ruling): a card per type, icon-led, of 56 pt tiles — the page's picture, its name, one line in words; never tags or a percentage — the picture opens the image picker on a click. A tile opens the entity card as the detail column, and the list narrows to rows with pictures and ages, recently mentioned first.

**Sources (v3, 2026-10-19 — supersedes the tile grid; §9).** A list page. The eyebrow reads "Sources · n connected", with "Add a source" as a `NeutralButton` in the eyebrow row. With nothing open: two groups of 56 pt rows — *Saved by you*, then *Captured for you* — each row a bare mark, the brand and one line ("342 saved · Watching"); no tiles, sparklines, week-dots or deltas. Who wrote your memory and the counts sit under one collapsed, remembered *Statistics* disclosure. A row opens its source as the detail column; a saved source's column is everything saved from it, newest first, each row the site's mark, the title, the day and the person's why. Sources clicked again in the rail returns to this root.

**Sleep. Fixes P3, P4.** A room-over-list page (§5.2, 2026-10-16). The study room stays — the art, the worm, one sentence, and Consolidate as the page's only `PrimaryActionButton` — out of its card, drawn at a whole 5/4/3 pt per cell by the column's width, with no title above it: the eyebrow reads "Sleep · 42 waiting · last read 2 h ago".
- **The lists (2026-10-16):** Waiting · Saved · Videos · Past reads, one tab row of text tabs with counts (DR-45), sticky under the titlebar once the room scrolls away. A count of zero hides its tab; the page opens on Waiting while anything waits, else Past reads.
- **Saved (the Feed until 2026-10-16).** Rows are 56 pt: mark, title and source line, with a thumbnail only for media. Its sort (Relevance · Recent, one always on) and kind filter sit in one View menu, never a second tab row (DR-38). A row opens the saved item as the detail column, where a video plays (`MediaPreview`); the Reader is the third column. The one-shot import is the tab row's `+` (⌘N).
- **Videos** is the Feed's Videos list and its watch run, drawn only while a video is saved; it is the video queue's one place.
- **New (owner, 2026-09-23): a quick engine/model menu** beside Consolidate. It is a `NeutralButton` that reads the current engine ("Claude plan · Sonnet ▾") and writes the same `PUT /sleep/engine` that `EngineChooser` writes. It opens a popover of the five engines with real marks, the chosen engine's model (a menu picker), both previews, and "More in Settings → Engines ›". It shows both the `preview.manual` and `preview.scheduled` lines, so ruling 4 (a scheduled cycle never spends plan quota) stays visible rather than applying silently.
- **Waiting and Past reads** (Details' What's waiting, and its Last cycle · Readout · Past nights, until 2026-10-16) use the list grammar: section labels over rows, no cards, 28 pt between sections. Last cycle's rows are words with a glyph and no fill, the readout is key–value rows, and an episode row carries one glyph. A past read opens in place under its row, with its Models, tokens and cost (ruling 12's one home on the page).
- **At rest (owner, 2026-10-16):** one headline with no empty line held under it (2026-10-17), one row of controls (Consolidate · the engine menu · Options…, one height), one schedule sentence. "Overdue" is a word in the lead's colour, never `warning`; the lamp-off fact is the schedule sentence and is said nowhere else; Waiting and Saved hide at zero (Saved stays for an export being waited on).
- **"Rested 0%"** is a sentence ("Fully rested — nothing is waiting.", "Rested n% — …") instead of a row of empty boxes, with the breakdown on hover.

**Settings panel. Fixes P1, P5.** Built per DR-33. Each pane is one group of rows on `bgFocus` (DR-37), and native controls follow the system accent. Integrations shows real marks: its chat-bubble fallback for Claude Code and Cursor is a bug (DR-52). Manage and Connect open as sheets, never popovers.

**Entity card. Fixes P3, P4, P5.** A detail column, opened from Graph, Clusters or ⌘K.
- **Header:** the name (`displayFont(size: 22)`), the type as a `Tag` with a dot, and a one-line summary.
- **A person (F-12, 2026-09-24):** mock C's top — an 88 pt picture, the name at 24, a one-line standfirst, where the picture came from, and a facts strip (Works at · Role · Known since · Last mentioned · Conversations · Contacts, each only with data). Every other type keeps the header above with a 40 pt picture.
- **Body:** one scroll replaces the four underline tabs. It shows, in order:
  - beliefs as rows (the claim in 14 regular, its evidence chip, its age);
  - "Changed recently";
  - "Where this came from" (DR-54), which opens the Reader column;
  - "Look it up at";
  - History, with commit subjects behind a disclosure.
- **Chips:** at most two per claim (speaker and age); the age steps aside when the chip already names its day (2026-10-17). Everything else goes in `.help`.
- **Nothing to show:** a page with nothing readable says so in words and never shows raw YAML.

**Projects (v2, 2026-10-19 — supersedes the G141 block; §9; ⌘8). Fixes P3, P4.** A list page in the same columns: projects list → project → Reader. The eyebrow reads "Projects · 6 current" (or "· 481 past"), the tabs Current · Past with counts. Current is the projects in motion as two-line rows — name, one-liner, and where it stands as one signal at the end — with a parent's parts folded under a chevron, then one folded *Fading* disclosure. Past is searchable, newest heard first under year labels, 50 rows at a time. A project opens on its name and one-liner, then *Where it stands* · *Last* · *Next*, each once; then the 112 pt band — a `progressFill` track from the first moment to a "You, today" marker, done happenings and milestones as neutral dots and diamonds, planned dates hollow on the unfilled track, ongoing threads as spans to Today, every mark clickable (§3.8, ruling of 2026-09-23 in §9) — then Log progress and the folded sections (In progress, What happened, Plan, Backlog, Around this project). What happened's sentences carry their provenance: each noun links to its entity, the evidence chip opens the Reader, dates are relative at read time (DR-58). Projects clicked again in the rail returns to this root.

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

- **2026-10-02: Integration review keeps state reactions fully visible and the weather disclosure accurate (G176; ruling 18; DR-13, DR-50, DR-61, DR-65, DR-66).** Room appearance layers keep their 0.4 s crossfade; the worm sits outside that identity and fades only on its lighting sheet set. A mood edge, overlay change or day-time lamp toggle swaps worm frames immediately when the lighting set stays the same. Re-review follow-up: an active transition or beat also makes a lighting-sheet swap immediate, including error → sleeping's day/dusk rainy/dark → sunny/day edge in Sleep-driven scenery or Local weather fallback. Room layers still crossfade; passive lighting swaps still fade. Clock ticks align with whole seconds, or minutes with Reduce Motion. Weather suppresses the viewer's language/region, uses fixed minimal headers and discloses the network address; no memory content leaves the Mac. Real-sheet tests cover every night mark and fly shade occlusion; isolated Settings renders distinguish source modes. Saved parts remain authoritative for partial/repeated builds; authoring provenance is static family data, independent of installed authoring tools.
