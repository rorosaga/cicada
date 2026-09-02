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

const { SIZES, loadGraph, synthetic, runScenario, runDeltaNoop } = require("./graph-physics-harness.js");

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

// The delta path (every SSE version tick after a Sleep): a delta with NO change on
// a settled layout must not re-lay the graph out. Measured core mean displacement
// 8.8 / 31 / 80 wu (max 49 / 173 / 573) — before phase 1: 1,289 / 1,480 / 1,723
// mean. The bound is a regression net for "the reheat re-lays out the graph", not
// a lock on the residual: the delta reheat value (0.3) and a collide lever are the
// phase-2 tuning, measured in-app (G109 row).
for (const size of Object.keys(SIZES)) {
    const d = runDeltaNoop(size);
    check(`${size}: a no-op delta moves the settled core < 200 wu mean`, d.deltaNoopCoreMean < 200, `${d.deltaNoopCoreMean} (max ${d.deltaNoopCoreMax})`);
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

console.log("");
if (failures) {
    console.log(`${failures} graph physics check(s) FAILED.`);
    process.exit(1);
}
console.log("All graph physics checks passed.");
