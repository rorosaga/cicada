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
// before the pass (49ffcad8). The proportion pass (2026-10-15, later that day) adds the size curve across 50 / 500 /
// 4.5k nodes and the link width per zoom tier. ~10 s.
"use strict";

const harness = require("./graph-physics-harness.js");
const { coldOpen, bankShaped1015, bankShapedAt, lookMetrics, components, shapeSummary } = require("./graph-bank-shape.js");

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

    // ---- dots at the floor of the size curve, the owner's page large but not dominant (proportion pass) ----
    // measured median 2.20-2.21 pt, smallest page 1.54 pt (#291: 0.95 / 0.66 pt, a speck under a 1 pt line)
    check(`${tag} at the fit zoom the median dot sits at the floor (2.2 pt, +-10 %)`, Math.abs(L.fitMedianPt - 2.2) <= 0.22, L.fitMedianPt);
    check(`${tag} at the fit zoom the smallest page dot is >= 1.4 pt`, L.fitMinPt >= 1.4, L.fitMinPt);
    // measured 6.7 (before 14.3: a 206 wu disc over the centre)
    check(`${tag} the largest node is 4-8x the median`, L.radiusMaxOverMedian >= 4 && L.radiusMaxOverMedian <= 8, L.radiusMaxOverMedian);
    // ---- negative space ----
    // measured 0.071-0.073 (#291: 0.013, before it 0.25-0.26): the 6 % the curve asks of the median, plus the big pages
    check(`${tag} discs cover 5-10 % of the fitted view`, L.coverage >= 0.05 && L.coverage <= 0.10, L.coverage);
    // measured 0 % (before 51-52 %)
    check(`${tag} <= 5 % of nodes overlap another disc`, m.overlapPct <= 5, m.overlapPct);
    // ---- the halo: a loose, irregular scatter, not ruled rows ----
    // measured 0.32-0.33 (#291 0.49-0.50 with 2.3x smaller dots; before it 0.09-0.15: rows of evenly spaced beads). The
    // bigger discs exclude the very closest pairs (collide), as in any random scatter of discs, so the spread narrows.
    check(`${tag} halo spacing is irregular (nearest-neighbour CV >= 0.28)`, L.haloNnCv >= 0.28, L.haloNnCv);
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
    const base = (id) => h.get(`baseRadius(nodes.find(n => n.id === "${id}"))`);
    check("forty claims between two pages size them as one neighbour", Math.abs(base("b") - (2.2 + 0.4 + 0.45)) < 1e-9, base("b").toFixed(2));
    check("a server degree counting parallels does not size a node", Math.abs(r("c") - r("b")) < 1e-9, `${r("c").toFixed(2)} vs ${r("b").toFixed(2)}`);
}

