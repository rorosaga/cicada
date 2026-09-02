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
