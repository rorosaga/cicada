#!/usr/bin/env node
//
// G247 bench (owner 2026-11-25): a cold open of the owner-shaped graph (graph-bank-shape.js) with ~5,100 quiet saved
// items drawn as dots (today), folded into ~47 list bubbles, and with none at all, through graph.js's real entry points
// and d3. Run it with:
//
//     node app/CicadaApp/Tests/graph/graph-bubbles.bench.js
//
// Measured 2026-11-25 on this Mac: today 4.9 s to stop, 34 ms a tick; bubbles 3.1 s, 20 ms a tick (as with no saves).
"use strict";
const harness = require("./graph-physics-harness.js");
const { bankShaped, coldOpen } = require("./graph-bank-shape.js");

const SAVED = [["yt", 3150], ["bm", 880], ["post", 455], ["book", 290], ["repo", 200], ["feed", 130]];
const LISTS = [["yt", 25], ["bm", 12], ["post", 5], ["book", 2], ["repo", 2], ["feed", 1]];

function graph(seed, mode) {
    const g = bankShaped(seed);
    if (mode === "none") return g;
    const lists = new Map(LISTS);
    const bubbles = [];
    for (const [src, n] of SAVED) {
        const ids = [];
        for (let i = 0; i < n; i++) {
            const id = `saved-${src}-${i}`;
            ids.push(id);
            g.nodes.push({ id, name: `Saved ${src} ${i}`, type: "media", status: "active", confidence: 0.5, quiet: true });
        }
        const k = lists.get(src);
        for (let j = 0; j < k; j++) {
            const members = ids.filter((_, i) => i % k === j);
            bubbles.push({ id: `list:${src}-${j}`, name: `List ${src} ${j}`, kindNoun: "pages", count: members.length, members, folders: [], outside: [] });
        }
    }
    if (mode === "bubbles") g.bubbles = bubbles;
    return g;
}

for (const mode of ["today", "bubbles", "none"]) {
    for (const seed of [7, 3]) {
        const { h, metrics } = coldOpen(harness, seed, { graph: graph(seed, mode) });
        h.get("transform = d3.zoomIdentity");
        const t0 = performance.now();
        for (let i = 0; i < 10; i++) h.get("draw()");
        console.log(JSON.stringify({ mode, seed, drawn: h.get("visibleNodes.length"), stopTick: metrics.stopTick,
            msTickP50: metrics.msTickP50, msTickP95: metrics.msTickP95, secondsToStop: metrics.secondsToStop,
            drawMsJs: +((performance.now() - t0) / 10).toFixed(1) }));
    }
}
