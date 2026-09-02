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
//   deltaNoop*       a delta with NO change pushed onto the settled layout (the app's most
//                    frequent reheat, every SSE version tick after a Sleep): ticks until d3's
//                    timer stops again, and how far the connected core / the isolates moved by
//                    then (mean, max). The core residual is the phase-2 delta-reheat lever.
//
// Numbers only; the synthetic has no names. Deterministic except msPerTick.

const { GRAPH_JS, SIZES, runScenario, runDeltaNoop } = require("./graph-physics-harness.js");

const COLUMNS = [
    "size", "n", "links", "msPerTick", "ke400", "maxSpeed400", "ticksToAlphaMin", "keAtStop",
    "isoN", "isoMedian", "isoMax", "coreMedian", "coreP90", "coreMax", "ratioMaxToP90", "ratioMedToP90",
    "freeAlphaAtRelease", "freeCoastTicks", "freeCoastDist", "freeTicksToStop",
    "holdAlphaTarget", "holdKE", "seededSpeed", "alphaAtRelease",
    "throwCoastTicks", "throwCoastDist", "throwTicksToStop", "throwTimerStopTick", "otherDisp60",
    "deltaNoopStopTick", "deltaNoopCoreMean", "deltaNoopCoreMax", "deltaNoopIsoMean", "deltaNoopIsoMax",
];

console.log("graph.js:", GRAPH_JS);
const rows = Object.keys(SIZES).map(size => Object.assign(runScenario(size), runDeltaNoop(size)));
for (const r of rows) console.log(JSON.stringify(r));
console.log("");
const w = Math.max(...COLUMNS.map(c => c.length));
for (const c of COLUMNS) {
    console.log(c.padEnd(w), rows.map(r => String(r[c] ?? "")).map(v => v.padStart(10)).join(""));
}
