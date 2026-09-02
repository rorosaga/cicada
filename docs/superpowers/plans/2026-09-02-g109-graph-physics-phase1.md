# G109 Graph Physics — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a thrown node visibly decelerate and stop zero-degree nodes from exploding into a ring around the graph — by fixing three local bugs in how `graph.js` drives d3-force, with every earned behaviour of the current renderer preserved verbatim, and with a committed headless bench so the before/after numbers are reproducible by anyone.

**Architecture:** Four commits on one branch. (1) A Node harness that loads the REAL `graph.js` under the REAL bundled d3 into a `vm` context and drives its actual `startSimulation` and drag handlers on synthetic graphs — the "before" baseline. (2) The two one-line-class physics bugs: `hubGravityForce` ignores `alpha` (a permanent 5 %/tick energy source that is the true origin of the "1,500 nodes bounce forever" folklore), and the release path reheats the whole graph (`alpha(max(alpha, 0.2))`). (3) The retune those bugs made impossible (`velocityDecay` 0.45 → 0.2) plus per-isolate containment (a phyllotaxis slot per zero-degree node, pulled by the existing `forceX/forceY`, weaker isolate charge, a speed clamp). (4) Docs: the ruling into CLAUDE.md, the G109 row, and the TODO handoff.

**Tech Stack:** `graph.js` (vanilla ES2020, runs in a `WKWebView`, d3 7.9.0 bundled as `d3.v7.min.js`, d3-force 3.0.0 inside it); Node 25 for the headless bench (`vm` + `require` of the bundled UMD d3, no npm); SwiftPM tests untouched but re-run.

**Spec:** the G109 research decision memo (folded into the G109 row; sections 1, 3 "Phase 1", "How every earned behaviour is preserved", 4, 5, and "## Critic", whose corrected values win), and `docs/goals/memory-evolution.md` row **G109**. Where the memo and `graph.js` (or the memo and its own critic, or the memo and a measurement made while writing this plan) disagree, the **Rulings** below decide.

## Global Constraints

- Work ONLY inside the git worktree `/Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109` (branch `feat/graph-physics`, based on `dev` @ `b690b66`). Never edit files under `/Users/rorosaga/Documents/roros_lab/cicada` outside that path.
- **NEVER read** `/Users/rorosaga/Documents/roros_lab/cicada/memory` or `~/.cicada` (real people). **NEVER open or quote** the research run's live-graph export (`eg.json`, never committed) — it holds personal data. Synthetic graphs only; the bench and test below carry no names, only `h0`/`c12`/`i3` ids.
- Every shell command: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109 && <cmd>` with the ABSOLUTE path (`zoxide` hijacks a relative `cd`; ignore its stderr "configuration issue" warning). No `grep --include=*.ext`.
- The file under change is `/Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109/app/CicadaApp/Sources/CicadaApp/Resources/graph/graph.js` (1,661 lines at `b690b66`; loaded by `index.html` next to it after `d3.v7.min.js`). It runs inside a `WKWebView`; Swift pushes data via `evaluateJavaScript` and receives events through `window.webkit.messageHandlers.cicada`. **Phase 1 is `graph.js` ONLY:** no Swift changes, no new dependency, no `index.html` change (this plan lists none).
- Node is available for the headless bench: `node` (v25.9.0 verified) `require`s the bundled `d3.v7.min.js` directly (UMD exports under CommonJS — the research benches did the same). No `npm install`, no `package.json`.
- Swift tests must stay green and unchanged: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109/app/CicadaApp && swift test 2>&1 | tail -20` (`GraphDiffTests`/`GraphPushTests` exercise the JS bridge contract from the Swift side; they must not change).
- The four existing JS tests must stay green and unchanged: `node app/CicadaApp/Tests/graph/graph-delta.test.js`, `graph-drag-velocity.test.js`, `graph-logo.test.js`, `graph-mindegree-default.test.js` (they mock d3 with a chainable no-op Proxy; every new custom force is a plain function so the Proxy tolerates it — verified against the patched source while writing this plan).
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`, `.claude/settings.json`, `api/.venv`, bench scratch under the scratchpad, or `*-report.md`. Do not push. Do not create branches or worktrees. Do not dispatch subagents. Ignore Devin/PR comments.
- Every earned behaviour in the memo's "How every earned behaviour is preserved" table is a hard constraint, preserved verbatim: delta updates keyed on `content_hash` with positions preserved (`updateGraphDelta` :501-618), `prevPositions` carry (:199, :462-499), new-node seeding (`seedPositionFor` :701-719 — **untouched**, see R12), hub index + ring R=400 (:647-699), pinning/drag + throw seeding (:1391-1527; only :1404 and :1517 change), cluster hulls / hub ring / labels / pulse / observer dim (draw, :978-1329, reads x/y only), selection + click-vs-drag + double-click (:1360-1470, :1529+), hub gravity's intent (members orbit their hub; nominal 0.05 kept), focus/ego pinning (:873-935), filter reheat only on set-affecting axes (:1597-1637), `simulation.find` pick (:1365-1374), zoom-to-fit (`fitGraph`/`transformForNodes` :420-451), and the Swift message contract (no new entry points in either direction).
- Line numbers cited as `graph.js:N` are from `b690b66` and were re-verified for this plan. Task 3 inserts ~100 lines (the isolate block, comment included) above `startSimulation`, so from that commit on everything at or after `:792` shifts by that amount — read the code at the cited anchor before editing; anchors are given as unique code strings as well.

## Rulings (binding — do not re-derive)

- **R1 — Engine ruling.** Keep d3-force 3.0.0 (inside the bundled d3 7.9.0) and fix `graph.js`; do not change engine or renderer. All three judges picked it (8.33/10; runner-up sigma.js + graphology + ForceAtlas2 at 5.64, which has no velocity model, needs esbuild, and costs 12–20 days of port). **Flip trigger:** after phases 1 and 2 land, an in-app measurement showing p95 frame time (tick + draw) above 16.7 ms on the live bank with the two scale levers already pulled (tick every other frame; isolates excluded from the sim — phase 3), **or** the graph growing well past ~10k nodes, **or** a product decision to move decorations off the canvas anyway. At that point a WebGL renderer stage (sigma or Pixi over the same d3-force worker) is justified, and nothing in phases 1–3 has to be undone.
- **R2 — No alpha bump on release, ever.** The release path becomes `simulation.alphaTarget(0).restart()`. The dragged node keeps the velocity `seededDragVelocity` gave it; velocity integration `x += vx *= (1 - velocityDecay)` is unconditional of alpha (documented, d3 `simulation.tick`), so a coast needs only low per-tick damping and a running timer — not a hot graph. Measured here through graph.js's own handlers: the bump made a flicked node reverse in **0 ticks** (the link springs, at alpha 0.2, cancel a 26 wu/tick seed in one tick) and moved every other node ~1,000 wu; without it the other nodes move 1.4 / 9.7 / 29 wu (small / medium / dense synthetic).
- **R3 — Alpha-scale every custom force.** A force registered on the simulation multiplies its impulse by the `alpha` d3 passes it, so the summed energy decays with alpha. The one exception is a force that can only *remove* energy (`clampSpeed`, which rescales a velocity down to `VMAX_WU_PER_TICK`) — it is a guard, not a force, and cannot create the plateau. The guard for this rule is `graph-physics.test.js`'s "KE/node at tick 400 < 1e-1" check: a plateau there is the regression signature.
- **R4 — `alphaMin` 0.001 lands in Task 2, not Task 3.** The memo lists `alphaMin` under "momentum" beside `velocityDecay`, and the task split given to this plan puts both in Task 3. But R2's release change is broken without it: with `alphaMin` 0.05, `alphaTarget(0).restart()` after a short drag leaves alpha ≈ 0.026 < 0.05, so d3's timer stops after **one** tick and the coasting node freezes. Measured with the Task-2 patch (hub gravity scaled, `alphaMin` 0.001, `velocityDecay` still 0.45): a flick from rest coasts 6 ticks / 34 wu — exactly the vd-0.45 arithmetic, i.e. the release path is now honest and Task 3 only has to lengthen it.
- **R5 — `isIsolate(d)` is `!nodeIsHub(d) && !memberToHub.has(d.id) && !neighborsById.has(d.id)`.** The memo's "visible degree 0" has no source in the file (critic gap 2): `_localDegree` counts ALL links, and the contexts filter drops edges at `:753`. `neighborsById` is built from `visibleLinks` (`:760-770`), so it is the cheap truth. `memberToHub` excludes hub members and facets whose parent is on the graph (critic gap 3: they are pulled by `hubGravityForce` and must not get a second pull). Hubs are excluded because they anchor to the ring at 0.08. One pre-existing gap stays as it is: a member whose hub is filtered OUT of the visible set (e.g. the `hub` type deselected) is still in `memberToHub` (built from all `nodes`, `:663-666`), so `hubGravity` skips it (`byId.get(hid)` is undefined) and `anchorStrength` returns 0 — it has no pull today and gets none from this plan; it is not an isolate by this definition. Narrow, out of scope, noted so nobody "fixes" it by dropping the `memberToHub` clause. **Orphan facets (parent not on the graph) are isolates** — they are visible-degree-0 non-hub non-members, and today they fall to a 0.04 pull toward `typeClusterPositions[facet.type]` (undefined for a facet's type → `(0,0)`), the unbounded case the d3-force-fixed report flagged; a slot is strictly better than that.
- **R6 — Slots are a per-type free-list, assigned at the top of `startSimulation`.** "Sort isolates by id" (memo step 4) shuffles every slot after any insert that sorts earlier (critic gap 4). Instead: `isolateSlots: Map<id, {x, y, type, index}>` persists across calls; an isolate that already holds a slot of its current type keeps it; a new isolate takes the lowest free index of its type; a node that stops being an isolate (gains a visible link, changes type, leaves) releases its index. Assignment runs first thing in `startSimulation`, which every call site (`:495`, `:614`, `:1633`) reaches only after `rebuildNeighborsIndex()` — so the slot pass never reads a stale neighbour index, and the `forceX/forceY` accessors (evaluated once at `initialize`, `x.js:17-23`) see the final answer.
- **R7 — Disc geometry and strengths are measured, not copied.** Constants: `ISOLATE_ANCHOR_SCALE = 1.0` (disc centred on the type anchor), `ISOLATE_SLOT_SPACING = 20` (critic gap 5c: c ≈ 20 is the collision-free spacing for two high-confidence isolates, `2 × (4 + 8 + 6) = 36` wu), `ISOLATE_ANCHOR_STRENGTH = 0.3`, `ISOLATE_CHARGE = -30`. The memo's 0.10 pull was measured insufficient on this plan's synthetics: with the rest of the Task-3 patch in place (charge −30, clamp, `velocityDecay` 0.2) and only the strength at 0.10, isolate-max/core-p90 is 1.80 / 1.58 / 1.55 and isolate-median/core-p90 1.58 / 1.35 / 1.33 (small / medium / dense) — the ring is still there; a sweep on the 1500-node synthetic gave isolate-max/core-p90 ratios of 1.42 (0.2), **1.31 (0.3)**, 1.19 (0.5) — and 0.5 costs +30 % post-release displacement while pushing isolates inside the type cluster. Scaling the anchor outward (1.3–1.8×) does **not** move the outcome (ratio 1.57–1.75 at 0.10 regardless of scale): the isolates' resting radius is set by the core's outward push, which per-node charge cannot reduce (critic gap 6 — `strength()` sets what a body *exerts*), so scale 1.0 keeps `fitGraph`'s framing unchanged. **The memo's two exit criteria "isolate max ≤ 1.2× core p90" and "zero isolates beyond 700 wu of the core centroid" are replaced** (critic gap 5b showed they contradict the memo's own geometry) by the measured, meaningful ones the test asserts: isolate max ≤ 1.1× the farthest connected node (no halo *around* the graph), isolate median ≤ 1.35× core p90, isolate max ≤ 1.35× core p90 on the 1500-node synthetics, and core median within ±10 % of its pre-containment value.
- **R8 — Reheat cost is accepted, not hidden.** With `alphaMin` 0.001 every existing reheat runs longer: cold 59 → 135 ticks (measured), a 0.3 reheat 35 → 112 (`⌈ln(0.001/0.3)/ln 0.95⌉`), `setFocus` 0.4 → 117, `clearFocus` 0.2 → 104 (critic gap 7). The redraw loop (`:959-976`) draws through all of them — ~2 s of full-frame work per filter change at ~7 ms/tick + draw. Lowering the reheats to 0.2 buys only ~9 ticks (log arithmetic), so the reheat values stay. The real fix is phase 2's owned loop with a *physical* settle criterion (max speed < 0.3 wu/tick for 10 frames), which also removes the other artefact measured here: the cold layout freezes at tick 135 while still relaxing (`keAtStop` 0.03–0.76), so the next reheat resumes that motion (this is most of `otherDisp60` on the dense synthetic).
- **R9 — Drag hold `alphaTarget(0.1)`.** Kept from the memo (today 0.3; d3's canonical example uses 0.3). Measured lever, not taken: 0.05 lowers the medium synthetic's post-release displacement from 8.9 to 7.6 wu and hold KE 1.5 → 0.4 — a phase-2 tuning knob, read from `__cicadaPerf.report()`.
- **R10 — `velocityDecay` 0.2, `alphaDecay` 0.05 unchanged, `distanceMax` 700 unchanged.** All from the memo; 0.15 (24 ticks / 159 wu collide-off) is a phase-2 lever, `distanceMax` 350 was measured to worsen the isolate max (2,032 wu). Measured with collide ON through graph.js (the combination the critic noted had never been benched): KE/node at tick 400 4.5e-16 / 3.9e-6 / 3.5e-5, fastest node 0 / 0.01 / 0.02 wu/tick — no rebound at 0.2 once hub gravity is alpha-scaled.
- **R11 — The bench drives `graph.js` itself; no extraction refactor.** Verified while writing this plan: `graph.js` loads into a `vm` context with the real d3 and only `requestAnimationFrame` (no-op), `performance.now` (fake clock) and `Math.random` (seeded) stubbed; `updateGraph` builds the real simulation; `simulation.stop()` right after any entry point that calls `.restart()` prevents d3's `setTimeout` timer from ticking concurrently; the real `onMouseDown/Move/Up` handlers produce a real throw with the fake clock advanced 16.7 ms per move. So `buildSimulation(nodes, links, opts)` is **not** needed, and the bench guards the real `startSimulation` (the only way to catch a future unscaled force — critic gap 10a). Location: `app/CicadaApp/Tests/graph/` — outside `Resources/` (which `Package.swift` copies into the bundle wholesale via `.copy("Resources")`) and outside every SwiftPM target (`Tests/CicadaAppTests` is the only test target), next to the four existing node scripts that already live there.
- **R12 — `seedPositionFor` stays untouched (L3).** Critic gap 14 notes a NEW isolate arriving via a delta is seeded at its type anchor ±30 and then pulled to its slot — a short visible transit inside its own type's disc (scale 1.0 makes it short). Disclosed, not fixed; phase 3 seeds isolates at their slot.
- **R13 — Where the memo and `graph.js` disagree.** (a) `graph.js:1368` says `simulation.find` "uses a quadtree"; d3-force 3.0.0's `find` is a linear scan (`simulation.js`, `find`) — the comment is wrong but harmless; leave it. (b) The memo's anchors (`:774-790`, `:809-810`, `:1404`, `:1517`, …) all hold at `b690b66` (`git diff --stat 80e737f..HEAD` over the graph files is empty). (c) The memo's `hubGravityForce` rebuilds a `Map` of every visible node per tick (`:778`; the memo and its critic both cite `:776`, which is the `function tick()` line); the alpha-scaled version hoists it into `initialize()` (critic gap 14), since the force now also runs on every drag frame. (d) The memo's phase-1 table puts the isolate pull at 0.10 — superseded by R7's measurement. (e) The memo's exit criterion "other-node displacement on release < 2 wu" was measured with collide off and no hold; through the real handlers the hold itself reheats the graph, so the thresholds are the measured 5 / 15 / 40 wu bounds (vs ~1,000 today). (f) The memo's "glide ≥ 15 ticks / ≥ 80 wu" was measured with collide off; with collide on a flick from rest gives 12–13 ticks / 63–100 wu, so the test asserts ≥ 10 ticks, ≥ 60 wu (≥ 90 wu on the 1500-node synthetics). (g) The memo's test name and path (`app/CicadaApp/Tests/graph/graph-physics.test.js`) are kept; it runs as a plain node script like its siblings, not under `node --test`, because none of the existing four use the runner and `swift test` never sees them.

---

## File map

| File | Responsibility |
|---|---|
| `app/CicadaApp/Sources/CicadaApp/Resources/graph/graph.js` | the only shipped change: `hubGravityForce`, `startSimulation` constants and force list, isolate slot block, `xAnchor`/`yAnchor`/`anchorStrength`, `onMouseDown` hold, `onMouseUp` release |
| `app/CicadaApp/Tests/graph/graph-physics-harness.js` (new) | loads real graph.js + real d3 into a vm; synthetic generator; metrics; `runScenario(size)` |
| `app/CicadaApp/Tests/graph/graph-physics.bench.js` (new) | prints the metrics table for the three synthetics; `GRAPH_JS=` env to bench a patched copy |
| `app/CicadaApp/Tests/graph/graph-physics.test.js` (new) | asserts the thresholds; Task 2 block, then Task 3 block appended |
| `CLAUDE.md` | "Why d3-force" line carries the ruling |
| `docs/goals/memory-evolution.md` | G109 row: ruling + "Phase 1 shipped (PR #TBD)" + measured numbers |
| `docs/goals/TODO.md` | G109 In progress → Shipped (phase 1); handoff header refreshed |

---

### Task 1: Headless physics bench — the "before" baseline

**Files:**
- Create: `app/CicadaApp/Tests/graph/graph-physics-harness.js`
- Create: `app/CicadaApp/Tests/graph/graph-physics.bench.js`

**Interfaces:**
- Produces: `graph-physics-harness.js` exporting `{ GRAPH_JS, SIZES, loadGraph(), synthetic(size), runScenario(sizeName), kePerNode(nodes), maxSpeed(nodes), radii(get) }`. `loadGraph()` returns `{ sandbox, clock, get, call }` where `get(expr)` evaluates an expression in the graph.js context (module `let` state such as `simulation`, `visibleNodes`, `neighborsById`, `isolateSlots` is lexical — not a sandbox property — so it is read by expression, exactly as the existing tests do) and `call(fnName, arg)` calls a graph.js entry point with a JSON argument. Task 2 and Task 3 consume `runScenario`, `loadGraph`, `synthetic`.

- [ ] **Step 1: Confirm the bench's home is outside the bundle and outside SwiftPM**

```sh
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109 && cat app/CicadaApp/Package.swift && ls app/CicadaApp/Tests/graph
```
Expected: `resources: [.copy("Resources")]` on the executable target (so nothing under `Resources/` may hold the bench), one `testTarget` named `CicadaAppTests`, and the four existing `graph-*.test.js` scripts in `Tests/graph/`.

- [ ] **Step 2: Create the harness**

Create `app/CicadaApp/Tests/graph/graph-physics-harness.js`:

```js
// G109 physics harness: load the REAL graph.js under the REAL bundled d3 (not the
// chainable Proxy the other Tests/graph/*.test.js use) so graph.js's own
// startSimulation, forces, and drag handlers can be ticked by hand and measured.
//
// Shared by graph-physics.bench.js (prints numbers) and graph-physics.test.js
// (asserts thresholds). Not part of `swift test`; plain node scripts, outside
// every SwiftPM target and outside Resources/ (which Package.swift copies into
// the app bundle wholesale).
//
// What is stubbed and why:
//   - requestAnimationFrame: a no-op. graph.js's tick listener calls
//     scheduleRedraw -> rAF; with a no-op, draw() never runs and the sim never
//     schedules itself. Every tick here is an explicit simulation.tick().
//   - performance.now: a fake clock the throw scenario advances by hand, so the
//     DRAG_STALE_MS gate and the per-move velocity EMA see real 16.7 ms gaps.
//   - Math.random: a seeded LCG, so seedPositionFor's jitter is reproducible
//     and every number the bench prints is stable across runs.
//   - simulation.stop() is called right after every graph.js entry point that
//     calls .restart(): d3.forceSimulation starts its own d3-timer (setTimeout
//     under Node) and would otherwise tick concurrently with the manual loop.
//
// GRAPH_JS=/abs/path/to/graph.js overrides the file under test (used to compare
// a patched copy against the committed one without touching the repo).
"use strict";

