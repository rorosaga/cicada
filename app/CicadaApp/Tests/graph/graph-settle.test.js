#!/usr/bin/env node
//
// G109 (2026-10-14) — the owner's graph "never stops moving until it freezes", a star of small nodes sits far out on
// long links, and two tiny nodes rest in a far corner. This is the regression net for the fix, on a synthetic with
// the owner's bank's SHAPE (graph-bank-shape.js: 3,698 nodes, 41,570 links, one 3,529-node component, a 2,092-degree
// page, stars of 226 / 44 / 23 … leaves, 138 isolates and 11 small components; no names), through graph.js's real
// entry points and the real bundled d3, stepped exactly as d3's own timer steps it. Run it with:
//
//     node app/CicadaApp/Tests/graph/graph-settle.test.js
//
// Every threshold was set from a measured value with margin; the numbers next to each are the measured value on three
// seeds and, where it exists, the value on the layout this replaced (dev at d20bfb25). graph-settle.bench.js prints
// them. ~10 s: three cold opens of a 3,700-node graph plus the event checks.
"use strict";

const harness = require("./graph-physics-harness.js");
const { coldOpen, bankShaped, components, SWIFT_DEFAULT_FILTER, LIVE_ISOLATES_2026_10_14 } = require("./graph-bank-shape.js");

let failures = 0;
const check = (label, cond, actual) => {
    console.log((cond ? "PASS " : "FAIL ") + label + (actual === undefined ? "" : `  [${actual}]`));
    if (!cond) failures += 1;
};

// ---- 1. a cold open settles, stops, and stays organised (three seeds) ----
let settled = null;
for (const seed of [7, 3, 11]) {
    const run = coldOpen(harness, seed);
    const m = run.metrics;
    if (seed === 7) settled = run;
    const tag = `seed ${seed}:`;
    // measured 129 / 124 / 133 (before: 135, the alpha cut-off, still moving)
    check(`${tag} the d3 timer stops within 150 steps`, m.stopTick !== null && m.stopTick <= 150, m.stopTick);
    // measured 0.014 / 0.017 / 0.009 (before: 130 / 120 / 120 — frozen mid-motion)
    check(`${tag} it is still when it stops (KE/node < 0.05)`, m.keAtStop < 0.05, m.keAtStop);
    // measured 0.62 / 0.66 / 0.95 wu/tick (before: 48, the speed clamp)
    check(`${tag} the fastest node at the stop moves < 1.5 wu/tick`, m.vmaxAtStop < 1.5, m.vmaxAtStop);
    // measured 101 / 97 / 99 (before: never before the stop)
    check(`${tag} 95 % of nodes move < 1 wu/tick by step 115`, m.stillTick !== null && m.stillTick <= 115, m.stillTick);
    check(`${tag} once stopped, the redraw loop asks for no more frames`, m.framesAfterStop === 0, m.framesAfterStop);
    // measured 18.7-19.4 ms on the author's machine (before: 25-27). A coarse guard, not a benchmark.
    check(`${tag} one step costs < 75 ms (p50)`, m.msTickP50 < 75, m.msTickP50);
    // measured 1,073-1,081 wu = 18.2 sqrt(n) (before: 1,015-1,023)
    check(`${tag} the giant's p95 radius is bounded by its size (<= 22 sqrt(n))`, m.R95 <= 22 * Math.sqrt(m.giantN), `${m.R95} vs ${Math.round(22 * Math.sqrt(m.giantN))}`);
    // measured 1.28 / 1.28 / 1.32 R95 (before: 1.37 / 1.36 / 1.36)
    check(`${tag} no node sits beyond 1.4 giant radii`, m.farthestR <= 1.4, m.farthestR);
    // measured 1.06 / 1.07 / 1.10 — the band sits outside the body (before: 0.97, pushed against and into its edge)
    check(`${tag} every node outside the giant sits in a band past its p95 radius`, m.outsideMinR >= 1.0 && m.outsideMaxR <= 1.4, `${m.outsideMinR}-${m.outsideMaxR}`);
    // measured 154 / 174 / 176 wu median, 279 / 277 / 309 max (before: 933 / 914 / 921, max 1,076-1,207)
    check(`${tag} the 2,092-degree page's 226 leaves sit close (median <= 250 wu)`, m.ownerLeafMed <= 250, m.ownerLeafMed);
    check(`${tag} ... none past 450 wu`, m.ownerLeafMax <= 450, m.ownerLeafMax);
    // measured 99 / 139 / 109 wu median, 164 / 199 / 165 max (before: 800 / 881 / 381, max 1,400 / 1,273 / 1,020)
    check(`${tag} the 44-leaf star's leaves sit close (median <= 200 wu)`, m.star44LeafMed <= 200, m.star44LeafMed);
    check(`${tag} ... none past 300 wu`, m.star44LeafMax <= 300, m.star44LeafMax);
    // measured 4.69 / 4.91 / 4.61 (before: 2.39 / 2.47 / 2.52)
    check(`${tag} planted communities read as clusters (separation >= 4)`, m.commSep >= 4, m.commSep);
    // measured 43 / 37 / 40 % (before: 48 / 49 / 48 %)
    check(`${tag} no more overlapping discs than before (<= 50 %)`, m.overlapPct <= 50, m.overlapPct);
    // the ring (2026-10-14): measured coverage 342°, hull fill 0.95, rim spread 1.06
    check(`${tag} the satellites wrap the body (coverage >= 330°)`, m.coverageDeg >= 330, m.coverageDeg);
    check(`${tag} the layout is round (hull >= 0.85 of its circle, rim spread <= 1.15)`, m.hullFill >= 0.85 && m.rimSpread <= 1.15, `${m.hullFill}, ${m.rimSpread}`);
}

