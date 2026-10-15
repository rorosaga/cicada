#!/usr/bin/env node
//
// G109 look pass (2026-10-15) — the owner: "Right now it looks like a weird circle. Can you look at pictures of an
// Obsidian vault and make it look different?" The regression net for the look at rest, on a synthetic with the shape of
// the owner's bank as measured that day (graph-bank-shape.js `bankShaped1015`: 4,544 nodes, 41,570 links over 9,046
// pairs, a 3,529-node giant, 984 isolates of which 846 saved links; no names), through graph.js's real entry points and
// the real bundled d3, at the fit-to-view zoom the app opens on. Run it with:
//
//     node app/CicadaApp/Tests/graph/graph-look.test.js
//
// Every threshold was set from a measured value with margin; next to each are the values on two seeds and on dev
// before the pass (49ffcad8). ~6 s.
"use strict";

const harness = require("./graph-physics-harness.js");
const { coldOpen, bankShaped1015, lookMetrics, components, shapeSummary } = require("./graph-bank-shape.js");

let failures = 0;
const check = (label, cond, actual) => {
    console.log((cond ? "PASS " : "FAIL ") + label + (actual === undefined ? "" : `  [${actual}]`));
    if (!cond) failures += 1;
};

{
    const s = shapeSummary(bankShaped1015());
    check("synthetic: 4,544 nodes, 41,570 links, 996 components, giant 3,529, 984 isolates",
          s.nodes === 4544 && s.links === 41570 && s.components === 996 && s.giant === 3529 && s.singletons === 984,
          JSON.stringify(s));
}

let kept = null;
for (const seed of [7, 3]) {
    const g = bankShaped1015(seed);
    const run = coldOpen(harness, seed, { graph: g });
    if (seed === 7) kept = run;
    const m = run.metrics;
    const L = lookMetrics(run.h.get);
    const tag = `seed ${seed}:`;

    // ---- small dots, the owner's page large but not dominant ----
    // measured 3.5 wu (before 14.4)
    check(`${tag} the median node is a small dot (<= 5 wu)`, L.radiusMedian <= 5, L.radiusMedian);
    // measured 6.7 (before 14.3: a 206 wu disc over the centre)
    check(`${tag} the largest node is 4-8x the median`, L.radiusMaxOverMedian >= 4 && L.radiusMaxOverMedian <= 8, L.radiusMaxOverMedian);
    // ---- negative space ----
    // measured 0.013 (before 0.25-0.26)
    check(`${tag} discs cover <= 4 % of the fitted view`, L.coverage <= 0.04, L.coverage);
    // measured 0 % (before 51-52 %)
    check(`${tag} <= 5 % of nodes overlap another disc`, m.overlapPct <= 5, m.overlapPct);
    // ---- the halo: a loose, irregular scatter, not ruled rows ----
    // measured 0.49-0.50 (before 0.09-0.15: rows of evenly spaced beads)
    check(`${tag} halo spacing is irregular (nearest-neighbour CV >= 0.35)`, L.haloNnCv >= 0.35, L.haloNnCv);
    // measured 1.03-1.04 (before 1.67-1.75)
    check(`${tag} halo is a random-like scatter (Clark-Evans <= 1.3)`, L.haloClarkEvans <= 1.3, L.haloClarkEvans);
    // measured 0.08-0.09 of the body's radius
    check(`${tag} a clear gap between body and halo (3-25 % of the body's radius)`, L.haloGap >= 0.03 && L.haloGap <= 0.25, L.haloGap);
    // measured 358°, hull 0.87-0.88, rim spread 1.12-1.14, farthest 1.49-1.50 giant radii
    check(`${tag} the halo wraps the body (coverage >= 330°)`, m.coverageDeg >= 330, m.coverageDeg);
    check(`${tag} the whole is roughly round (hull >= 0.8, rim spread <= 1.3)`, m.hullFill >= 0.8 && m.rimSpread <= 1.3, `${m.hullFill}, ${m.rimSpread}`);
    check(`${tag} nothing flies away (farthest node <= 1.7 giant radii)`, m.farthestR <= 1.7, m.farthestR);
    // ---- the owner's page sits in the middle of the body ----
    const vis = run.h.get("visibleNodes");
    const giant = new Set(components(g)[0]);
    const body = vis.filter(n => giant.has(n.id));
    const cx = body.reduce((a, n) => a + n.x, 0) / body.length, cy = body.reduce((a, n) => a + n.y, 0) / body.length;
    const owner = vis.find(n => n.id === "owner");
    const off = Math.hypot(owner.x - cx, owner.y - cy) / m.R95;
    // measured 0.12-0.16 (0.6 with a weak pull, ~1.0 with its charge growing with its neighbours)
    check(`${tag} the owner's page sits near the middle (<= 0.25 giant radii off)`, off <= 0.25, off.toFixed(2));
    // ---- it still settles (#285/#287) ----
    // measured 111-113 steps, KE 0.018-0.02, vmax 0.54-0.58, 16.3-16.5 ms p50 (before 131 steps, 20 ms)
    check(`${tag} the timer stops within 150 steps, at rest`, m.stopTick !== null && m.stopTick <= 150 && m.keAtStop < 0.05 && m.vmaxAtStop < 1.5,
          `${m.stopTick} steps, KE ${m.keAtStop}, vmax ${m.vmaxAtStop}`);
    check(`${tag} once stopped, the redraw loop asks for no more frames`, m.framesAfterStop === 0, m.framesAfterStop);
    check(`${tag} one step costs < 75 ms (p50)`, m.msTickP50 < 75, m.msTickP50);
}