const fs = require("fs");
const vm = require("vm");
const path = require("path");

const RESOURCES = path.join(__dirname, "..", "..", "Sources", "CicadaApp", "Resources", "graph");
const GRAPH_JS = process.env.GRAPH_JS || path.join(RESOURCES, "graph.js");
const d3 = require(path.join(RESOURCES, "d3.v7.min.js"));

// ---- deterministic PRNG (LCG) ----
let seed = 42;
function rnd() { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; }
function reseed(s = 42) { seed = s; }

// ---- DOM stubs (same shape as graph-delta.test.js) ----
const noop = () => {};
let canvasStub;
const ctxStub = new Proxy({}, {
    get: (t, k) => {
        if (k === "canvas") return canvasStub;
        if (k === "measureText") return () => ({ width: 10 });
        if (k === "createLinearGradient") return () => ({ addColorStop: noop });
        return typeof k === "string" ? noop : undefined;
    },
    set: () => true,
});
canvasStub = {
    clientWidth: 1200, clientHeight: 800, width: 1200, height: 800,
    style: {}, classList: { add: noop, remove: noop },
    getContext: () => ctxStub, addEventListener: noop,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 1200, height: 800 }),
};

function loadGraph() {
    const clock = { now: 0 };
    const sandbox = {
        console,
        document: { getElementById: () => canvasStub, addEventListener: noop, documentElement: {}, body: {} },
        window: {
            devicePixelRatio: 2, innerWidth: 1200, innerHeight: 800, addEventListener: noop,
            // Swallow the JS->Swift messages (nodeClicked etc.) the click-release path posts.
            webkit: { messageHandlers: { cicada: { postMessage: noop } } },
        },
        requestAnimationFrame: noop, cancelAnimationFrame: noop,
        performance: { now: () => clock.now },
        setTimeout, clearTimeout, Date, JSON, Map, Set, Number, String, Boolean, Array, Object,
        Math: Object.create(Math, { random: { value: rnd } }),
        d3,
    };
    sandbox.globalThis = sandbox;
    sandbox.self = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(GRAPH_JS, "utf8"), sandbox, { filename: "graph.js" });
    vm.runInContext("canvas = document.getElementById('graph'); ctx = canvas.getContext('2d');", sandbox);
    // `let`/`const` module state is lexical, not a sandbox property: read it by expression.
    const get = (expr) => vm.runInContext(expr, sandbox);
    const call = (fn, arg) => vm.runInContext(`${fn}(${JSON.stringify(arg)})`, sandbox);
    return { sandbox, clock, get, call };
}

// ---- synthetic graph: hub-and-spoke core + facets + N isolates ----
const TYPES = ["person", "project", "company", "concept", "tool", "skill", "location", "media", "directory"];