// ---- proportion pass (owner, 2026-10-15): dots scale with the graph, inside a floor and a ceiling at the fit zoom ----
// The curve: the median dot's on-screen radius at the fit zoom is sqrt(6 % of the view / (pi x nodes)), clamped to
// [DOT_MIN_PT, DOT_MAX_PT] = [2.2, 8] pt. Measured in the 1200x800 harness view (values next to each check).
const sized = new Map([[4544, kept]]);
const sizeRun = (N, opts = {}) => coldOpen(harness, 7, { graph: N === 4544 ? bankShaped1015(7) : bankShapedAt(N, 7), ...opts });
for (const N of [50, 500]) sized.set(N, sizeRun(N));
const fitPt = new Map();
for (const [N, run] of sized) {
    const h = run.h;
    const L = lookMetrics(h.get);
    fitPt.set(N, L);
    const want = h.get(`dotTargetPt(${h.get("visibleNodes.length")})`);
    const tag = `${N} nodes:`;
    // measured 50: 7.75 (want 8); 500: 5.98 (want 6.05); 4.5k: 2.20 (want 2.2)
    check(`${tag} at the fit zoom the median dot is within 10 % of the curve's ${want.toFixed(2)} pt`, Math.abs(L.fitMedianPt - want) <= 0.1 * want, L.fitMedianPt);
    // the floor and the ceiling, whatever the size: measured smallest 5.4 / 4.2 / 1.5 pt, median 7.8 / 6.0 / 2.2 pt
    check(`${tag} the floor: no page dot under 1.4 pt, the median >= ${h.get("DOT_MIN_PT")} pt - 10 %`,
          L.fitMinPt >= 1.4 && L.fitMedianPt >= 0.9 * h.get("DOT_MIN_PT"), `${L.fitMinPt}, ${L.fitMedianPt}`);
    // measured largest 11.4 / 16.3 / 14.8 pt
    check(`${tag} the ceiling: the median <= ${h.get("DOT_MAX_PT")} pt + 10 %, the largest dot <= 24 pt`,
          L.fitMedianPt <= 1.1 * h.get("DOT_MAX_PT") && L.fitMaxPt <= 24, `${L.fitMedianPt}, ${L.fitMaxPt}`);
    // a bigger dot never lands on its neighbour: measured 0 % at every size
    check(`${tag} <= 5 % of nodes overlap another disc`, run.metrics.overlapPct <= 5, run.metrics.overlapPct);
    check(`${tag} it settles within 150 steps, then asks for no frames`, run.metrics.stopTick !== null && run.metrics.stopTick <= 150 && run.metrics.framesAfterStop === 0,
          `${run.metrics.stopTick} steps, ${run.metrics.framesAfterStop} frames`);
    // relative order: bigger means more connected, at every size
    const vis = h.get("visibleNodes").filter(n => !h.get("nodeIsFacet")(n));
    const rad = h.get("nodeRadius"), base = h.get("baseRadius");
    const s = h.get("sizeScale");
    check(`${tag} every dot is its scale-1 size times one scale (${s.toFixed(2)}), so the order holds`, vis.every(n => Math.abs(rad(n) - s * base(n)) < 1e-9));
}
check("a smaller graph gets bigger dots (median 50 > 500 > 4.5k at the fit zoom)",
      fitPt.get(50).fitMedianPt > fitPt.get(500).fitMedianPt && fitPt.get(500).fitMedianPt > fitPt.get(4544).fitMedianPt,
      [50, 500, 4544].map(N => fitPt.get(N).fitMedianPt).join(" > "));
{
    // the view they are fitted to: a 4.5k graph in a small 800x560 window keeps the floor; 500 nodes in it get smaller
    // dots than in 1200x800 (the 6 % share of a smaller view), still above the floor
    const small = () => {
        const ctx = new Proxy({}, { get: (t, k) => (k === "measureText" ? () => ({ width: 10 }) : typeof k === "string" ? () => {} : undefined), set: () => true });
        return { clientWidth: 800, clientHeight: 560, width: 800, height: 560, style: {}, classList: { add() {}, remove() {} },
                 getContext: () => ctx, addEventListener() {}, getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 560 }) };
    };
    for (const N of [500, 4544]) {
        const run = sizeRun(N, { canvas: small() });
        const L = lookMetrics(run.h.get);
        const want = run.h.get(`dotTargetPt(${run.h.get("visibleNodes.length")})`);
        // measured 500: 4.06 (want 4.0); 4.5k: 2.2
        check(`${N} nodes in an 800x560 view: the median dot is within 10 % of ${want.toFixed(2)} pt, the smallest >= 1.4 pt`,
              Math.abs(L.fitMedianPt - want) <= 0.1 * want && L.fitMinPt >= 1.4, `${L.fitMedianPt}, ${L.fitMinPt}`);
        if (N === 500) check("500 nodes: a smaller view, smaller dots", L.fitMedianPt < fitPt.get(500).fitMedianPt, `${L.fitMedianPt} < ${fitPt.get(500).fitMedianPt}`);
    }
}

// ---- the scale is chosen afresh when the graph changes under it (review, 2026-10-15) ----
// A bank switch pushes a blank graph, then the new bank as a full push; the previous bank's scale must not survive it.
// Measured before the fix: 50 -> blank -> 4.5k gave a 1.19 pt median (under the floor), 4.5k -> 50 a 2.5-17 pt one,
// and filtering the 4.5k shape to its 251 people (a 0.3 reheat) a 10.0 pt one (over the ceiling).
{
    const settle = (h) => { h.get("simulation").stop(); h.disarmFit(); let t = 0; while (t < 1000 && h.step()) t += 1; return t; };
    const push = (h, g) => { h.call("updateGraph", g); h.call("applyFilters", { minConfidence: 0, minDegree: 0, types: [], statuses: ["active", "decaying"], tags: [], contexts: [], observers: [], showLogos: false }); return settle(h); };
    const median = (h) => lookMetrics(h.get).fitMedianPt;
    const target = (h) => h.get(`dotTargetPt(${h.get("visibleNodes.length")})`);
    const near = (h) => Math.abs(median(h) - target(h)) <= 0.1 * target(h);
    const big = bankShaped1015(7), small = bankShapedAt(50, 7);
    {
        const h = harness.loadGraph({ frames: true });
        push(h, small);
        push(h, { nodes: [], links: [] });
        const steps = push(h, big);
        // measured 2.21 pt, 94 steps
        check("a bank switch 50 -> blank -> 4.5k: the new bank's median at the fit zoom is on its curve (2.2 pt +-10 %)", near(h) && steps <= 150, `${median(h)} pt, ${steps} steps`);
        push(h, small);
        // measured 7.95 pt (the 50-node bank's ids are all cached from its first paint)
        check("... and back to the 50-node bank: on its curve (8 pt +-10 %)", near(h), median(h));
        push(h, big);
        // measured 2.19 pt
        check("... and back to the 4.5k bank: on its curve again", near(h), median(h));
    }
    {
        const h = harness.loadGraph({ frames: true });
        push(h, big);
        push(h, small);
        // measured 7.86 pt (the two synthetics share ids, so this is the warm whole-graph relayout, not a cold one)
        check("4.5k -> a 50-node bank: on its curve (8 pt +-10 %)", near(h), median(h));
    }
    {
        const h = harness.loadGraph({ frames: true });
        push(h, big);
        h.call("applyFilters", { types: ["person"] });
        const steps = settle(h);
        const L = lookMetrics(h.get);
        // measured 8.13 pt, 82 steps, no overlap
        check("filtering the 4.5k shape to its 251 people: the median stays within the ceiling (8 pt + 10 %)", L.fitMedianPt <= 1.1 * h.get("DOT_MAX_PT") && near(h) && steps <= 150, `${L.fitMedianPt} pt, ${steps} steps`);
        h.call("applyFilters", { types: [] });
        settle(h);
        // measured 2.2 pt
        check("... and clearing the filter: back on the 4.5k curve", near(h), median(h));
    }
}

