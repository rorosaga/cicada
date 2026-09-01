# G83 / G84 fix report

Worktree: `.worktrees/app-polish`, branch `feat/app-polish`, off dev at `2c00c55`.

## Commits

- `96d221b` — fix(app): shared plain-button style fixes multi-click hit area + adds pressed feedback (G83)
- `049592c` — fix(app): graph cold-paint filter drift + drag deceleration (G84a, G84b)

## G83 — button hit area + pressed feedback

**Root cause confirmed** at `TopicsView.swift:707-721` before editing: the back
button's label was a bare `HStack { Image; Text }` under `.buttonStyle(.plain)`
with only `.foregroundStyle`/`.padding`, so the tap target was the union of the
rendered glyphs, not the `.glassCard` pill drawn behind it.

**Fix:** added `CicadaPlainButtonStyle` (a `ButtonStyle`) in
`app/CicadaApp/Sources/CicadaApp/Theme/CicadaTheme.swift`, exposed as
`.cicadaPlain`. Its `makeBody` wraps `configuration.label` in
`.contentShape(Rectangle())` (fixes the hit area for every adopter from one
definition) and applies a `scaleEffect`/`opacity` dip keyed on
`configuration.isPressed` with a 0.12s eased animation (the "snappy" feedback
Rodrigo asked for).

**Scope:** every `.buttonStyle(.plain)` call site in `Sources/CicadaApp` was
converted to `.buttonStyle(.cicadaPlain)` — **87 real call sites across 31
files** (the backlog's "37 of 87" was a scoping estimate; the actual current
count in the tree was 87, all now on the shared style — including the 7 that
already had a manual `.contentShape` and the rest that had neither). [Corrected
2026-09-01: a prior version of this report said "89 occurrences across 30
files" — that counted 2 doc-comment mentions of the string `.buttonStyle(.plain)`
inside `Theme/CicadaTheme.swift`'s own comments (lines 395, 428 at the time) as
call sites; they aren't. `grep -c "buttonStyle(\.cicadaPlain)"` over `Sources`
returns 89 for the same reason post-conversion. 0 `.buttonStyle(.plain)` call
sites remain either way — the conversion itself was always complete, only the
report's count was off.] No test target referenced `.buttonStyle(.plain)`, so
this was a safe blanket conversion. Verified `TopicsView.swift:718` (`Button
{ onBack() } label: { ... }.buttonStyle(.cicadaGlass(...))`, see the review
follow-up below) is on the shared style.

No dedicated unit test for the style itself — `.contentShape`/pressed-state
visuals aren't meaningfully testable without a live view; existing 389-test
suite covers regressions elsewhere and stayed green.

## G84a — cold first paint hides zero-degree nodes

**Root cause confirmed:** `Coordinator.pushGraphData()`
(`GraphView.swift:164-171` pre-edit) pushed `updateGraph` but never followed
with `applyFilters`, unlike `updateNSView`'s push site (`:74-79`, which does).
`graph.js`'s own default was `filters.minDegree = 1` (`:154` pre-edit, dropping
every zero-degree node in `rebuildVisible()` at `:702`), while Swift's default
is `GraphFilter.minDegree = 0` (`GraphFilter.swift:11`, unchanged).

**Fix (two parts, both applied):**
1. `GraphView.swift`, `pushGraphData()`: after the `updateGraph` completion
   handler, re-assert `applyFilters(filterJSON)`, mirroring `:74-79` exactly.
2. `graph.js`: changed the built-in `filters.minDegree` default from `1` to
   `0` so the two sides can't drift apart again even in the brief window
   before Swift's push lands.

**Tests added** (both pass):
- `Tests/CicadaAppTests/GraphFilterTests.swift` — pins
  `GraphFilter().minDegree == 0` and that `jsPayload["minDegree"] == 0`.
- `Tests/graph/graph-mindegree-default.test.js` — a plain node script (same
  vm-context harness as the existing `graph-delta.test.js`/`graph-logo.test.js`,
  **not** part of `swift test`) asserting graph.js's own `filters.minDegree`
  defaults to `0`, and that a zero-degree node survives `rebuildVisible()` on
  a cold `updateGraph` push before any `applyFilters` call.

## G84b — drag stops instantly instead of decelerating