const SIZES = {
    small:  { n: 300,  isolates: 100, hubs: 6,  facets: 20,  extraLinksPerNode: 3 },
    medium: { n: 1500, isolates: 500, hubs: 20, facets: 100, extraLinksPerNode: 3 },
    dense:  { n: 1500, isolates: 500, hubs: 20, facets: 100, extraLinksPerNode: 5 },
};

function synthetic({ n, isolates, hubs, facets, extraLinksPerNode }) {
    reseed(42);
    const nodes = [], links = [];
    for (let i = 0; i < hubs; i++) {
        nodes.push({ id: "h" + i, name: "H" + i, type: "hub", isHub: true, status: "active", confidence: 0.9, memberCount: 0 });
    }
    const core = n - isolates - facets - hubs;
    for (let i = 0; i < core; i++) {
        const hub = "h" + (i % hubs);
        nodes.push({ id: "c" + i, name: "C" + i, type: TYPES[i % TYPES.length], status: "active", confidence: 0.3 + rnd() * 0.7, hubId: hub });
        links.push({ source: hub, target: "c" + i });
        for (let k = 0; k < extraLinksPerNode; k++) {
            if (i > 0 && rnd() < 0.8) links.push({ source: "c" + i, target: "c" + Math.floor(rnd() * i) });
        }
    }
    for (let i = 0; i < facets; i++) {
        const parent = "c" + Math.floor(rnd() * core);
        nodes.push({ id: "f" + i, name: "F" + i, type: "concept", status: "active", confidence: 0.6, isFacet: true, parentId: parent, context: "engineering" });
        links.push({ source: parent, target: "f" + i, kind: "facetOf" });
    }
    for (let i = 0; i < isolates; i++) {
        nodes.push({ id: "i" + i, name: "I" + i, type: TYPES[i % TYPES.length], status: "active", confidence: 0.3 + rnd() * 0.7 });
    }
    return { nodes, links };
}

// ---- metrics ----
function kePerNode(nodes) { let k = 0; for (const n of nodes) k += n.vx * n.vx + n.vy * n.vy; return k / nodes.length; }
function maxSpeed(nodes) { let m = 0; for (const n of nodes) m = Math.max(m, Math.hypot(n.vx, n.vy)); return m; }
const quantile = (sorted, p) => sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))] : NaN;
const round = (v, d = 0) => (v == null || !isFinite(v)) ? v : +v.toFixed(d);

// Isolate = visible degree 0 (no entry in neighborsById) and not a hub. Radii are
// from the origin, which is the centre of the hub ring and of the type anchors.
function radii(get) {
    const vis = get("visibleNodes"), nb = get("neighborsById");
    const iso = vis.filter(n => !nb.has(n.id) && !n.isHub);
    const core = vis.filter(n => nb.has(n.id));
    const r = a => a.map(n => Math.hypot(n.x, n.y)).sort((x, y) => x - y);
    const ir = r(iso), cr = r(core);
    return {
        isoN: iso.length,
        isoMedian: round(quantile(ir, 0.5)), isoMax: round(ir[ir.length - 1]),
        coreMedian: round(quantile(cr, 0.5)), coreP90: round(quantile(cr, 0.9)), coreMax: round(cr[cr.length - 1]),
        ratioMaxToP90: round(ir[ir.length - 1] / quantile(cr, 0.9), 2),
        ratioMedToP90: round(quantile(ir, 0.5) / quantile(cr, 0.9), 2),
    };
}

// The node every throw scenario uses: the outermost connected non-hub, non-facet
// node with visible degree <= 3. Deterministic for a given synthetic + graph.js.
function peripheralNode(get) {
    const vis = get("visibleNodes"), nb = get("neighborsById");
    const cands = vis.filter(n => !n.isHub && !n.isFacet && nb.has(n.id) && nb.get(n.id).size <= 3);
    return cands.reduce((a, b) => Math.hypot(b.x, b.y) > Math.hypot(a.x, a.y) ? b : a);
}

// Follow one node after a release: how long its OUTWARD velocity component stays
// >= 0.5 wu/tick (coastTicks), how far out it got (coastDist, max projection on the
// throw direction), when |v| first drops below 0.1 (ticksToStop), when d3's own
// timer would have stopped (alpha < alphaMin; timerStopTick), and how far every
// OTHER visible node moved over the 60 ticks after release (otherDisp60).
function followRelease(sim, visibleNodes, node, ux, uy) {
    const rx = node.x, ry = node.y;
    const atRelease = visibleNodes.map(n => [n.x, n.y]);
    let coastTicks = null, coastDist = 0, ticksToStop = null, timerStopTick = null, otherDisp60 = null;
    for (let t = 1; t <= 300; t++) {
        sim.tick();
        const vOut = node.vx * ux + node.vy * uy;
        const proj = (node.x - rx) * ux + (node.y - ry) * uy;
        if (proj > coastDist) coastDist = proj;
        if (coastTicks === null && vOut < 0.5) coastTicks = t - 1;
        if (ticksToStop === null && Math.hypot(node.vx, node.vy) < 0.1) ticksToStop = t;
        if (timerStopTick === null && sim.alpha() < sim.alphaMin()) timerStopTick = t;
        if (t === 60) {
            let disp = 0, cnt = 0;
            visibleNodes.forEach((n, i) => { if (n !== node) { disp += Math.hypot(n.x - atRelease[i][0], n.y - atRelease[i][1]); cnt++; } });
            otherDisp60 = round(disp / cnt, 2);
        }
    }
    return { coastTicks: coastTicks ?? ">300", coastDist: round(coastDist), ticksToStop: ticksToStop ?? ">300", timerStopTick: timerStopTick ?? ">300", otherDisp60 };
}

// One full scenario on one synthetic. Returns a flat metrics object.
function runScenario(sizeName) {
    const size = SIZES[sizeName];
    const { sandbox, clock, get, call } = loadGraph();
    call("updateGraph", synthetic(size));
    const sim = get("simulation");
    sim.stop();
    const visibleNodes = get("visibleNodes");
    const out = { size: sizeName, n: size.n, links: get("visibleLinks").length };

    // 1. cold settle: 400 manual ticks from alpha 1.0
    let ticksToAlphaMin = null, keAtStop = null;
    const t0 = performance.now();
    for (let t = 1; t <= 400; t++) {
        sim.tick();
        if (ticksToAlphaMin === null && sim.alpha() < sim.alphaMin()) { ticksToAlphaMin = t; keAtStop = kePerNode(visibleNodes); }
    }
    out.msPerTick = round((performance.now() - t0) / 400, 2);
    out.ke400 = +kePerNode(visibleNodes).toExponential(1);
    out.maxSpeed400 = round(maxSpeed(visibleNodes), 2);
    out.ticksToAlphaMin = ticksToAlphaMin;
    out.keAtStop = keAtStop == null ? null : +keAtStop.toExponential(1);
    Object.assign(out, radii(get));

    // 2. free coast: mousedown on the peripheral node (the app's only way to raise
    //    alpha before a throw), one tick, release as a click (seeds 0), then set a
    //    28 wu/tick outward velocity by hand — the memo's bench, with graph.js's
    //    own alpha state at release.
    const node = peripheralNode(get);
    const tr = get("transform");
    const toScreen = (x, y) => [x * tr.k + tr.x, y * tr.k + tr.y];
    const r0 = Math.hypot(node.x, node.y), ux = node.x / r0, uy = node.y / r0;
    let [sx, sy] = toScreen(node.x, node.y);
    clock.now = 1000;
    sandbox.onMouseDown({ clientX: sx, clientY: sy, stopImmediatePropagation: noop });
    sim.stop();
    sim.tick();
    clock.now += 5;
    sandbox.onMouseUp({});
    sim.stop();
    node.vx = 28 * ux; node.vy = 28 * uy;
    out.freeAlphaAtRelease = round(sim.alpha(), 3);
    const free = followRelease(sim, visibleNodes, node, ux, uy);
    out.freeCoastTicks = free.coastTicks; out.freeCoastDist = free.coastDist; out.freeTicksToStop = free.ticksToStop;

    // 3. drag-throw through the real handlers: press, six 28-wu moves 16.7 ms apart
    //    (ticking once per move, as the app would), release 5 ms after the last one.
    //    seededDragVelocity's EMA turns the 28 wu/tick pointer motion into ~26.
    for (let t = 0; t < 200; t++) sim.tick(); // let the free coast die out first
    [sx, sy] = toScreen(node.x, node.y);
    clock.now = 5000;
    sandbox.onMouseDown({ clientX: sx, clientY: sy, stopImmediatePropagation: noop });
    sim.stop();
    out.holdAlphaTarget = sim.alphaTarget();
    const stepScreen = 28 * tr.k;
    let holdKE = 0;
    for (let i = 1; i <= 6; i++) {
        clock.now += 1000 / 60;
        sx += stepScreen * ux; sy += stepScreen * uy;
        sandbox.onMouseMove({ clientX: sx, clientY: sy });
        sim.tick();
        holdKE += kePerNode(visibleNodes);
    }
    out.holdKE = +(holdKE / 6).toExponential(1);
    clock.now += 5;
    sandbox.onMouseUp({});
    sim.stop();
    out.seededSpeed = round(Math.hypot(node.vx, node.vy), 1);
    out.alphaAtRelease = round(sim.alpha(), 3);
    const thrown = followRelease(sim, visibleNodes, node, ux, uy);
    out.throwCoastTicks = thrown.coastTicks; out.throwCoastDist = thrown.coastDist;
    out.throwTicksToStop = thrown.ticksToStop; out.throwTimerStopTick = thrown.timerStopTick;
    out.otherDisp60 = thrown.otherDisp60;
    return out;
}

module.exports = { GRAPH_JS, SIZES, loadGraph, synthetic, runScenario, kePerNode, maxSpeed, radii };
```

- [ ] **Step 3: Create the bench**

Create `app/CicadaApp/Tests/graph/graph-physics.bench.js`:

```js
#!/usr/bin/env node
//
// G109 physics bench. Run it with:
//
//     node app/CicadaApp/Tests/graph/graph-physics.bench.js
//     GRAPH_JS=/abs/path/graph.js node app/CicadaApp/Tests/graph/graph-physics.bench.js   # a patched copy
//
// Prints one row per synthetic (small 300 / medium 1500 / dense 1500 nodes) through
// graph.js's REAL startSimulation and drag handlers (see graph-physics-harness.js):
//
//   msPerTick        cost of one simulation.tick() (the only non-deterministic column)
//   ke400            mean vx^2+vy^2 per node after 400 cold ticks — a plateau here means a
//                    force is not alpha-scaled (the G109 phase-1 regression signature)
//   maxSpeed400      fastest node at tick 400, wu/tick
//   ticksToAlphaMin  cold ticks until d3's timer would stop; keAtStop = KE at that tick
//   iso*/core*       radii from the origin after settle: isolates (visible degree 0) vs
//                    connected core; ratioMaxToP90 = isoMax / coreP90
//   free*            a 28 wu/tick outward flick from rest: ticks the outward velocity stays
//                    >= 0.5 wu, distance gained, ticks until |v| < 0.1
//   throw*           the same through the real drag handlers (six 28-wu moves, then release)
//   otherDisp60      mean displacement of every OTHER node over the 60 ticks after that release
//
// Numbers only; the synthetic has no names. Deterministic except msPerTick.

const { GRAPH_JS, SIZES, runScenario } = require("./graph-physics-harness.js");