// ---- 1b. the live graph after #285: 1,000 isolates, 86 % of one type (bookmarks just imported) ----
// Owner, 2026-10-14: "would be nice if it resembled a circle in the end". #285 packed each type in its own 30° sector,
// so 860 isolates of one type became a slab: coverage 302°, hull fill 0.40, rim spread 2.07, farthest node 2.05 R95.
for (const seed of [7, 3]) {
    const { metrics: m } = coldOpen(harness, seed, { isolates: LIVE_ISOLATES_2026_10_14 });
    const tag = `live mix, seed ${seed}:`;
    // measured 128-133 steps, KE 0.014-0.016, vmax 0.8-1.0
    check(`${tag} the timer stops within 150 steps, at rest`, m.stopTick !== null && m.stopTick <= 150 && m.keAtStop < 0.05 && m.vmaxAtStop < 1.5,
          `${m.stopTick} steps, KE ${m.keAtStop}, vmax ${m.vmaxAtStop}`);
    // measured 357° (before: 302°)
    check(`${tag} the satellites wrap the body (coverage >= 330°)`, m.coverageDeg >= 330, m.coverageDeg);
    // measured 0.95-0.97 (before: 0.40)
    check(`${tag} the hull fills >= 0.85 of the circle through its farthest node`, m.hullFill >= 0.85, m.hullFill);
    // measured 1.04-1.05 (before: 2.07) — a slab or a line on one side shows here
    check(`${tag} no slab: the farthest node per 15° bin varies <= 1.15x`, m.rimSpread <= 1.15, m.rimSpread);
    // measured 1.24-1.25 (before: 2.05)
    check(`${tag} no node beyond 1.4 giant radii`, m.farthestR <= 1.4, m.farthestR);
    // measured 104-105 / 162-170 wu
    check(`${tag} the 44-leaf star stays tight (median <= 200, max <= 300 wu)`, m.star44LeafMed <= 200 && m.star44LeafMax <= 300, `${m.star44LeafMed} / ${m.star44LeafMax}`);
}