**Root cause confirmed:** `onMouseUp` correctly nulled `fx/fy` and zeroed
`alphaTarget` — not a stuck pin. While `fx/fy` are set, d3 zeroes the node's
own `vx/vy` every tick (it's pinned, not simulated), so at release velocity
was exactly 0 by construction. Pointer velocity was never sampled in
`onMouseMove`. Compounded by `velocityDecay(0.55)` (`:770` pre-edit; d3's
default is 0.4).

**Fix:**
- `onMouseMove`: while dragging past the click threshold, sample the
  pointer's world-space delta each move, convert to a per-tick velocity
  estimate (`SIM_TICK_MS = 1000/60`), and EMA-smooth it into module-level
  `dragVX`/`dragVY` (smoothing weight `0.35`).
- `onMouseDown`: reset `dragVX`/`dragVY`/`lastDragSample` for each new drag.
- `onMouseUp`: seed `draggingNode.vx = dragVX; draggingNode.vy = dragVY`
  **before** nulling `fx/fy` (order matters — clearing the pin first hands
  the node back to the sim already at rest). Then
  `simulation.alphaTarget(0).alpha(Math.max(simulation.alpha(), 0.2)).restart()`
  so there is alpha left for the seeded velocity to actually animate a
  visible settle, instead of just `alphaTarget(0)`.
- `velocityDecay` relaxed from `0.55` to **`0.45`** — partway toward d3's
  `0.4` default, deliberately not all the way: an existing code comment says
  `0.4` (the plain default) is exactly what caused the simulation to "bounce
  indefinitely" at ~1500 nodes, so going all the way back risks reintroducing
  that instability at the graph's full ~1800-2000 node scale. `0.45` keeps
  most of that stability margin while roughly doubling the visible coast
  duration of a thrown node. **This is a judgment call, not something I could
  verify by running the app at full scale — see "what to check" below.**
- **Latent bug also fixed:** `mouseup` was bound only on the `canvas`
  (`:1299-1302` pre-edit), so releasing the button outside the canvas bounds
  never unpinned the node. Added a `window`-level `mouseup` listener bound to
  the same `onMouseUp` handler as a catch-all. Safe alongside the existing
  canvas listener: `onMouseUp` never reads its `event` argument and is a
  no-op once `draggingNode` is already `null`, so an ordinary in-canvas
  release just runs the handler twice (second call no-ops).

**Not unit-testable here** (physics/timing against a real DOM + d3 force
tick loop). All three `Tests/graph/*.test.js` node scripts
(`graph-delta`, `graph-logo`, and the new `graph-mindegree-default`) still
pass, confirming the file loads and its non-physics data paths are
unaffected, but none of them exercise mouse drag.

### What a human should verify by driving the app

1. **Cold paint (G84a):** relaunch the app, go straight to the Graph tab
   before touching any filter control. Isolated/zero-degree entities (e.g. a
   freshly-created entity with no relationships) should be visible
   immediately, not only after nudging a filter slider.
2. **Throw feel (G84b):** drag a node with a deliberate flick and release
   while still moving. The node should visibly coast/decelerate for a
   noticeable beat (not stop dead), and the surrounding sim should settle
   without odd resurgent bouncing.
3. **Slow drag / plain click:** drag a node slowly and release with ~0
   velocity — it should stay essentially where dropped (no phantom throw).
   A plain click (no movement past the threshold) should still open the
   detail card as before, with the node not moving.
4. **Release outside the canvas:** start dragging a node, move the cursor
   past the canvas edge into the surrounding chrome, and release the mouse
   button there. The node must unpin (not stay stuck to the cursor position)
   and the drag state must fully reset (a subsequent click elsewhere should
   behave normally, not think a drag is still in progress).
5. **Full-graph stability at scale:** with the graph at its real size
   (~1800-2000 nodes), watch for persistent, non-decaying jitter/bouncing
   across the whole layout (not just around a just-thrown node) after
   several drags. If that appears, `velocityDecay` should move back toward
   `0.55` in `graph.js` (`startSimulation`, `.velocityDecay(0.45)`) rather
   than being lowered further.
6. **Focus mode:** with a 2-hop focus active (double-click a node), drag and
   release a *context* node that's pinned by the focus (`keepPinned`) —
   confirm it stays pinned exactly as before (this path is unchanged; the
   new velocity-seed code only runs on the `!keepPinned` branch).

## Gate

- `swift build`: clean.
- `swift test`: **389/389 passed**, 0 failures (387 baseline + 2 new
  `GraphFilterTests` cases). Verified on the final committed state (built
  and re-ran the full suite after both commits landed, not just before
  committing).
- `node app/CicadaApp/Tests/graph/graph-delta.test.js`,
  `graph-logo.test.js`, and the new `graph-mindegree-default.test.js`: all
  pass (not part of `swift test`; run manually).
- `node --check` on `graph.js`: syntax OK.

## Review follow-up (2026-09-01)

Review came back Spec ✅ / Approved with 3 Low findings (`review-g83-g84.md`). Two
were worth closing because they undercut the "buttons should feel snappy" ask
directly; the third was the report arithmetic fixed above.

**Finding 2 — double scale-effect nullified press feedback on `InboxActionButton`**
(`Views/Inbox/InboxCardView.swift`, the Dismiss/Keep Active/Archive/Answer/Merge
buttons — the highest-frequency buttons in the app). The label already carried
`.scaleEffect(isHovered && !disabled ? 1.03 : 1.0)`; `CicadaPlainButtonStyle`
wraps that same label in its own `.scaleEffect(isPressed ? 0.97 : 1.0)`. On the
ordinary hover-then-click path the two multiplied to ≈0.999 — a press was
essentially invisible. **Resolved by dropping the pre-existing hover-scale line
from the label** and letting the shared style own the transform exclusively —
the hover cue stays as the existing background-tint change
(`color.opacity(isHovered ? 0.2 : 0.12)`), which doesn't compete with a
scale/opacity transform. This was the simpler and more robust of the review's
two suggested options (the alternative — teaching the shared style to detect
and skip its own scale when a label happens to declare one — would need the
style to reach into arbitrary per-site `@State`, which `ButtonStyle` has no
clean way to do).

**Finding 3 — `.glassCard()`-wrapped buttons got only partial feedback.**
`.glassCard()` chained AFTER `.buttonStyle(.cicadaPlain)` puts the card's
background/border/shadow OUTSIDE the style's `scaleEffect`/`opacity` (SwiftUI:
modifiers chained onto the label closure become part of `configuration.label`
and DO get the style's transform; modifiers chained onto the `Button` itself,
after `.buttonStyle()`, wrap the already-styled output and DON'T) — so on press
only the icon/text dipped while the visible pill stayed static. Added a second
style, `CicadaGlassButtonStyle` (`.cicadaGlass` / `.cicadaGlass(cornerRadius:)`,
same file), whose `makeBody` applies `.modifier(GlassCard(cornerRadius:))` (the
existing recipe, not a duplicated copy) to compose the card INSIDE `makeBody`,
then applies the press transform to the whole result — background included.

Audited every `.glassCard(` call site in the tree (not just the review's named
lines) to separate genuine per-button pairs (this button's OWN glassCard,
chained directly after ITS `.buttonStyle(.cicadaPlain)`) from a container-level
`.glassCard()` that merely happens to wrap several buttons in one shared card
(e.g. `ObserverFilterBar`'s segmented HStack, `ContextLegend`'s panel,
`ClaimChip`'s footer, every search-bar clear-button pair) — the latter pattern
was never broken and is untouched. Found and converted exactly **8** genuine
sites (the review said "~10" and named 8 by line plus a bare mention of
`ConnectView.swift`; independently verified `ConnectView.swift` has no
`.buttonStyle(.cicadaPlain)`+`.glassCard()` pair on the same button — its two
buttons use in-label `Capsule()` backgrounds, and its four `.glassCard()` calls
all decorate plain container cards):
- `Views/Common/TopBarControls.swift` — Sleep, Upload, Help buttons
- `ContentView.swift` — `FilterButton`, `AskButton`
- `Views/Topics/TopicsView.swift` — the type-filter button, the label-filter
  button, and **the "< Clusters" back button itself** (G83's named button —
  now gets full-pill press feedback, not just the label)

One genuine per-button site, `EntityDetailCard.swift:1222-1225` (a contested-
belief row), already had `.glassCard()` chained INSIDE the label closure
(before `.buttonStyle(.cicadaPlain)`, not after) — that ordering already
composes correctly, so it was left alone.

**Gate re-run:** `swift build` clean, `swift test` 389/389 (unchanged — no new
test surface for this pass; SwiftUI `ButtonStyle` composition isn't testable
without a live view, same reasoning as G83's original pass).

## Concerns / open items

- The `velocityDecay` value (`0.45`) is a reasoned compromise, not a
  measured one — I could not drive the live app to confirm it neither
  under- nor over-shoots at full graph scale. Flagged above as item 5 to
  check by hand.
- G83's conversion was a blanket replace of all 89 `.buttonStyle(.plain)`
  sites rather than only the 37 the backlog scoped as "affected" (missing
  `.contentShape`/background) — done deliberately since (a) the shared style
  is a strict superset of `.plain` (adds `.contentShape` + pressed feedback,
  never removes anything), (b) the user's ask ("buttons should... feel
  snappy") was broader than just the broken-hit-area sites, and (c) auditing
  each of 89 call sites individually for "does it already have a background"
  would have been slower and more error-prone than the safe superset move.
  Flagging in case a narrower, more conservative scope was actually wanted.
- G84's other two causes ((c) legend/color axis mismatch, (d) All/Cicada/
  You/External observer-filter meaninglessness) were left untouched per the
  task's explicit scope — they need design decisions, not just a code fix.
- `api/.venv` shows as an untracked directory in `git status` throughout this
  session; it predates this task, is unrelated to G83/G84, and was left
  alone (not added, not touched).