const COLUMNS = [
    "size", "n", "links", "msPerTick", "ke400", "maxSpeed400", "ticksToAlphaMin", "keAtStop",
    "isoN", "isoMedian", "isoMax", "coreMedian", "coreP90", "coreMax", "ratioMaxToP90", "ratioMedToP90",
    "freeAlphaAtRelease", "freeCoastTicks", "freeCoastDist", "freeTicksToStop",
    "holdAlphaTarget", "holdKE", "seededSpeed", "alphaAtRelease",
    "throwCoastTicks", "throwCoastDist", "throwTicksToStop", "throwTimerStopTick", "otherDisp60",
];

console.log("graph.js:", GRAPH_JS);
const rows = Object.keys(SIZES).map(runScenario);
for (const r of rows) console.log(JSON.stringify(r));
console.log("");
const w = Math.max(...COLUMNS.map(c => c.length));
for (const c of COLUMNS) {
    console.log(c.padEnd(w), rows.map(r => String(r[c] ?? "")).map(v => v.padStart(10)).join(""));
}
```

- [ ] **Step 4: Run the bench twice on the unchanged `graph.js` and confirm determinism**

```sh
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109 && SCRATCH=<your scratch dir> && node app/CicadaApp/Tests/graph/graph-physics.bench.js > $SCRATCH/bench-before-1.txt && node app/CicadaApp/Tests/graph/graph-physics.bench.js > $SCRATCH/bench-before-2.txt && diff <(grep -v msPerTick $SCRATCH/bench-before-1.txt) <(grep -v msPerTick $SCRATCH/bench-before-2.txt) && echo DETERMINISTIC && tail -30 $SCRATCH/bench-before-1.txt
```
Expected: `DETERMINISTIC`, and (msPerTick aside, ~0.7 / ~6.7 / ~6.9 on an M-series Mac) exactly this **baseline** table — measured on `b690b66` while writing this plan:

```
size                    small    medium     dense
n                         300      1500      1500
links                     606      3076      4468
ke400                      13        20        23
maxSpeed400              4.99        11     11.75
ticksToAlphaMin            59        59        59
keAtStop                  3.3       8.6        10
isoN                      100       500       500
isoMedian                 808      1219      1202
isoMax                   1880      2310      2388
coreMedian               1674      1997      2109
coreP90                  1851      2203      2287
coreMax                  1936      2325      2421
ratioMaxToP90            1.02      1.05      1.04
ratioMedToP90            0.44      0.55      0.53
freeAlphaAtRelease        0.2       0.2       0.2
freeCoastTicks              0         1         0
freeCoastDist               0         1         0
freeTicksToStop          >300      >300        38
holdAlphaTarget           0.3       0.3       0.3
holdKE                   2200      3400      8500
seededSpeed              25.9      25.9      25.9
alphaAtRelease            0.2       0.2       0.2
throwCoastTicks             0         0         0
throwCoastDist              0         0         0
throwTicksToStop         >300      >300      >300
throwTimerStopTick         28        28        28
otherDisp60            978.77   1194.39   1275.02
```
Reading it: `ke400` 13–23 with alpha at 1e-9 is the plateau (the unscaled hub gravity vs. the never-alpha-scaled collide); the connected core has been blown out to a 2,000-wu median by 400 ticks of that bounce (which is why the isolate/core ratios look "fine" — nothing is settled); a flick from rest coasts **0 ticks** because the release bump lets the link springs cancel it in one tick; a release moves every other node ~1,000 wu.

- [ ] **Step 5: Run the existing suites (nothing changed, they must be green)**

```sh
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109 && for t in graph-delta graph-drag-velocity graph-logo graph-mindegree-default; do node app/CicadaApp/Tests/graph/$t.test.js | tail -1; done
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109/app/CicadaApp && swift test 2>&1 | tail -20
```
Expected: four "All … checks passed." lines; `swift test`'s tail contains the XCTest line `Executed 530 tests, with 0 failures` (count as of `b690b66`, re-run by the plan critic). The very last lines are swift-testing's `Test run with 0 tests in 0 suites passed` — that block is expected (the suite is XCTest), not a failure.

- [ ] **Step 6: Commit**

```sh
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109 && git add app/CicadaApp/Tests/graph/graph-physics-harness.js app/CicadaApp/Tests/graph/graph-physics.bench.js && git commit -m "$(cat <<'EOF'
test(graph): G109 headless physics bench — real graph.js under real d3

A Node harness that loads Resources/graph/graph.js into a vm context with the
bundled d3.v7.min.js (not the no-op Proxy the other Tests/graph scripts use),
pushes a synthetic hub-and-spoke graph with N isolates through updateGraph, stops
d3's own timer, and ticks startSimulation's real simulation by hand. The drag
handlers are driven with a fake performance.now clock so seededDragVelocity sees
real 16.7 ms gaps. Prints KE/node at tick 400, the settle tick, isolate vs core
radii, a flick-from-rest coast, a drag-throw coast, and the displacement of every
other node after a release, on 300 / 1500 / 1500-dense synthetics. Deterministic
(seeded Math.random) except ms/tick. Lives outside Resources/ (copied into the
bundle wholesale) and outside every SwiftPM target.

Baseline on this commit: KE/node at tick 400 = 13 / 20 / 23 (a plateau: hub
gravity is not alpha-scaled), a 28 wu/tick flick coasts 0 ticks, a release moves
every other node ~1,000 wu.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 2: Alpha-scale hub gravity; no reheat on release; `alphaMin` 0.001

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Resources/graph/graph.js:774-790` (`hubGravityForce`), `:810` (`alphaMin`), `:1404` (`onMouseDown` hold), `:1512-1518` (`onMouseUp` release)
- Create: `app/CicadaApp/Tests/graph/graph-physics.test.js`

**Interfaces:**
- `hubGravityForce(strength)` now returns a d3-shaped force: `force(alpha)` plus `force.initialize(nodes)`. d3 calls `initialize` when the force is bound (`simulation.force(name, f)`) and whenever `simulation.nodes()` changes; `startSimulation` builds a fresh simulation over `visibleNodes` every time, so `initialize` always receives the current visible set — the same array the old per-tick `Map` was built from.

- [ ] **Step 1: Write the failing test**

Create `app/CicadaApp/Tests/graph/graph-physics.test.js` (this is the Task-2 form; Task 3 appends to it):

```js
#!/usr/bin/env node
//
// Regression net for graph.js's physics (G109 phase 1). Run it with:
//
//     node app/CicadaApp/Tests/graph/graph-physics.test.js
//
// Unlike the other four Tests/graph/*.test.js scripts (which mock d3 with a
// chainable no-op Proxy), this one runs graph.js's REAL startSimulation under the
// REAL bundled d3 via graph-physics-harness.js, on three synthetic graphs, and
// asserts the numbers graph-physics.bench.js prints. Every threshold below was set
// from a measured value with margin; the measured values are recorded next to each
// assertion so a future re-tune knows what it is moving.
//
// The one signature this file exists to catch: a KE/node plateau at tick 400. Any
// custom force added to startSimulation without alpha scaling re-creates the
// permanent bounce that motivated velocityDecay 0.45 / alphaMin 0.05 in the first
// place (backlog G109), and ke400 is where it shows first.

const { SIZES, loadGraph, synthetic, runScenario } = require("./graph-physics-harness.js");

let failures = 0;
const check = (label, cond, actual) => {
    console.log((cond ? "PASS " : "FAIL ") + label + (actual === undefined ? "" : `  [${actual}]`));
    if (!cond) failures += 1;
};

const rows = {};
for (const size of Object.keys(SIZES)) rows[size] = runScenario(size);

// ---- Task 2: alpha-scaled hub gravity, alphaMin 0.001, no reheat on release ----
for (const [size, r] of Object.entries(rows)) {
    // measured after Task 2: 2.8e-17 / 6e-4 / 3.6e-3 — before: 13 / 20 / 23
    check(`${size}: KE/node at tick 400 < 1e-1 (no unscaled force)`, r.ke400 < 1e-1, r.ke400);
    // measured: 0 / 0.06 / 0.17 — before: 5.0 / 11 / 11.8
    check(`${size}: fastest node at tick 400 < 0.3 wu/tick`, r.maxSpeed400 < 0.3, r.maxSpeed400);
    // measured: 6 / 6 / 6 ticks (velocityDecay 0.45 arithmetic) — before: 0 / 1 / 0
    check(`${size}: a 28 wu/tick flick from rest coasts >= 5 ticks`, r.freeCoastTicks >= 5, r.freeCoastTicks);
    // measured: 3 / 3 / 2 — before: 0 / 0 / 0 (the alpha bump let the links snap it back in one tick)
    check(`${size}: a drag-throw through the handlers coasts >= 2 ticks`, r.throwCoastTicks >= 2, r.throwCoastTicks);
    check(`${size}: the drag hold targets alpha 0.1, not 0.3`, r.holdAlphaTarget === 0.1, r.holdAlphaTarget);
}
// measured: 1.41 / 9.73 / 28.95 wu — before: 979 / 1194 / 1275 (the whole graph re-laid out)
check("small: other nodes move < 5 wu in the 60 ticks after a release", rows.small.otherDisp60 < 5, rows.small.otherDisp60);
check("medium: other nodes move < 15 wu in the 60 ticks after a release", rows.medium.otherDisp60 < 15, rows.medium.otherDisp60);
check("dense: other nodes move < 40 wu in the 60 ticks after a release", rows.dense.otherDisp60 < 40, rows.dense.otherDisp60);

{
    // Structural: the hub-gravity force is a d3 force (takes alpha, has initialize)
    // and contributes nothing at alpha 0.
    const { get, call } = loadGraph();
    call("updateGraph", synthetic(SIZES.small));
    const sim = get("simulation");
    sim.stop();
    const hub = get("simulation").force("hubGravity");
    check("hubGravity exposes initialize()", typeof hub.initialize === "function");
    check("simulation alphaMin is d3's default 0.001", sim.alphaMin() === 0.001, sim.alphaMin());
    const member = get("visibleNodes").find(n => get("memberToHub").has(n.id));
    member.vx = 0; member.vy = 0; member.x += 500;
    hub(0);
    check("hubGravity at alpha 0 leaves velocity untouched", member.vx === 0 && member.vy === 0, member.vx);
    hub(1);
    check("hubGravity at alpha 1 pulls the displaced member", member.vx < 0, member.vx);
}