// ---- 2. structure: one spring per pair, every small component in the band ----
{
    const { h, g } = settled;
    const simLinks = h.get("simLinks");
    const pairs = new Set(g.links.map(l => [l.source, l.target].sort().join("\u0000")));
    check("the simulation has one link per connected pair (parallel links still draw)", simLinks.length === pairs.size, `${simLinks.length} for ${g.links.length} links`);
    const comps = components(g);
    const satelliteOf = h.get("satelliteOf");
    const small = comps.slice(1).flat();
    check("every node of every component but the giant is a satellite", small.every(id => satelliteOf.has(id)), `${small.filter(id => satelliteOf.has(id)).length}/${small.length}`);
    check("no node of the giant is a satellite", comps[0].every(id => !satelliteOf.has(id)));
    let worst = 0, offSum = 0;
    for (const id of small) {
        const u = satelliteOf.get(id);
        const n = h.get("visibleNodes").find(x => x.id === id);
        const off = Math.hypot(n.x - u.x, n.y - u.y);
        worst = Math.max(worst, off / u.footprint);
        offSum += off;
    }
    // measured 21 wu mean, 2.0 footprints worst (an isolate nudged by a body page past the body's p99 radius)
    check("satellites sit at their slots (mean offset <= 30 wu)", offSum / small.length <= 30, (offSum / small.length).toFixed(1));
    check("... none more than 2.5 footprints off", worst <= 2.5, worst.toFixed(2));
    const charge = h.get("simulation").force("charge");
    check("the bodies' charge does not act on satellites", typeof charge.initialize === "function" && h.get("bodyNodes").every(n => !satelliteOf.has(n.id)));
    harness.drawCounters.stroke = 0;
    h.get("transform = d3.zoomIdentity");
    h.get("draw()");
    // measured 18 (before: 41,586 — one per link)
    check("one frame at zoom 1 strokes a handful of paths, not one per link", harness.drawCounters.stroke <= 64, harness.drawCounters.stroke);
}