// ---- drawing: one hairline per pair, no hub rings, names fade in with zoom ----
{
    const { h, g } = kept;
    const pairs = new Set(g.links.map(l => [l.source, l.target].sort().join("\u0000")));
    check("a pair joined by several claims draws one line", h.get("drawLinks.length") === pairs.size, `${h.get("drawLinks.length")} lines for ${pairs.size} pairs, ${g.links.length} links`);
    // count what draw() writes and strokes at a given zoom
    h.get(`(() => { const inner = ctx; globalThis.__texts = []; globalThis.__arcs = 0;
        ctx = new Proxy(inner, { get: (t, k) => k === "fillText" ? (s) => __texts.push(s)
                                       : k === "arc" ? () => { __arcs += 1; } : t[k], set: () => true }); })()`);
    const frameAt = (k) => {
        h.get("globalThis.__texts = []; globalThis.__arcs = 0");
        if (k === "fit") h.get("transform = transformForNodes(visibleNodes, 60)");
        else h.get(`transform = d3.zoomIdentity.translate(width / 2, height / 2).scale(${k})`);
        h.get("draw()");
        return { texts: h.get("__texts.length"), arcs: h.get("__arcs"), names: h.get("__texts.slice()") };
    };
    const fit = frameAt("fit");
    // one arc per node, plus a pulse ring per pending node — no second ring on a hub
    const pending = h.get("visibleNodes.filter(nodeHasPending).length");
    check("at rest every node draws one disc, and only a waiting question adds a ring (no hub rings)",
          fit.arcs === h.get("visibleNodes.length") + pending, `${fit.arcs} arcs, ${h.get("visibleNodes.length")} nodes, ${pending} waiting`);
    check("at the fit zoom only a page as big as the owner's is named", fit.texts <= 3 && fit.names.includes("owner"), JSON.stringify(fit.names));
    const near = frameAt(2);
    check("zoomed in, names appear — within the label budget", near.texts > 20 && near.texts <= h.get("LABEL_BUDGET"), near.texts);
    check("the fade: a dot at the threshold is unnamed, one well past it fully named",
          h.get("labelFade(LABEL_FADE_FROM)") === 0 && h.get("labelFade(LABEL_FADE_TO)") === 1 && Math.abs(h.get("labelFade((LABEL_FADE_FROM + LABEL_FADE_TO) / 2)") - 0.5) < 1e-9);
    // the pending pulse hugs its dot: at most ~6 px beyond it on screen
    check("the pending ring stays within 6 px of its dot", h.get("PULSE_RING_FROM + PULSE_RING_TRAVEL") <= 6, h.get("PULSE_RING_FROM + PULSE_RING_TRAVEL"));
}

// ---- size counts distinct neighbours, not parallel claims ----
{
    const h = harness.loadGraph();
    const nodes = [{ id: "a", name: "a", type: "concept", status: "active", confidence: 0.5 },
                   { id: "b", name: "b", type: "concept", status: "active", confidence: 0.5 },
                   { id: "c", name: "c", type: "concept", status: "active", confidence: 0.5, degree: 999 }];
    const links = [];
    for (let i = 0; i < 40; i++) links.push({ source: "a", target: "b" });
    links.push({ source: "c", target: "a" });
    h.call("updateGraph", { nodes, links });
    h.get("simulation").stop();
    const r = (id) => h.get(`nodeRadius(nodes.find(n => n.id === "${id}"))`);
    check("forty claims between two pages size them as one neighbour", Math.abs(r("b") - (2.2 + 0.4 + 0.45)) < 1e-9, r("b").toFixed(2));
    check("a server degree counting parallels does not size a node", Math.abs(r("c") - r("b")) < 1e-9, `${r("c").toFixed(2)} vs ${r("b").toFixed(2)}`);
}

// ---- the halo keeps each satellite's place across pushes ----
{
    const h = harness.loadGraph();
    const g = bankShaped1015(5);
    h.call("updateGraph", g);
    h.get("simulation").stop();
    const place = () => new Map([...h.get("satelliteOf")].map(([id, u]) => [id, `${u.angle}:${u.depth}`]));
    const before = place();
    h.call("updateGraphDelta", { added: [{ id: "a-sorts-first", name: "a", type: "media", status: "active", confidence: 0.5 }], updated: [], removed: ["iso1"] });
    h.get("simulation").stop();
    const after = place();
    let moved = 0;
    for (const [id, p] of before) if (id !== "iso1" && after.get(id) !== p) moved += 1;
    check("a newcomer and a removal move no other satellite's place in the halo", moved === 0 && after.has("a-sorts-first"), moved);
}

console.log("");
if (failures) {
    console.log(`${failures} graph look check(s) FAILED.`);
    process.exit(1);
}
console.log("All graph look checks passed.");