console.log("");
if (failures) {
    console.log(`${failures} graph physics check(s) FAILED.`);
    process.exit(1);
}
console.log("All graph physics checks passed.");
```

Run it: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109 && node app/CicadaApp/Tests/graph/graph-physics.test.js | grep -c FAIL`
Expected: **21** FAIL lines (verified on the unchanged file: the 15 per-size checks, the 3 displacement checks, `initialize()` missing on today's bare-function force, `alphaMin` 0.05, and `hubGravity at alpha 0` moving the member because it ignores alpha; only `hubGravity at alpha 1 pulls` passes).

- [ ] **Step 2: Alpha-scale `hubGravityForce` and hoist the id map (graph.js:774-790)**

Replace exactly:

```js
function hubGravityForce(strength) {
    let force;
    function tick() {
        if (!memberToHub.size) return;
        const byId = new Map(visibleNodes.map(n => [n.id, n]));
        for (const n of visibleNodes) {
            const hid = memberToHub.get(n.id);
            if (!hid) continue;
            const hub = byId.get(hid);
            if (!hub) continue;
            n.vx += (hub.x - n.x) * strength;
            n.vy += (hub.y - n.y) * strength;
        }
    }
    force = tick;
    return force;
}
```

with:

```js
// G109: `alpha` is what d3 passes every force each tick (1.0 cold -> alphaMin).
// This force used to ignore it — a permanent `strength`-per-tick spring that,
// against the never-alpha-scaled forceCollide, kept ~1,500 nodes bouncing for
// ever (KE/node plateau ~20 at tick 400 on the bench, 4e-4 once scaled). That
// bounce is what velocityDecay 0.45 / alphaMin 0.05 were papering over. The
// nominal 0.05 is unchanged, so a cold layout at alpha 1.0 is identical to
// before for its first ticks. The id map is built once per simulation in
// initialize() (d3 calls it when the force is bound and when nodes change),
// not on every tick — the force now also runs on every drag frame.
function hubGravityForce(strength) {
    let byId = new Map();
    function force(alpha) {
        if (!memberToHub.size) return;
        const k = strength * alpha;
        for (const n of visibleNodes) {
            const hid = memberToHub.get(n.id);
            if (!hid) continue;
            const hub = byId.get(hid);
            if (!hub) continue;
            n.vx += (hub.x - n.x) * k;
            n.vy += (hub.y - n.y) * k;
        }
    }
    force.initialize = (simNodes) => { byId = new Map(simNodes.map(n => [n.id, n])); };
    return force;
}
```

- [ ] **Step 3: `alphaMin` 0.001 (graph.js:810) and rewrite the stale comment above it (:799-808)**

Replace exactly:

```js
        // G84b: was 0.55 (d3's default is 0.4), which damped a thrown node's
        // seeded velocity to near-zero in ~4 ticks (~65ms) — motion stopped
        // before it was visible. Relaxed partway toward the default rather
        // than all the way to it: 0.4 is exactly the value the comment above
        // says caused indefinite bouncing at ~1500 nodes, so going there
        // risks reintroducing that. 0.45 buys a noticeably longer, visible
        // coast on a throw while keeping most of the extra damping margin
        // above the value that was unstable at scale. If the full graph
        // still oscillates/bounces persistently after this change, raise it
        // back toward 0.55 rather than lowering it further.
        .velocityDecay(0.45)
        .alphaMin(0.05)
```

with:

```js
        // G84b relaxed this 0.55 -> 0.45 for a visible throw; G109 found the
        // "indefinite bouncing at ~1500 nodes" that kept it high was the
        // unscaled hubGravity force below, not d3. Task 3 of the G109 plan
        // lowers it to 0.2 once that force is alpha-scaled.
        .velocityDecay(0.45)
        // G109: d3's default. 0.05 stopped the timer ~27 ticks after any
        // reheat, freezing a thrown node mid-coast; the release path no longer
        // bumps alpha (see onMouseUp), so the runway has to come from here.
        // Cost: a cold run is 135 ticks instead of 59, a 0.3 reheat 112
        // instead of 35 (log arithmetic); phase 2's owned loop replaces this
        // alpha cut-off with a physical settle criterion.
        .alphaMin(0.001)
```

- [ ] **Step 4: Hold at `alphaTarget(0.1)` (graph.js:1404)**

Replace exactly:

```js
        if (simulation) simulation.alphaTarget(0.3).restart();
```

with:

```js
        // G109: 0.1, not 0.3 — the hold used to heat the whole graph so every
        // node jittered under the cursor (bench: KE/node 2e3-8e3 during a
        // hold, 4e-3-5.5 at 0.1). Enough alpha for the neighbours to follow.
        if (simulation) simulation.alphaTarget(0.1).restart();
```

- [ ] **Step 5: Release without the alpha bump (graph.js:1512-1518)**

Replace exactly:

```js
        if (simulation) {
            // Leave enough alpha for the seeded velocity to actually animate
            // a visible coast instead of alphaTarget(0) alone, which only
            // stops pulling the sim back UP — it doesn't guarantee alpha is
            // above alphaMin (0.05) for the few ticks a throw needs to read.
            simulation.alphaTarget(0).alpha(Math.max(simulation.alpha(), 0.2)).restart();
        }
```

with:

```js
        if (simulation) {
            // G109: NO alpha bump on release. d3 integrates `x += vx *= (1 -
            // velocityDecay)` regardless of alpha, so the seeded velocity
            // coasts on its own; alpha only needs to be above alphaMin (now
            // 0.001, and the hold's alphaTarget(0.1) already raised it) so the
            // timer keeps ticking. The old `alpha(max(alpha, 0.2))` reheated
            // every node: measured ~1,000 wu mean displacement of the OTHER
            // nodes over the next second, and the link springs at alpha 0.2
            // cancelled a 26 wu/tick throw in a single tick — the "no
            // deceleration" the user saw. Now 1-30 wu and a real coast.
            simulation.alphaTarget(0).restart();
        }
```

- [ ] **Step 6: Run the physics test and the bench**

```sh
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109 && node app/CicadaApp/Tests/graph/graph-physics.test.js | tail -3 && node app/CicadaApp/Tests/graph/graph-physics.bench.js | tail -30
```
Expected: `All graph physics checks passed.` and exactly this table (the `msPerTick` row is omitted here — it is the one non-deterministic value, ~0.6 / 6.3 / 6.7) — measured with these edits while writing the plan and independently re-run by the plan critic:

```
size                    small    medium     dense
n                         300      1500      1500
links                     606      3076      4468
ke400                 2.8e-17    0.0006    0.0036
maxSpeed400                 0      0.06      0.17
ticksToAlphaMin           135       135       135
keAtStop             0.000019     0.034       0.4
isoN                      100       500       500
isoMedian                 756      1114      1078
isoMax                    926      1403      1380
coreMedian                254       470       484
coreP90                   443       694       679
coreMax                   652       967       866
ratioMaxToP90            2.09      2.02      2.03
ratioMedToP90            1.71       1.6      1.59
freeAlphaAtRelease      0.005     0.005     0.005
freeCoastTicks              6         6         6
freeCoastDist              34        35        35
freeTicksToStop             9        11        10
holdAlphaTarget           0.1       0.1       0.1
holdKE                 0.0041      0.49       5.5
seededSpeed              25.9      25.9      25.9
alphaAtRelease          0.026     0.026     0.026
throwCoastTicks             3         3         2
throwCoastDist             18        21        16
throwTicksToStop           71        67        73
throwTimerStopTick         64        64        64
otherDisp60              1.41      9.73     28.95
```
Direction: `ke400` 20 → 6e-4 (the plateau is gone), the core settles to a 470-wu median, and — now that it is settled — the isolate ring shows for the first time (isolate median 1.6× core p90, max 2×): Task 3's target. Flick from rest 0 → 6 ticks / 34 wu (vd 0.45's arithmetic, R4); other-node displacement 1,194 → 9.7 wu.

- [ ] **Step 7: Run the existing suites**

```sh
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109 && for t in graph-delta graph-drag-velocity graph-logo graph-mindegree-default; do node app/CicadaApp/Tests/graph/$t.test.js | tail -1; done
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109/app/CicadaApp && swift test 2>&1 | tail -20
```
Expected: four "All … checks passed."; `swift test` 0 failures.

- [ ] **Step 8: Commit**

```sh
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109 && git add app/CicadaApp/Sources/CicadaApp/Resources/graph/graph.js app/CicadaApp/Tests/graph/graph-physics.test.js && git commit -m "$(cat <<'EOF'
fix(graph): G109 phase 1a — alpha-scale hub gravity, no reheat on release, alphaMin 0.001

hubGravityForce ignored the alpha d3 passes every force, so it was a permanent
5%/tick spring fighting the never-alpha-scaled forceCollide: KE/node at tick 400
stayed at 13-23 on the bench (alpha 1e-9) — the "1,500 nodes bounce forever"
that velocityDecay 0.45 / alphaMin 0.05 were papering over. It now takes
`alpha` and multiplies by it (nominal 0.05 unchanged; id map hoisted into
initialize). The release path's `alpha(max(alpha, 0.2))` reheated the whole
graph (~1,000 wu mean displacement of every other node, and the link springs at
alpha 0.2 cancelled a throw in one tick); it is now `alphaTarget(0).restart()`.
alphaMin goes to d3's default 0.001 in the same commit because without it the
timer stops one tick after a short drag's release. The drag hold targets alpha
0.1 instead of 0.3.

Bench (small / medium / dense synthetic): KE/node@400 13/20/23 -> 3e-17/6e-4/4e-3;
flick from rest 0 -> 6 ticks / 34 wu; other-node displacement after a release
979/1194/1275 -> 1.4/9.7/29 wu. Isolate ring now visible on a settled layout
(isolate median 1.6x core p90) — phase 1b.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 3: `velocityDecay` 0.2, isolate containment, speed clamp

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Resources/graph/graph.js` — insert a block above `function startSimulation`; `startSimulation` (`velocityDecay`, charge strength, force list, first line); `xAnchor`, `yAnchor`, `anchorStrength`
- Modify: `app/CicadaApp/Tests/graph/graph-physics.test.js` (append the Task-3 block)

**Interfaces:**
- New module state `isolateSlots: Map<id, {x, y, type, index}>` (read by the test through `get("isolateSlots")`), `isolateSlotIndexByType: Map<type, Set<index>>`.
- New functions: `isIsolate(d)`, `isolateAnchor(type) -> [x, y]`, `isolateSlotPosition(type, index) -> {x, y, type, index}`, `assignIsolateSlots()`, `clampSpeedForce()`.
- New constants: `ISOLATE_ANCHOR_SCALE`, `ISOLATE_RING_R`, `ISOLATE_SLOT_SPACING`, `ISOLATE_ANCHOR_STRENGTH`, `ISOLATE_CHARGE`, `GOLDEN_ANGLE`, `VMAX_WU_PER_TICK`. `ISOLATE_RING_R` (480, the magnitude of the type anchors at `:45-58`) is the fallback centre for an isolate whose `type` has no entry in `typeClusterPositions` — every type the backend emits today has one, so no synthetic exercises it and it is unmeasured; it exists so an unknown type lands beside the clusters instead of at `(0, 0)` under the core (critic gap 5d) and never in a halo beyond them (R7).

- [ ] **Step 1: Append the failing Task-3 checks to the test**

In `app/CicadaApp/Tests/graph/graph-physics.test.js`, insert the following immediately BEFORE the final `console.log("");` / failure summary block:

```js
// ---- Task 3: velocityDecay 0.2, isolate containment, speed clamp ----
for (const [size, r] of Object.entries(rows)) {
    // measured: 12 / 13 / 13 ticks, 63 / 99 / 100 wu — Task 2 alone: 6 ticks / 34-35 wu
    check(`${size}: a 28 wu/tick flick from rest coasts >= 10 ticks`, r.freeCoastTicks >= 10, r.freeCoastTicks);
    check(`${size}: ... and gains >= 60 wu`, r.freeCoastDist >= 60, r.freeCoastDist);
    // measured isoMax/coreMax: 1.06 / 0.82 / 0.93 — Task 2 alone: 1.42 / 1.45 / 1.59
    check(`${size}: no isolate sits beyond 1.1x the farthest connected node`, r.isoMax <= 1.1 * r.coreMax, `${r.isoMax} vs coreMax ${r.coreMax}`);
    // measured isoMedian/coreP90: 1.30 / 1.09 / 1.10 — Task 2 alone: 1.71 / 1.60 / 1.59
    check(`${size}: isolate median radius <= 1.35x core p90`, r.ratioMedToP90 <= 1.35, r.ratioMedToP90);
}
// measured: 99 / 100 wu on the 1500-node synthetics (the memo's >= 80 wu, collide on)
check("medium: flick from rest gains >= 90 wu", rows.medium.freeCoastDist >= 90, rows.medium.freeCoastDist);
check("dense: flick from rest gains >= 90 wu", rows.dense.freeCoastDist >= 90, rows.dense.freeCoastDist);
// measured isoMax/coreP90: 1.31 / 1.28 — Task 2 alone: 2.02 / 2.03 (the ring)
check("medium: isolate max radius <= 1.35x core p90", rows.medium.ratioMaxToP90 <= 1.35, rows.medium.ratioMaxToP90);
check("dense: isolate max radius <= 1.35x core p90", rows.dense.ratioMaxToP90 <= 1.35, rows.dense.ratioMaxToP90);
// Containment must not compress the connected core: Task-2 core medians were 254 / 470 / 484.
const CORE_MEDIAN_BEFORE_CONTAINMENT = { small: 254, medium: 470, dense: 484 };
for (const [size, before] of Object.entries(CORE_MEDIAN_BEFORE_CONTAINMENT)) {
    const r = rows[size];
    check(`${size}: core median within +-10% of its pre-containment value (${before})`, r.coreMedian >= 0.9 * before && r.coreMedian <= 1.1 * before, r.coreMedian);
}

{
    // Slot stability across deltas (the L2/L3 position-preservation contract):
    // an added isolate whose id sorts FIRST must not shift anyone else's slot; a
    // removed isolate frees its index; an isolate that gains a link leaves the map.
    const { get, call } = loadGraph();
    const g = synthetic(SIZES.small);
    call("updateGraph", g);
    get("simulation").stop();
    const before = new Map([...get("isolateSlots")].map(([id, s]) => [id, `${s.type}:${s.index}`]));
    check("isolates were assigned slots", before.size === SIZES.small.isolates, before.size);
    const firstIsolate = g.nodes.find(n => n.id === "i0");
    call("updateGraphDelta", { added: [{ ...firstIsolate, id: "a-sorts-first", name: "A" }], updated: [], removed: ["i1"] });
    get("simulation").stop();
    const after = get("isolateSlots");
    check("a new isolate whose id sorts first got a slot", after.has("a-sorts-first"));
    check("the removed isolate lost its slot", !after.has("i1"));
    let shifted = 0;
    for (const [id, key] of before) if (id !== "i1" && after.has(id) && `${after.get(id).type}:${after.get(id).index}` !== key) shifted += 1;
    check("no surviving isolate changed slot", shifted === 0, shifted);
    check("the newcomer's slot is in its own type's disc", after.get("a-sorts-first").type === firstIsolate.type, after.get("a-sorts-first").type);
    call("updateGraphDelta", { added: [], updated: [], removed: [], links: [...g.links, { source: "i2", target: "c0" }] });
    get("simulation").stop();
    check("an isolate that gained a visible link left the slot map", !get("isolateSlots").has("i2"));
}

{
    // Speed clamp: a node launched at 200 wu/tick is at most VMAX after one tick.
    const { get, call } = loadGraph();
    call("updateGraph", synthetic(SIZES.small));
    const sim = get("simulation");
    sim.stop();
    for (let t = 0; t < 50; t++) sim.tick();
    const n = get("visibleNodes")[10];
    n.vx = 200; n.vy = 0;
    sim.tick();
    check("clampSpeed caps a launched node at 60 wu/tick", Math.hypot(n.vx, n.vy) <= 60, Math.hypot(n.vx, n.vy).toFixed(1));
    check("velocityDecay is 0.2", Math.abs(sim.velocityDecay() - 0.2) < 1e-9, sim.velocityDecay());
}

```

Run it: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109 && node app/CicadaApp/Tests/graph/graph-physics.test.js 2>&1 | grep -c "^FAIL"; node app/CicadaApp/Tests/graph/graph-physics.test.js 2>&1 | grep -m1 ReferenceError`
Expected: 16 FAIL lines from the first Task-3 loop (measured on the Task-2 file), then `ReferenceError: isolateSlots is not defined` from the slot block — the file exits non-zero either way.

- [ ] **Step 2: Insert the isolate block above `startSimulation`**

Find the unique line `function startSimulation({ reheat = 1.0 } = {}) {` and insert this block immediately ABOVE it (it must be able to see `typeClusterPositions`, `hashHue`, `nodeIsHub`, `memberToHub`, `neighborsById`, `visibleNodes` — all module-level and defined earlier):

```js
// ---------- G109 isolate containment ----------
//
// A zero-degree node has nothing pulling it in: forceCenter is a uniform
// translation of the centroid (it cannot pull an individual node), and the
// 0.04 type anchor loses to forceManyBody(-150) from ~1,000 bodies until the
// node clears distanceMax(700) and parks — the ring the user photographed. Each
// isolate gets its own slot on a Vogel-phyllotaxis disc centred on its type's
// anchor (the same arrangement d3 uses to initialise nodes), pulled by the
// existing xType/yType forces at ISOLATE_ANCHOR_STRENGTH, and exerts a weaker
// charge so a disc of them does not blast itself apart. Measured on the bench
// (1500-node synthetic): isolate max radius 2.0x -> 1.3x core p90, no isolate
// beyond the farthest connected node, core median unchanged. Phase 3 (not
// built) excludes isolates from the simulation entirely, which makes the disc
// a guarantee instead of a tuning outcome.
//
// Levers, for the phase-2 live-bank tuning pass: ISOLATE_ANCHOR_STRENGTH (0.2
// -> ratio 1.4, 0.3 -> 1.3, 0.5 -> 1.2 but +30% post-release motion and the
// disc inside the type cluster); ISOLATE_SLOT_SPACING (20 is collision-free for
// two high-confidence isolates: 2 x (4 + 8 + 6) = 36 wu); ISOLATE_ANCHOR_SCALE
// (measured NOT to move the outcome at 1.0-1.8: the resting radius is set by
// the core's outward push, which per-node charge cannot reduce — d3's
// strength() sets what a body EXERTS, not what it receives).
const ISOLATE_ANCHOR_SCALE = 1.0;     // multiplies the type anchor; 1.0 = centred on it
const ISOLATE_RING_R = 480;           // fallback for a type with no anchor: same radius as the type anchors (450-540), never a halo beyond them
const ISOLATE_SLOT_SPACING = 20;      // c in r = c * sqrt(i)
const ISOLATE_ANCHOR_STRENGTH = 0.3;  // forceX/forceY strength for an isolate (d3 range [0, 1])
const ISOLATE_CHARGE = -30;           // what an isolate EXERTS (vs -150 for a connected node)
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const VMAX_WU_PER_TICK = 60;          // speed clamp; a 1000 px/s flick at k=0.6 seeds ~28

let isolateSlots = new Map();                 // id -> { x, y, type, index }
const isolateSlotIndexByType = new Map();     // type -> Set<index> in use

// Visible degree 0, not a hub (hubs anchor to the ring), not a hub member or a
// facet with its parent on the graph (both are pulled by hubGravity). Reads
// neighborsById — built from visibleLinks — so a node whose only edges the
// contexts filter dropped counts as isolated, unlike _localDegree. An orphan
// facet (parent not on the graph) IS an isolate: today it falls to a 0.04 pull
// toward typeClusterPositions[<facet type>], i.e. (0, 0), and drifts.
function isIsolate(d) {
    return !nodeIsHub(d) && !memberToHub.has(d.id) && !neighborsById.has(d.id);
}

function isolateAnchor(type) {
    const t = typeClusterPositions[type];
    if (t && type !== "hub") return [t[0] * ISOLATE_ANCHOR_SCALE, t[1] * ISOLATE_ANCHOR_SCALE];
    const a = (hashHue(String(type)) / 360) * 2 * Math.PI;
    return [Math.cos(a) * ISOLATE_RING_R, Math.sin(a) * ISOLATE_RING_R];
}

function isolateSlotPosition(type, index) {
    const [cx, cy] = isolateAnchor(type);
    const r = ISOLATE_SLOT_SPACING * Math.sqrt(index + 0.5);
    const a = index * GOLDEN_ANGLE;
    return { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a), type, index };
}

// Stable per-type free-list: an isolate keeps its slot across updateGraph /
// updateGraphDelta / applyFilters for as long as it stays an isolate of the
// same type; a newcomer takes the lowest free index of its type; a node that
// gains a visible link, changes type, or leaves releases its index. Sorting
// isolates by id instead would re-shuffle every slot after any insert that
// sorts earlier, defeating the delta path's position preservation. Runs at
// the top of startSimulation, which every caller reaches only after
// rebuildNeighborsIndex(), and before d3 evaluates the forceX/forceY accessors
// (once, at initialize).
function assignIsolateSlots() {
    const current = new Map();
    for (const n of visibleNodes) if (isIsolate(n)) current.set(n.id, n.type);
    for (const [id, slot] of isolateSlots) {
        if (current.get(id) !== slot.type) {
            isolateSlots.delete(id);
            isolateSlotIndexByType.get(slot.type)?.delete(slot.index);
        }
    }
    const ids = [...current.keys()].filter(id => !isolateSlots.has(id)).sort();
    for (const id of ids) {
        const type = current.get(id);
        if (!isolateSlotIndexByType.has(type)) isolateSlotIndexByType.set(type, new Set());
        const used = isolateSlotIndexByType.get(type);
        let index = 0;
        while (used.has(index)) index += 1;
        used.add(index);
        isolateSlots.set(id, isolateSlotPosition(type, index));
    }
}

// Guard, not a force: with velocityDecay at 0.2 a reheat can launch a node;
// this rescales any velocity above VMAX down to it. Registered LAST so it sees
// the summed velocity (d3 applies forces in insertion order, then damping).
// Deliberately not alpha-scaled — it can only remove energy, so it cannot
// re-create the plateau that rule "alpha-scale every custom force" guards.
function clampSpeedForce() {
    return function force() {
        for (const n of visibleNodes) {
            const s = Math.hypot(n.vx, n.vy);
            if (s > VMAX_WU_PER_TICK) { const k = VMAX_WU_PER_TICK / s; n.vx *= k; n.vy *= k; }
        }
    };
}

```

- [ ] **Step 3: Wire it into `startSimulation`**

Four exact replacements inside `startSimulation`:

(a) First line — replace:
```js
function startSimulation({ reheat = 1.0 } = {}) {
    if (simulation) simulation.stop();
```
with:
```js
function startSimulation({ reheat = 1.0 } = {}) {
    if (simulation) simulation.stop();
    assignIsolateSlots();
```

(b) `velocityDecay` — replace the comment + call written in Task 2:
```js
        // G84b relaxed this 0.55 -> 0.45 for a visible throw; G109 found the
        // "indefinite bouncing at ~1500 nodes" that kept it high was the
        // unscaled hubGravity force below, not d3. Task 3 of the G109 plan
        // lowers it to 0.2 once that force is alpha-scaled.
        .velocityDecay(0.45)
```
with:
```js
        // G109: 0.2 (d3 default 0.4; was 0.55, then 0.45 under G84b). Each
        // tick keeps 80% of velocity, so a 28 wu/tick flick coasts ~13 ticks /
        // ~100 wu with collide on (bench) instead of 6 / 34. The "indefinite
        // bouncing at ~1500 nodes" that kept this high was the unscaled
        // hubGravity force, not d3: with it alpha-scaled, KE/node at tick 400
        // is 4e-6 at 0.2 on the bench. graph-physics.test.js guards that.
        .velocityDecay(0.2)
```

(c) Charge — replace:
```js
            .strength(-150)
            .distanceMax(700)
```
with:
```js
            .strength(d => isIsolate(d) ? ISOLATE_CHARGE : -150)
            .distanceMax(700)
```

(d) Force list — replace:
```js
        .force("hubGravity", hubGravityForce(0.05))
        .on("tick", scheduleRedraw)
```
with:
```js
        .force("hubGravity", hubGravityForce(0.05))
        .force("clampSpeed", clampSpeedForce())
        .on("tick", scheduleRedraw)
```

- [ ] **Step 4: Isolate branch in the anchors (`xAnchor`, `yAnchor`, `anchorStrength`)**

Replace:
```js
function xAnchor(d) {
    if (nodeIsHub(d) && hubAnchors.has(d.id)) return hubAnchors.get(d.id)[0];
```
with:
```js
function xAnchor(d) {
    const slot = isolateSlots.get(d.id);
    if (slot) return slot.x;
    if (nodeIsHub(d) && hubAnchors.has(d.id)) return hubAnchors.get(d.id)[0];
```

Replace:
```js
function yAnchor(d) {
    if (nodeIsHub(d) && hubAnchors.has(d.id)) return hubAnchors.get(d.id)[1];
```
with:
```js
function yAnchor(d) {
    const slot = isolateSlots.get(d.id);
    if (slot) return slot.y;
    if (nodeIsHub(d) && hubAnchors.has(d.id)) return hubAnchors.get(d.id)[1];
```

Replace:
```js
function anchorStrength(d) {
    if (nodeIsHub(d) && hubAnchors.has(d.id)) return 0.08;  // hubs anchor strongly
```
with:
```js
function anchorStrength(d) {
    if (isolateSlots.has(d.id)) return ISOLATE_ANCHOR_STRENGTH;  // G109: isolates sit in their disc
    if (nodeIsHub(d) && hubAnchors.has(d.id)) return 0.08;  // hubs anchor strongly
```

- [ ] **Step 5: Run the physics test and the bench**

```sh
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109 && node app/CicadaApp/Tests/graph/graph-physics.test.js | tail -3 && node app/CicadaApp/Tests/graph/graph-physics.bench.js | tail -30
```
Expected: `All graph physics checks passed.` and exactly this table (`msPerTick` omitted, ~0.6 / 6.5 / 6.8) — measured with these edits while writing the plan and independently re-run by the plan critic (both the 21-FAIL Task-2 baseline count and the 16-FAIL + `ReferenceError` Task-3 count were re-verified too):

```
size                    small    medium     dense
n                         300      1500      1500
links                     606      3076      4468
ke400                 4.5e-16 0.0000039  0.000035
maxSpeed400                 0      0.01      0.02
ticksToAlphaMin           135       135       135
keAtStop             0.000068     0.073      0.76
isoN                      100       500       500
isoMedian                 593       769       769
isoMax                    708       922       893
coreMedian                259       477       500
coreP90                   456       704       699
coreMax                   667      1123       957
ratioMaxToP90            1.55      1.31      1.28
ratioMedToP90             1.3      1.09       1.1
freeAlphaAtRelease      0.005     0.005     0.005
freeCoastTicks             12        13        13
freeCoastDist              63        99       100
freeTicksToStop            17        52        16
holdAlphaTarget           0.1       0.1       0.1
holdKE                  0.035       1.5        20
seededSpeed              25.9      25.9      25.9
alphaAtRelease          0.026     0.026     0.026
throwCoastTicks             4         4         3
throwCoastDist             38        35        24
throwTicksToStop           81        84        86
throwTimerStopTick         64        64        64
otherDisp60              1.78      8.83     27.75
```
Direction vs Task 2: flick from rest 6 → 12–13 ticks, 34 → 63–100 wu; isolate max 2.0× → 1.3× core p90 on the 1500-node synthetics and never beyond 1.1× the farthest connected node; core median moves +2 / +1.5 / +3 %. `throwCoastTicks` stays short (3–4) because a drag stretches the node's links by 168 wu before the flick, so the spring-back dominates — that is physics, and the ~80 ticks of visible spring-back that follow (`throwTicksToStop`) are the deceleration the user asked for. `ms/tick` is unchanged within noise (~6.5–6.9 on the 1500-node synthetics; the memo's 7.3 was a 1,900-node / 6,800-link graph).