// ---- 3. nothing reheats forever: deltas, hover, hold, filters, visibility on the settled graph ----
{
    const { h, g } = settled;
    const sim = () => h.get("simulation");
    const stopped = () => sim().alpha() < sim().alphaMin();
    const snapshot = () => new Map(h.get("visibleNodes").map(n => [n.id, [n.x, n.y]]));
    const moved = (before, ids) => {
        let max = 0, sum = 0, cnt = 0;
        for (const n of h.get("visibleNodes")) {
            const b = before.get(n.id);
            if (!b || (ids && !ids.has(n.id))) continue;
            const d = Math.hypot(n.x - b[0], n.y - b[1]);
            max = Math.max(max, d); sum += d; cnt += 1;
        }
        return { max, mean: cnt ? sum / cnt : 0 };
    };
    const framesToIdle = () => { let f = 0; while (h.pumpFrame() > 0 && f < 2000) f += 1; return f; };

    // (a) the app's most frequent push: an SSE version tick with no change, five times, each followed by the filter
    // Swift re-asserts. Nothing starts.
    let before = snapshot();
    for (let i = 0; i < 5; i++) {
        h.call("updateGraphDelta", { added: [], updated: [], removed: [] });
        h.call("applyFilters", SWIFT_DEFAULT_FILTER);
        sim().stop();
    }
    check("five no-op deltas start no layout", stopped(), sim().alpha());
    check("... and move nothing", moved(before).max === 0, moved(before).max);
    check("... and the redraw loop goes idle", framesToIdle() <= 1);

    // (b) hover across the canvas: a repaint, never a restart
    const hub = h.get("visibleNodes").find(n => n.id === "owner");
    for (let i = 0; i < 20; i++) h.sandbox.onMouseMove({ clientX: hub.x + i * 3, clientY: hub.y, buttons: 0 });
    check("hovering starts no layout", stopped(), sim().alpha());
    check("... and the redraw loop goes idle", framesToIdle() <= 1);

    // (c) a hold and a release on a page: the hold runs the simulation (alphaTarget 0.1), the release ends it
    before = snapshot();
    const leaf = h.get("visibleNodes").find(n => n.id === "sl0-3");
    h.clock.now = 10000;
    h.sandbox.onMouseDown({ clientX: leaf.x, clientY: leaf.y, stopImmediatePropagation: () => {} });
    sim().stop();
    for (let i = 0; i < 30; i++) h.step();
    check("a hold keeps the layout warm (alphaTarget 0.1)", sim().alphaTarget() === 0.1, sim().alphaTarget());
    h.clock.now += 600;
    h.sandbox.onMouseUp({});
    sim().stop();
    const afterRelease = h.runUntilStop(400);
    // measured 41 steps
    check("after the release the layout stops within 200 steps", afterRelease !== null && afterRelease <= 200, afterRelease);
    // measured 0 (before: 234 wu — the hold re-laid out the whole graph; 66 with only the settle fix)
    const others = new Set([...before.keys()].filter(id => id !== "sl0-3" && id !== "star0"));
    check("... having moved nothing but the page and its neighbour", moved(before, others).max === 0, moved(before, others).max.toFixed(2));
    check("... and the redraw loop goes idle", framesToIdle() <= 1);

    // (d) a filter change re-lays out, and stops
    h.call("applyFilters", { ...SWIFT_DEFAULT_FILTER, minDegree: 1 });
    sim().stop();
    let t = h.runUntilStop(400);
    // measured 112 steps
    check("hiding the isolates (min degree 1) re-lays out and stops within 150 steps", t !== null && t <= 150, t);
    h.call("applyFilters", SWIFT_DEFAULT_FILTER);
    sim().stop();
    t = h.runUntilStop(400);
    check("showing them again stops within 150 steps", t !== null && t <= 150, t);
    check("... and the redraw loop goes idle", framesToIdle() <= 1);

    // (e) a delta that brings an isolate and a new leaf of the owner: only they move, briefly
    before = snapshot();
    const owned = new Set(before.keys());
    h.call("updateGraphDelta", {
        added: [{ id: "new-isolate", name: "n", type: "person", status: "active", confidence: 0.5 },
                { id: "new-leaf", name: "n", type: "concept", status: "active", confidence: 0.5 }],
        updated: [], removed: [],
        links: [...g.links, { source: "owner", target: "new-leaf" }],
    });
    sim().stop();
    t = h.runUntilStop(400);
    // measured 135 steps (alpha 0.3 to alphaMin; two nodes, so ~0.1 ms a step)
    check("a delta with two newcomers stops within 150 steps", t !== null && t <= 150, t);
    check("... and moves none of the settled nodes", moved(before, owned).max === 0, moved(before, owned).max);
    const unit = h.get("satelliteOf").get("new-isolate");
    const iso = h.get("visibleNodes").find(n => n.id === "new-isolate");
    // measured 26 wu, about one footprint: its held neighbours in the band are not exactly on their own slots
    check("the new isolate rests at its band slot (< 2 footprints)", unit && Math.hypot(iso.x - unit.x, iso.y - unit.y) < 2 * unit.footprint,
          unit && Math.hypot(iso.x - unit.x, iso.y - unit.y).toFixed(1));
    const newLeaf = h.get("visibleNodes").find(n => n.id === "new-leaf");
    const ownerNode = h.get("visibleNodes").find(n => n.id === "owner");
    // measured 113 wu
    check("the new leaf rests near its page (< 450 wu)", Math.hypot(newLeaf.x - ownerNode.x, newLeaf.y - ownerNode.y) < 450,
          Math.hypot(newLeaf.x - ownerNode.x, newLeaf.y - ownerNode.y).toFixed(0));

    // (f) hidden and shown again: no reheat
    h.call("setGraphActive", false);
    h.call("setGraphActive", true);
    check("hiding and showing the graph starts no layout", stopped(), sim().alpha());
    check("... and the redraw loop goes idle", framesToIdle() <= 1);
}

