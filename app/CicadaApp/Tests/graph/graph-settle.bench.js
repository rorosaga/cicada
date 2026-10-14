#!/usr/bin/env node
//
// G109 settle bench (2026-10-14) — a cold open of a graph with the owner's bank's SHAPE (graph-bank-shape.js:
// 3,698 nodes, 41,570 links, one 3,529-node component, a 2,092-degree page, 138 isolates, 11 small components; no
// names) through graph.js's real entry points and d3, stepped the way d3's own timer steps it. Run it with:
//
//     node app/CicadaApp/Tests/graph/graph-settle.bench.js
//     GRAPH_JS=/abs/path/graph.js node app/CicadaApp/Tests/graph/graph-settle.bench.js   # e.g. the dev copy
//
//   stopTick         steps until the timer stops (graph.js's settle check, or alpha < alphaMin)
//   stillTick        first step at which 95 % of nodes move < 1 wu a tick (what looks still)
//   msTickP50/P95    one step (machine-dependent); secondsToStop = their sum
//   keAtStop         mean vx^2+vy^2 when the timer stops — large means it froze mid-motion
//   vmaxAtStop       the fastest node then, wu/tick
//   framesAfterStop  frames the redraw loop still requests once stopped (0-1 = idle)
//   farthestR        the farthest node from the giant's centroid, in giant p95 radii (R95)
//   outsideMin/MaxR  where the nodes NOT in the giant sit, in R95 (a band just outside the body is ~1.0-1.35)
//   ownerLeaf*       the 226 degree-1 leaves of the 2,092-degree page: median / max distance to it, wu
//   star44Leaf*      the 44 leaves of the next star
//   commSep          planted-community centroid spread / mean distance to own centroid (higher = more organised)
//   overlapPct       nodes whose disc cuts >10 % into another's
//   strokesPerFrame  canvas stroke() calls for one frame at zoom 1 (every link drawn)
"use strict";
const harness = require("./graph-physics-harness.js");
const { coldOpen } = require("./graph-bank-shape.js");

console.log("graph.js:", harness.GRAPH_JS);
for (const seed of [7, 3, 11]) {
    const { h, metrics } = coldOpen(harness, seed);
    h.get("transform = d3.zoomIdentity");
    harness.drawCounters.stroke = 0;
    h.get("draw()");
    console.log(JSON.stringify({ seed, ...metrics, strokesPerFrame: harness.drawCounters.stroke }));
}