- [ ] **Step 6: Run the existing suites**

```sh
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109 && for t in graph-delta graph-drag-velocity graph-logo graph-mindegree-default; do node app/CicadaApp/Tests/graph/$t.test.js | tail -1; done
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109/app/CicadaApp && swift test 2>&1 | tail -20
```
Expected: four "All … checks passed." (verified against this exact patch set while writing the plan); `swift test` 0 failures.

- [ ] **Step 7: Commit**

```sh
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109 && git add app/CicadaApp/Sources/CicadaApp/Resources/graph/graph.js app/CicadaApp/Tests/graph/graph-physics.test.js && git commit -m "$(cat <<'EOF'
fix(graph): G109 phase 1b — velocityDecay 0.2, isolate discs, speed clamp

velocityDecay 0.45 -> 0.2 now that the unscaled hub-gravity bounce is gone
(KE/node at tick 400 stays 4e-6 on the 1500-node bench): a 28 wu/tick flick
from rest coasts 12-13 ticks / 63-100 wu with collide on, instead of 6 / 34.

Zero-degree nodes used to fly to a ring at the periphery: forceCenter cannot
pull an individual node and the 0.04 type anchor lost to the core's charge.
Each isolate (visible degree 0 via neighborsById, not a hub, not a hub member
or a facet with its parent on the graph) now owns a stable slot on a
phyllotaxis disc centred on its type anchor — a per-type free-list, so a delta
never re-shuffles the survivors — and is pulled there by the existing
xType/yType forces at 0.3, exerting -30 charge instead of -150. Bench: isolate
max radius 2.0x -> 1.3x core p90 on the 1500-node synthetics, never beyond 1.1x
the farthest connected node, core median within 3%. A last-registered
clampSpeed force caps any node at 60 wu/tick so a reheat cannot launch one now
that damping is lower.

Disclosed: a NEW isolate arriving via a delta still seeds at its type anchor
+-30 (seedPositionFor untouched) and transits to its slot; phase 3 seeds it
there. Live-bank tuning of ISOLATE_ANCHOR_STRENGTH / ISOLATE_SLOT_SPACING is
phase 2's, read through __cicadaPerf.report().

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 4: Docs — ruling into CLAUDE.md, the G109 row, and the TODO handoff

**Files:**
- Modify: `CLAUDE.md:524` (the "Why d3-force" line)
- Modify: `docs/goals/memory-evolution.md:671` (the G109 row — one line)
- Modify: `docs/goals/TODO.md` (header "Where things stand", "Pick up here" item 1, `_Last synced_`, Shipped block, In progress row :197, Wave A #1 :205-207, Known-broken :298)

**Interfaces:** none (prose).

**`PR #TBD` is deliberate.** This plan never pushes or opens a PR, so the literal `PR #TBD` is committed as-is — seven occurrences: 0 in `CLAUDE.md`, 2 in the (single-line) G109 row, 5 in `TODO.md`. Whoever opens the PR replaces every one with the real number in one follow-up docs commit; `grep -rn 'PR #TBD' CLAUDE.md docs/goals` finds them. Do not invent a number.

