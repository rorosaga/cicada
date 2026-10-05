# Audit batch 2 — graph energy (A07, A08, A09)

Source: [`docs/goals/audit-2026-10-02/README.md`](../goals/audit-2026-10-02/README.md), revalidated on `dev` `efd5386e`
(2026-10-05). `repros/graph-loops.cjs` still shows a pending node rendering 120 of 120 frames at alpha 0 with one more
queued, and an interrupted drag holding alpha ≈ 0.1 after 400 ticks. Branch `fix/audit-graph-energy`.

## Global constraints

- **G109 binds:** d3-force stays, every custom force multiplies by alpha, and the release path never bumps alpha.
- Preserve the zoom, node positions, a normal throw's coast, capture, SSE and the menu-bar state. Never stop capture or
  SSE to make the app look idle.
- No new SwiftUI duration (DR-61): the pulse cadence is graph.js's own canvas clock, as `pulsePhase` already was.
  Precedent: the 2026-09-24 ruling R-HO7, "a living painting rests when nobody can see it", ≤ 30 fps.

## Rulings

- **R1 (A07, bridge).** `GraphView(isActive:)` is true when the Graph tab is selected *and* `WindowVisibilityReader`
  reports the window visible (occluded, minimized and hidden all read false). It is pushed as `setGraphActive(bool)`
  once per change and only after `graphReady`, latched on the coordinator like the theme. Covering sheets inside the
  window are not tracked (the in-app Settings panel is an overlay, and the occlusion API does not see it); disclosed.
- **R2 (A07, suspend).** Going inactive cancels the queued animation frame and the pulse timer, runs
  `cancelInteraction`, and stops the d3 timer. `holdIfInactive()` runs after every `simulation.restart()`
  (`startSimulation`, `setFocus`, `clearFocus`), so a data push while hidden never ticks in the background.
  `simSuspended` records whether the simulation was still above `alphaMin`.
- **R3 (A07, resume).** Becoming active again restarts a suspended simulation at its current alpha (`restart()`
  alone, with no `alpha()` call) and schedules one redraw. Positions and `transform` are never touched.
- **R4 (A07, visible pulse).** With physics settled, the loop continues only when a pending node's ring (radius
  + 16 px) intersects the canvas. Pulse-only frames come from a `setTimeout` at 1000/30 ms, not from back-to-back
  rAF. `pulsePhase = performance.now() / 1000 × 0.96`, which keeps the old ~1 s period (0.016 per 60 fps frame).
  While physics is active, rAF stays at full rate as before.
- **R5 (A09).** One `cancelInteraction()` handles window blur, a mousemove with `buttons === 0` while dragging,
  `pointercancel`/`lostpointercapture`, and going inactive. It unpins the node, zeroes its velocity and the
  drag-velocity estimate, sets `alphaTarget(0)` **without** `restart()` (no reheat), and clears `pressStart` and
  the dragging class. A normal held drag (buttons = 1) is untouched.
- **R6 (A08).** `Coordinator.webView` becomes `weak`. `GraphView.makeWebView(coordinator:)` and
  `GraphView.teardown(_:coordinator:)` are static so they can be tested. `dismantleNSView` calls teardown:
  `setGraphActive(false)`, then remove the `cicada` handler, `stopLoading()`, and drop the reference.

## Files

`Resources/graph/graph.js`, `Views/Graph/GraphView.swift`, `Views/Graph/GraphPage.swift`, `Views/Graph/GraphBridge.swift`,
`Tests/graph/graph-lifecycle.test.js` (new), `Tests/CicadaAppTests/GraphViewLifecycleTests.swift` (new),
`docs/architecture/app.md`, the G109 row.

## Tests (first)

- **JS (real graph.js + d3, hand-drained rAF and timer queues):**
  - settle: one frame, nothing queued;
  - an on-screen pulse runs on a ≥ 32 ms timer, not rAF;
  - the phase follows elapsed time;
  - an off-screen pending node stops after one frame;
  - inactive: no frames, no timers, and an inactive data push stays suspended;
  - resume: same alpha, positions and transform, with one redraw;
  - resuming a settled graph does not restart it;
  - blur, a buttonless move, going inactive and a pointer cancel each end a drag with `alphaTarget` 0 and no
    alpha bump, while a held move keeps dragging;
  - an inactive graph's real d3 timer does not tick over 120 ms.
- **Swift (real `WKWebView`):**
  - the view and the coordinator deallocate after teardown;
  - dropping the owners alone releases the view (this fails with a strong `webView`);
  - three recreations leave no survivors;
  - the bridge literal;
  - the weak reference.

## Verification

`node --test app/CicadaApp/Tests/graph/*.test.js`; `cd app/CicadaApp && swift test`. Live CPU is **not measured**:
the brief forbids launching or driving the app, and an on-screen before/after trace needs the owner's machine and word
(VALIDATION.md's matrix).
