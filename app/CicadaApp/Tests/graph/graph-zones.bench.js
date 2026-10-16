#!/usr/bin/env node
//
// Item 6 (2026-10-08) — the owner's hypothesis: zones per entity type so nodes don't overlap. graph.js already pulls
// every node toward a per-type anchor (`typeClusterPositions`, forceX/forceY via `anchorStrength`, 0.04; d3 scales
// both by alpha), so the experiment is that strength. For each value, a cold layout of a 2,000-node synthetic (the
// owner's bank size, `ownerShaped`) through the REAL graph.js and d3:
//
//   ticks      ticks until d3's timer would stop (alpha < alphaMin)
//   ms/tick    one simulation.tick() (the only machine-dependent column)
//   overlap    node pairs whose discs (nodeRadius) intersect at rest, and the share of nodes in at least one
//   typeSep    mean distance between type centroids / mean distance of a node to its own type centroid (higher =
//              tighter, more separate zones)
//   spread     p90 distance from the origin (how much canvas the layout takes)
//
//     node app/CicadaApp/Tests/graph/graph-zones.bench.js
//
// Numbers only; placeholder ids.
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");

// 2,000 pages: 24 hubs, 40% of the connected pages in a hub (hub gravity owns them, type anchors do not), 60% free
// (the type anchors act on these), ~2.5 links per page, 400 isolates; one page linked to a third of the rest (the
// owner). Deterministic.
function ownerShaped() {
    let seed = 11;
    const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
    const types = ["person", "project", "company", "concept", "tool", "skill", "location", "media"];
    const nodes = [{ id: "owner", name: "Owner", type: "person", status: "active", confidence: 1, isOwner: true }];
    const links = [];
    for (let h = 0; h < 24; h++) nodes.push({ id: "h" + h, name: "H" + h, type: "hub", isHub: true, status: "active", confidence: 0.9 });
    const core = 2000 - 1 - 24 - 400;
    for (let i = 0; i < core; i++) {
        const member = rnd() < 0.4;
        const hub = "h" + (i % 24);
        nodes.push({ id: "c" + i, name: "C" + i, type: types[i % types.length], status: "active",
                     confidence: 0.3 + rnd() * 0.7, ...(member ? { hubId: hub } : {}) });
        if (member) links.push({ source: hub, target: "c" + i });
        if (i > 0) links.push({ source: "c" + i, target: "c" + Math.floor(rnd() * i) });
        if (rnd() < 0.5 && i > 0) links.push({ source: "c" + i, target: "c" + Math.floor(rnd() * i) });
        if (i % 3 === 0) links.push({ source: "owner", target: "c" + i });
    }
    for (let i = 0; i < 400; i++) {
        nodes.push({ id: "i" + i, name: "I" + i, type: types[i % types.length], status: "active", confidence: 0.3 + rnd() * 0.7 });
    }
    return { nodes, links };
}

if (process.argv[2] === "--one") {
    const { loadGraph } = require("./graph-physics-harness.js");
    const t = loadGraph();
    t.call("updateGraph", ownerShaped());
    const sim = t.get("simulation");
    sim.stop();
    let ticks = null;
    const start = process.hrtime.bigint();
    for (let i = 1; i <= 600; i++) {
        sim.tick();
        if (ticks === null && sim.alpha() < sim.alphaMin()) { ticks = i; break; }
    }
    const ms = Number(process.hrtime.bigint() - start) / 1e6 / (ticks || 600);
    const nodes = t.get("visibleNodes");
    const radius = (n) => t.sandbox.nodeRadius(n);
    // Overlap through a uniform grid (pairs within the largest diameter only).
    const cell = 40, grid = new Map();
    nodes.forEach((n, i) => {
        const k = `${Math.floor(n.x / cell)},${Math.floor(n.y / cell)}`;
        if (!grid.has(k)) grid.set(k, []);
        grid.get(k).push(i);
    });
    let pairs = 0;
    const touched = new Set();
    nodes.forEach((a, i) => {
        const cx = Math.floor(a.x / cell), cy = Math.floor(a.y / cell);
        for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
            for (const j of grid.get(`${cx + dx},${cy + dy}`) || []) {
                if (j <= i) continue;
                const b = nodes[j];
                if (Math.hypot(a.x - b.x, a.y - b.y) < radius(a) + radius(b)) { pairs++; touched.add(i); touched.add(j); }
            }
        }
    });
    const byType = new Map();
    for (const n of nodes) {
        if (n.isHub || n.isFacet) continue;
        if (!byType.has(n.type)) byType.set(n.type, []);
        byType.get(n.type).push(n);
    }
    const centroids = new Map([...byType].map(([k, v]) => [k, [v.reduce((s, n) => s + n.x, 0) / v.length,
                                                               v.reduce((s, n) => s + n.y, 0) / v.length]]));
    let within = 0, count = 0;
    for (const [k, v] of byType) for (const n of v) { const c = centroids.get(k); within += Math.hypot(n.x - c[0], n.y - c[1]); count++; }
    const cs = [...centroids.values()];
    let between = 0, cp = 0;
    for (let i = 0; i < cs.length; i++) for (let j = i + 1; j < cs.length; j++) { between += Math.hypot(cs[i][0] - cs[j][0], cs[i][1] - cs[j][1]); cp++; }
    const r = nodes.map((n) => Math.hypot(n.x, n.y)).sort((a, b) => a - b);
    console.log(JSON.stringify({
        ticks, msPerTick: +ms.toFixed(2), overlapPairs: pairs, overlapNodes: +(touched.size / nodes.length).toFixed(3),
        typeSep: +((between / cp) / (within / count)).toFixed(2), spreadP90: Math.round(r[Math.floor(0.9 * r.length)]),
    }));
    process.exit(0);
}

const source = fs.readFileSync(path.join(__dirname, "..", "..", "Sources", "CicadaApp", "Resources", "graph", "graph.js"), "utf8");
const marker = "    return 0.04;                                            // soft type clustering";
if (!source.includes(marker)) throw new Error("graph.js's type anchor strength moved; update the bench");
console.log("strength  " + ["ticks", "ms/tick", "overlapPairs", "overlapNodes", "typeSep", "spreadP90"].map((c) => c.padStart(13)).join(""));
for (const strength of [0.04, 0.1, 0.2, 0.4]) {
    const file = path.join(os.tmpdir(), `graph-zones-${strength}.js`);
    fs.writeFileSync(file, source.replace(marker, `    return ${strength};`));
    const out = JSON.parse(execFileSync(process.execPath, [__filename, "--one"], { env: { ...process.env, GRAPH_JS: file } }));
    fs.unlinkSync(file);
    console.log(String(strength).padEnd(10) + [out.ticks, out.msPerTick, out.overlapPairs, out.overlapNodes, out.typeSep,
                                                out.spreadP90].map((v) => String(v).padStart(13)).join(""));
}