- [ ] **Step 1: CLAUDE.md — the ruling in one sentence**

Replace exactly (line 524):
```
**Why d3-force:** Best ecosystem for node coloring, edge labels, zoom/pan, click handlers. More than sufficient for personal-scale graphs (hundreds of nodes). Obsidian uses Pixi.js for large scale — not a concern here.
```
with:
```
**Why d3-force:** Best ecosystem for node coloring, edge labels, zoom/pan, click handlers. More than sufficient for personal-scale graphs (hundreds of nodes). Obsidian uses Pixi.js for large scale — not a concern here. **Ruling (G109, 2026-09-02):** measured against sigma.js/ForceAtlas2, Pixi, cosmos, ngraph and d3-force-3d at ~1,900 nodes, the two G109 symptoms were three local bugs in how `graph.js` drove d3-force (an un-alpha-scaled custom force, a release-path reheat, nothing opposing charge on degree-0 nodes), so d3-force stays; the only flip trigger is an in-app p95 frame time above 16.7 ms on the live bank after the phase-2 loop and phase-3 isolate exclusion, or a graph well past ~10k nodes. Two rules follow: **every custom force multiplies by the `alpha` d3 passes it** (a guard that only removes energy is the one exception), and **the release path never bumps alpha** — a throw coasts on velocity, not on a hot graph. `app/CicadaApp/Tests/graph/graph-physics.test.js` (real d3, real `graph.js`) is the regression net; a KE/node plateau at tick 400 is the signature of a force that broke the first rule.
```

- [ ] **Step 2: The G109 row (docs/goals/memory-evolution.md:671)**

The row is one line. Replace its exact tail:
```
relates **G107** (the same "we hand-rolled art/physics that a library does better" question). | 🔲 **urgent** |
```
with:
```
relates **G107** (the same "we hand-rolled art/physics that a library does better" question). **Ruling (2026-09-02, research run: inventory → five candidates → three judges → decision memo + critic):** keep d3-force and fix `graph.js` (judges 8.33/10; runner-up sigma.js + graphology + ForceAtlas2 at 5.64 — measured to contain isolates natively and 60 fps in a real WKWebView, but no velocity model, an esbuild step, and a 12–20-day port of the earned behaviours; Pixi is a renderer-only stage deferred behind the flip trigger; cosmos rebuilds velocity in the shader so a throw is impossible; ngraph's isolates are unbounded and `stable` never fires; d3-force-3d is byte-identical in 2D). The symptoms were three local bugs: (a) `hubGravityForce` ignored `alpha` — a permanent 5 %/tick spring against the never-alpha-scaled `forceCollide`, the real origin of the "1,500 nodes bounce forever" folklore that justified `velocityDecay` 0.45 / `alphaMin` 0.05 (bench: KE/node at tick 400 = 13–23 with alpha at 1e-9; 4e-6 once scaled); (b) the release path's `alpha(max(alpha, 0.2))` reheated the whole graph (~1,000 wu mean displacement of every other node) and let the link springs cancel a throw in one tick; (c) `forceCenter` is a uniform translation and cannot pull a node, so nothing opposed charge on degree-0 nodes. **Flip trigger:** p95 tick+draw > 16.7 ms on the live bank after phases 1–2 with isolates excluded (phase 3), or > ~10k nodes. **Phase 1 shipped (PR #TBD)** — `graph.js` only, no Swift, no dependency: hub gravity alpha-scaled (nominal 0.05 kept, id map hoisted into `initialize`); release `alphaTarget(0).restart()` with no bump; hold `alphaTarget(0.1)`; `alphaMin` 0.001; `velocityDecay` 0.2; `alphaDecay` 0.05 and `distanceMax` 700 unchanged; each isolate (`!hub && !memberToHub && !neighborsById` — visible degree 0 from `visibleLinks`, orphan facets included) owns a stable per-type free-list slot on a phyllotaxis disc (c = 20) centred on its type anchor, pulled by the existing `forceX/forceY` at 0.3 and exerting −30 charge; a last-registered `clampSpeed` at 60 wu/tick. Measured through `graph.js` itself on synthetic 300 / 1,500 / 1,500-dense graphs (`Tests/graph/graph-physics.bench.js`, real d3): KE/node@400 13 / 20 / 23 → 4e-16 / 4e-6 / 4e-5; a 28 wu/tick flick from rest 0 → 12–13 ticks, 0 → 63 / 99 / 100 wu; other-node displacement over the second after a release 979 / 1,194 / 1,275 → 1.8 / 8.8 / 28 wu; isolate max radius 2.0× → 1.3× core p90 on the 1,500-node graphs and never beyond 1.1× the farthest connected node; core median within 3 %; ms/tick unchanged (~6.5–6.9). Superseded memo values: isolate pull 0.10 (measured to leave the ring at 1.6×; the anchor scale 1.0–1.8 does not move the outcome because per-node charge sets what a body *exerts*, not what it receives), and the "≤ 1.2× core p90" / "no isolate beyond 700 wu" criteria (geometrically incompatible with a disc beside its type cluster; replaced by the four asserted above). Disclosed: reheats run longer at `alphaMin` 0.001 (cold 59 → 135 ticks, a 0.3 reheat 35 → 112) and the cold layout still freezes at the alpha cut-off while relaxing; a new isolate from a delta seeds at its type anchor and transits to its slot. **Open — phase 2** (own the rAF loop: physical settle criterion, one tick per frame, `__cicadaPerf.report()` with tick/draw p50/p95 and the isolate/core radii, then the live-bank tuning pass over `ISOLATE_ANCHOR_STRENGTH` 0.2–0.5 / spacing 12–20 / hold 0.05–0.1 / vd 0.15–0.2); **phase 3** (exclude isolates from the simulation: tick 6.7 → 4.5 ms measured, containment by construction, `pickNode` fallback scan); and the **Swift track** — `ContentView.swift:137-139` rebuilds the `WKWebView` on every tab switch, which is where "explosion on return" comes from (keep one web view alive; reset `isGraphReady` on teardown). | 🛠️ **phase 1 shipped (PR #TBD); phases 2–3 + Swift track open** |
```

