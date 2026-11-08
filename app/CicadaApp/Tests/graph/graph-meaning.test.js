#!/usr/bin/env node
//
// ROR-134 — graph.js's "closeness by meaning" mode, under the REAL d3 (graph-physics-harness.js):
//
//     node app/CicadaApp/Tests/graph/graph-meaning.test.js
//
// Pairs from the backend turn the layout toward the subject; they are never links (ruling 56), the mode is off until
// the switch, the force is alpha-scaled (the layout still goes still, G109), and the result does not depend on chance.

const { loadGraph, synthetic, kePerNode } = require("./graph-physics-harness.js");

let failures = 0;
const check = (label, cond, actual) => {
    console.log((cond ? "PASS " : "FAIL ") + label + (actual === undefined ? "" : `  [${actual}]`));
    if (!cond) failures += 1;
};

const SIZE = { n: 300, isolates: 100, hubs: 6, facets: 20, extraLinksPerNode: 3 };

// Body pairs far apart in the link graph (c_i <-> c_{i+100}) and halo pairs (unlinked i_j <-> i_{j+40}).
function pairsFor(g) {
    const body = [], halo = [];
    for (let i = 0; i < 40; i++) body.push(["c" + i, "c" + (i + 100), 0.9]);
    for (let j = 0; j < 40; j++) halo.push(["i" + j, "i" + (j + 40), 0.9]);
    return { body, halo, all: [...body, ...halo] };
}

function run({ meaning }) {
    const h = loadGraph();
    const g = synthetic(SIZE);
    const p = pairsFor(g);
    h.call("updateGraph", g);
    h.get("simulation").stop();
    if (meaning) {
        h.call("setMeaningPairs", JSON.stringify({ pairs: p.all }));
        h.call("applyFilters", { byMeaning: true });
    }
    h.get("simulation").stop();
    h.disarmFit();
    const sim = h.get("simulation");
    for (let t = 0; t < 400; t++) sim.tick();
    const byId = new Map(h.get("visibleNodes").map(n => [n.id, n]));
    const dist = (pairs) => pairs.reduce((s, [a, b]) => s + Math.hypot(byId.get(a).x - byId.get(b).x, byId.get(a).y - byId.get(b).y), 0) / pairs.length;
    return { h, p, sim, byId, body: dist(p.body), halo: dist(p.halo), ke: kePerNode(h.get("visibleNodes")),
             xs: h.get("visibleNodes").map(n => n.x.toFixed(4)).join(","), drawn: h.get("drawLinks").length };
}

const off = run({ meaning: false });
const on = run({ meaning: true });
const again = run({ meaning: true });

check("off by default: no meaning pairs act without the switch", (() => {
    const h = loadGraph(); h.call("updateGraph", synthetic(SIZE)); h.get("simulation").stop();
    h.call("setMeaningPairs", JSON.stringify({ pairs: pairsFor().all }));
    return h.get("filters").byMeaning === false && h.get("meaningLinks").length === 0 && h.get("meaningHalo").size === 0;
})());
check("body pages of one subject end nearer (>= 25% closer)", on.body < off.body * 0.75, `${off.body.toFixed(0)} -> ${on.body.toFixed(0)}`);
check("unlinked (halo) pages of one subject end nearer (>= 25% closer)", on.halo < off.halo * 0.75, `${off.halo.toFixed(0)} -> ${on.halo.toFixed(0)}`);
check("no edge is drawn or implied: same drawn links and sim links", on.drawn === off.drawn && on.h.get("simLinks").length === off.h.get("simLinks").length, `${off.drawn}/${on.drawn}`);
check("it still goes still: KE/node at tick 400 < 1e-1", on.ke < 1e-1, on.ke.toExponential(1));
check("deterministic: the same pairs give the same positions", on.xs === again.xs);
check("switching it off restores a layout without meaning links", (() => {
    on.h.call("applyFilters", { byMeaning: false });
    return on.h.get("meaningLinks").length === 0 && on.h.get("meaningHalo").size === 0;
})());
check("a re-layout keeps a halo page's place (angle carried, no jump back to its hash)", (() => {
    const h = loadGraph(); h.call("updateGraph", synthetic(SIZE)); h.get("simulation").stop();
    h.call("setMeaningPairs", JSON.stringify({ pairs: pairsFor().all })); h.call("applyFilters", { byMeaning: true });
    h.get("simulation").stop(); h.disarmFit();
    const sim = h.get("simulation");
    for (let t = 0; t < 300; t++) sim.tick();
    const before = new Map(h.get("satelliteUnits").map(u => [u.key, u.angle]));
    h.call("applyFilters", { minConfidence: 0.0 }); h.call("applyFilters", { byMeaning: true });
    h.get("simulation").stop();
    const moved = h.get("satelliteUnits").filter(u => before.has(u.key) && h.get("meaningHalo").has(u) && Math.abs(u.angle - before.get(u.key)) > 1e-9);
    return moved.length === 0;
})());

if (failures) { console.log(`\n${failures} FAILED`); process.exit(1); }
console.log("\nall passed");