// ---- 4. the settle check never ends a hold or a throw early ----
{
    const { h } = coldOpen(harness, 5);
    const node = h.get("visibleNodes").find(n => n.id === "sl1-2");
    h.clock.now = 20000;
    h.sandbox.onMouseDown({ clientX: node.x, clientY: node.y, stopImmediatePropagation: () => {} });
    h.get("simulation").stop();
    let held = 0;
    for (let i = 0; i < 60; i++) if (h.step()) held += 1;
    check("a hold with the pointer still keeps the timer running", held === 60, held);
    h.clock.now += 600;
    h.sandbox.onMouseUp({});
    h.get("simulation").stop();
    node.vx = 20; node.vy = 0;   // a throw's seeded velocity
    let coast = 0;
    for (let i = 0; i < 10; i++) { if (!h.step()) break; coast += 1; }
    check("a thrown node keeps the timer running while it coasts", coast === 10, coast);
}

// ---- 5. a small graph's cold open fits the view when it ends, never later (review B1) ----
for (const n of [12, 40]) {
    const h = harness.loadGraph({ frames: true });
    const nodes = [], links = [];
    for (let i = 0; i < n; i++) {
        nodes.push({ id: "s" + i, name: "s", type: ["person", "concept", "project"][i % 3], status: "active", confidence: 0.5 });
        if (i > 0) links.push({ source: "s" + Math.floor((i - 1) / 2), target: "s" + i });   // a binary tree
    }
    h.call("updateGraph", { nodes, links });
    h.get("simulation").stop();
    // fitGraph needs d3-zoom on a real canvas; count its calls instead.
    h.get("fitGraph = function () { globalThis.__fits = (globalThis.__fits || 0) + 1; }");
    let steps = 0;
    while (steps < 1000 && h.step()) steps += 1;
    const fits = () => h.get("globalThis.__fits || 0");
    // measured 71 / 83 steps: the settle check ends it before INITIAL_FIT_TICKS (90), the case this guards
    check(`${n} nodes: the cold layout ends before the fit's 90 ticks`, steps + 1 < 90, steps + 1);
    check(`${n} nodes: the view is fitted exactly once by the layout's end`, fits() === 1, fits());
    check(`${n} nodes: no fit is left armed`, h.get("initialFitTicksLeft") === -1, h.get("initialFitTicksLeft"));
    const fitsBeforeGrab = fits();
    const node = h.get("visibleNodes")[0];
    h.clock.now = 30000;
    h.sandbox.onMouseDown({ clientX: node.x, clientY: node.y, stopImmediatePropagation: () => {} });
    h.get("simulation").stop();
    for (let i = 0; i < 30; i++) h.step();
    h.sandbox.onMouseUp({});
    check(`${n} nodes: grabbing a node afterwards fits nothing`, fits() === fitsBeforeGrab, `${fitsBeforeGrab} -> ${fits()}`);
}

{
    // The synthetic's shape is the brief's (a guard on the generator, not on graph.js).
    const { shapeSummary } = require("./graph-bank-shape.js");
    const s = shapeSummary(bankShaped());
    check("synthetic: 3,698 nodes, ~41,570 links, 150 components, giant 3,529, 138 singletons, 6 pairs",
          s.nodes === 3698 && Math.abs(s.links - 41570) <= 30 && s.components === 150 && s.giant === 3529 && s.singletons === 138 && s.pairs === 6,
          JSON.stringify(s));
}

console.log("");
if (failures) {
    console.log(`${failures} graph settle check(s) FAILED.`);
    process.exit(1);
}
console.log("All graph settle checks passed.");