// ---- links are hairlines: at every zoom tier, well under the smallest dot drawn ----
for (const [N, run] of sized) {
    const h = run.h;
    const fitK = h.get("transformForNodes(visibleNodes, 60).k");
    // the smallest dot drawn, facets included
    const minR = Math.min(...h.get("visibleNodes").map(n => h.get("nodeRadius")(n)));
    const tiers = { MIN_ZOOM: h.get("MIN_ZOOM"), fit: fitK, ZOOM_HUBS_ONLY: h.get("ZOOM_HUBS_ONLY"), ZOOM_NODE_LABELS: h.get("ZOOM_NODE_LABELS"),
                    ZOOM_EDGE_LABELS: h.get("ZOOM_EDGE_LABELS"), MAX_ZOOM: h.get("MAX_ZOOM") };
    const worst = { eff: 0, stroke: 0 };
    let ok = true;
    for (const dpr of [2, 1]) {
        h.get(`dpr = ${dpr}`);
        for (const [, k] of Object.entries(tiers)) {
            const st = h.get(`linkStroke(${k})`);
            const diameter = 2 * minR * k;
            const eff = st.width * st.alpha;          // what the eye sees: a sub-pixel width is a fainter device pixel
            worst.eff = Math.max(worst.eff, eff / diameter);
            // the stroke itself: never wider than one device pixel unless the dots are big enough to dwarf it
            if (st.width > 1 / dpr + 1e-9) worst.stroke = Math.max(worst.stroke, st.width / diameter);
            if (eff > 0.15 * diameter || st.width > Math.max(1 / dpr, 0.15 * diameter) + 1e-9 || st.width > Math.max(1 / dpr, h.get("LINK_WIDTH_MAX_PT")) + 1e-9) ok = false;
        }
    }
    h.get("dpr = 2");
    // measured: the effective width is <= 0.12 of the smallest dot's diameter at every tier (LINK_WIDTH_OF_DOT; #291's
    // 1 pt line was 0.75x the smallest page dot's diameter at the fit zoom)
    check(`${N} nodes: a link is <= 15 % of the smallest dot's diameter at every zoom tier (dpr 2 and 1)`, ok,
          `worst effective ${worst.eff.toFixed(3)}, worst stroke over a device pixel ${worst.stroke.toFixed(3)}`);
}
{
    // draw() strokes the resting links at linkStroke's width, and a hovered page's links at LINK_LIT_PT
    const { h } = kept;
    h.get(`(() => { const inner = ctx; globalThis.__widths = [];
        ctx = new Proxy(inner, { get: (t, k) => k === "stroke" ? () => __widths.push(__lw) : t[k],
                                 set: (t, k, v) => { if (k === "lineWidth") globalThis.__lw = v; return true; } }); })()`);
    h.get("transform = transformForNodes(visibleNodes, 60)");
    h.get("hoveredNode = null; __widths = []; draw()");
    const k = h.get("transform.k");
    const rest = h.get(`linkStroke(${k}).width`);
    const first = h.get("__widths[0]") * k;
    check("at rest, draw() strokes links at linkStroke's width", Math.abs(first - rest) < 1e-9, `${first.toFixed(3)} pt`);
    h.get("hoveredNode = visibleNodes.find(n => n.id === 'owner'); __widths = []; draw(); hoveredNode = null");
    const widths = h.get("__widths.slice()").map(w => +(w * k).toFixed(3));
    check("a hovered page's links thicken to LINK_LIT_PT", widths.includes(h.get("LINK_LIT_PT")) && widths.includes(+rest.toFixed(3)), JSON.stringify([...new Set(widths)].slice(0, 6)));
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