- [ ] **Step 3: TODO.md — handoff header**

(a) In "## Where things stand", append after the "**#29 — wikilinks (merged 2026-09-01).**" paragraph (i.e. before the "**Live environment (verified):**" paragraph) this new paragraph:
```
**G109 phase 1 — graph physics (2026-09-02, PR #TBD against `dev`).** The research run ruled: keep
d3-force, fix `graph.js` — the "no deceleration" and "orphan ring" were three local bugs, not the
engine (an un-alpha-scaled custom force, a release-path reheat, nothing opposing charge on degree-0
nodes). Three `graph.js` commits plus a committed headless bench (`Tests/graph/graph-physics.bench.js`,
real d3 driving the real `startSimulation`): KE/node at tick 400 20 → 4e-6, a flick coasts 0 → 13
ticks / 100 wu, a release moves the rest of the graph 1,200 → 9 wu, isolate max radius 2.0× → 1.3×
core p90. Two rules now in CLAUDE.md: alpha-scale every custom force; never bump alpha on release.
**Not done:** the live-bank visual check (needs Rodrigo at the machine — the bank holds real people),
phase 2 (own the loop + `__cicadaPerf`), phase 3 (isolates out of the sim), and the Swift track
(`ContentView` rebuilds the `WKWebView` per tab switch — that is the "explosion on return").
```

(b) Replace the "Pick up here" item 1 exactly:
```
1. **G109 (urgent)** — read the decision memo if one exists (the session writes it to its
   scratchpad, then folds the ruling into the G109 row); otherwise the row itself names the five
   candidates and the two symptoms. Phase 1 must fix both *invisible deceleration* and the *orphan
   ring* in a day, or the port decision is made for us.
```
with:
```
1. **G109 phase 1 is in PR #TBD** — merge it after an independent re-run of
   `node app/CicadaApp/Tests/graph/graph-physics.test.js`, the four sibling JS tests and
   `swift test`, then have Rodrigo eyeball the live bank at fit-zoom (isolates should read as discs
   on their type clusters, not a halo). Then the **Swift track** (one long-lived `WKWebView`, reset
   `isGraphReady` on teardown — ~0.5 day) before phase 2; without it the user still sees a re-layout
   every time they return to the Graph tab. Phases 2–3 are in the G109 row.
```

(c) Replace exactly:
```
_Last synced: 2026-09-01 evening (PRs #21–#29 merged, no open PRs; G88 shipped; G112–G114 filed; G109 in research)._
```
with:
```
_Last synced: 2026-09-02 (G109 phase 1 in PR #TBD; PRs #21–#29 merged; G88 shipped; G112–G114 filed)._
```

- [ ] **Step 4: TODO.md — execution view**

(a) In "## ✅ Shipped", the "**2026-08-31 → 09-01 (PRs #21–#29, merged to dev)**" list ends with the multi-line "Backlog hygiene" bullet whose last line is exactly:
```
  `memory-evolution.md` for the per-row evidence
```
Insert immediately after that line:
```

**2026-09-02**
- **G109 phase 1** graph physics (PR #TBD) — alpha-scaled hub gravity, no reheat on release,
  `velocityDecay` 0.2 / `alphaMin` 0.001, per-isolate phyllotaxis slots, speed clamp; headless
  physics bench + test under `Tests/graph/`; numbers in the G109 row
```

(b) In "## 🔄 In progress", replace the G109 row (line 197) exactly:
```
| **G109 graph physics** | **Research run in flight** (2026-09-01 evening): inventory of `graph.js` physics → five candidates (fix d3-force in place, Obsidian/Pixi, cosmograph, sigma+graphology/ForceAtlas2, ngraph/d3-force-3d) → engineer/user/skeptic judges → decision memo with a one-day phase 1 | Read the memo, rule, implement phase 1 in a worktree, fold the ruling into the G109 row |
```
with:
```
| **G109 graph physics** | **Phase 1 in PR #TBD** (2026-09-02): ruling = keep d3-force, fix `graph.js`; three commits + a committed bench, numbers in the row. Phases 2–3 and the Swift `WKWebView`-rebuild track are open | Merge after an independent re-run; live-bank visual check with Rodrigo; then the Swift track, then phase 2 |
```

(c) In "### Wave A", replace item 1 exactly:
```
1. **G109 🔴** graph physics — deceleration invisible (velocityDecay 0.45 + alphaMin 0.05 swallow
   the seeded throw) and zero-degree nodes fly to a ring now that the cold-paint fix renders them;
   *research run in flight* (see In progress) — S/M to decide, M to port
```
with:
```
1. **G109 phases 2–3 + Swift track** — phase 1 shipped (see In progress). Next: the Swift track
   (`ContentView.swift:137-139` rebuilds the `WKWebView` per tab switch — the "explosion on
   return"; keep one alive, reset `isGraphReady` on teardown) — S; phase 2 (own the rAF loop with a
   physical settle criterion, `__cicadaPerf.report()`, live-bank tuning pass) — S/M; phase 3
   (isolates out of the simulation, tick 6.7 → 4.5 ms measured) — S
```

(d) In "## 🩹 Known-broken", replace exactly:
```
- Graph physics: throw deceleration invisible, orphan nodes ring *(G109 — Wave A #1, in research)*
```
with:
```
- Graph re-lays out on every return to the Graph tab: `ContentView` rebuilds the `WKWebView` per
  tab switch *(G109 Swift track — Wave A #1; the physics half shipped in phase 1)*
```

- [ ] **Step 5: Verify the docs edits landed and nothing else moved**

```sh
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109 && git diff --stat && for f in CLAUDE.md docs/goals/memory-evolution.md docs/goals/TODO.md; do printf '%s %s\n' "$f" "$(grep -o 'PR #TBD' "$f" | wc -l | tr -d ' ')"; done && grep -n "^| G109 |" docs/goals/memory-evolution.md | tail -c 80
```
Expected: exactly three files in the stat (`CLAUDE.md`, `docs/goals/memory-evolution.md`, `docs/goals/TODO.md`); `CLAUDE.md 0`, `docs/goals/memory-evolution.md 2`, `docs/goals/TODO.md 5` (occurrences, not lines — the G109 row is ONE line holding both of its `PR #TBD`s, which is why `grep -c` would say 1 there); the last 80 bytes of the row end `phases 2–3 + Swift track open** |`.

- [ ] **Step 6: Commit**

```sh
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109 && git add CLAUDE.md docs/goals/memory-evolution.md docs/goals/TODO.md && git commit -m "$(cat <<'EOF'
docs(goals): G109 phase 1 shipped — ruling, measured numbers, handoff

CLAUDE.md's "Why d3-force" carries the ruling (keep d3-force, fix graph.js; flip
trigger p95 > 16.7 ms on the live bank after phases 1-2 or > ~10k nodes) and the
two rules it produced (alpha-scale every custom force; never bump alpha on
release). The G109 row records the ruling, the three bugs, the before/after bench
numbers, the superseded memo values, and what is still open (phase 2, phase 3,
the Swift WKWebView-rebuild track). TODO.md moves G109 to Shipped (phase 1),
rewrites Wave A #1 for the remaining tracks, and refreshes the handoff header.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

## Verification summary

Run after Task 4, from a clean state, before handing the branch back:

```sh
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109 && git status --porcelain -uall | grep -v '^?? api/.venv' ; git log --oneline dev..HEAD
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109 && node app/CicadaApp/Tests/graph/graph-physics.test.js | tail -1 && for t in graph-delta graph-drag-velocity graph-logo graph-mindegree-default; do node app/CicadaApp/Tests/graph/$t.test.js | tail -1; done && node app/CicadaApp/Tests/graph/graph-physics.bench.js | tail -30
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g109/app/CicadaApp && swift test 2>&1 | tail -20
```
Expected: the status shows nothing (`api/.venv` is gitignored so the `grep -v` is only a belt-and-braces), the plan commit plus four commits on top of `b690b66`, five "passed" lines, the Task-3 table, `swift test` with 0 failures.

**Before → after, in one table** (small 300 / medium 1500 / dense 1500-node synthetic; all measured through `graph.js`'s real `startSimulation` and drag handlers; `ms/tick` on an M-series Mac):

| Metric | Before (`b690b66`) | After phase 1 | Gate |
|---|---|---|---|
| KE/node at tick 400 | 13 / 20 / 23 (plateau) | 4e-16 / 4e-6 / 4e-5 | < 1e-1 |
| fastest node at tick 400 (wu/tick) | 5.0 / 11 / 11.8 | 0 / 0.01 / 0.02 | < 0.3 |
| flick from rest: coast ticks / wu | 0 / 0 · 1 / 1 · 0 / 0 | 12 / 63 · 13 / 99 · 13 / 100 | ≥ 10 ticks, ≥ 60 wu (≥ 90 on 1500) |
| drag-throw via handlers: coast ticks | 0 / 0 / 0 | 4 / 4 / 3 | ≥ 2 |
| other nodes' displacement, 60 ticks after release (wu) | 979 / 1,194 / 1,275 | 1.8 / 8.8 / 28 | < 5 / 15 / 40 |
| isolate max ÷ core p90 (1500-node) | 1.05 / 1.04 (unsettled) → 2.02 / 2.03 once settled (Task 2) | 1.31 / 1.28 | ≤ 1.35 |
| isolate max ÷ farthest connected node | — → 1.42 / 1.45 / 1.59 (Task 2) | 1.06 / 0.82 / 0.93 | ≤ 1.1 |
| core median (wu) | 1,674 / 1,997 / 2,109 (blown out) → 254 / 470 / 484 (Task 2) | 259 / 477 / 500 | ±10 % of Task 2 |
| ms per tick | 0.67 / 6.7 / 6.9 | 0.63 / 6.4 / 6.8 | informational |

## Deferred, deliberately (not in this branch)

- **Phase 2** — own the rAF loop (`simulation.stop()` after construction; `scheduleRedraw` ticks and draws; settle on max speed < 0.3 wu/tick for 10 frames, AND-ed with — not OR-ed with — the alpha floor, per critic gap 9; 600-tick cap), `window.__cicadaPerf` (debug-only global; numbers only, never ids or labels), then the live-bank tuning pass. Note critic gap 8: tick-every-other-frame halves the throw's on-screen speed unless the seed is scaled by the real tick interval (`SIM_TICK_MS`, `:224`).
- **Phase 3** — exclude isolates from the simulation (fixed slot positions, `pickNode` fallback scan); makes containment a guarantee and drops tick cost 6.7 → 4.5 ms (measured in the research run).
- **Swift track** — `ContentView.swift:137-139` rebuilds `GraphContainerView`'s `WKWebView` on every tab switch; keep one alive, reset `isGraphReady` on teardown. This, not physics, is "explosion on return".
- **Live-bank measurement** — no in-app tick/draw number exists yet; phase 2's `__cicadaPerf` is the instrument, and the visual check at fit-zoom needs Rodrigo at the machine (the bank holds real people).
