// G109 physics harness: load the REAL graph.js under the REAL bundled d3 (not the
// chainable Proxy the other Tests/graph/*.test.js use) so graph.js's own
// startSimulation, forces, and drag handlers can be ticked by hand and measured.
//
// Shared by graph-physics.bench.js (prints numbers) and graph-physics.test.js
// (asserts thresholds). Not part of `swift test`; plain node scripts, outside
// every SwiftPM target and outside Resources/ (which Package.swift copies into
// the app bundle wholesale).
//
// What is stubbed and why:
//   - requestAnimationFrame: a no-op. graph.js's tick listener calls
//     scheduleRedraw -> rAF; with a no-op, draw() never runs and the sim never
//     schedules itself. Every tick here is an explicit simulation.tick().
//   - performance.now: a fake clock the throw scenario advances by hand, so the
//     DRAG_STALE_MS gate and the per-move velocity EMA see real 16.7 ms gaps.
//   - Math.random: a seeded LCG, so seedPositionFor's jitter is reproducible
//     and every number the bench prints is stable across runs.
//   - simulation.stop() is called right after every graph.js entry point that
//     calls .restart(): d3.forceSimulation starts its own d3-timer (setTimeout
//     under Node) and would otherwise tick concurrently with the manual loop.
//
// GRAPH_JS=/abs/path/to/graph.js overrides the file under test (used to compare
// a patched copy against the committed one without touching the repo).
"use strict";

const fs = require("fs");
const vm = require("vm");
const path = require("path");

const RESOURCES = path.join(__dirname, "..", "..", "Sources", "CicadaApp", "Resources", "graph");
const GRAPH_JS = process.env.GRAPH_JS || path.join(RESOURCES, "graph.js");
const d3 = require(path.join(RESOURCES, "d3.v7.min.js"));

// ---- deterministic PRNG (LCG) ----
let seed = 42;
function rnd() { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; }
function reseed(s = 42) { seed = s; }

// ---- DOM stubs (same shape as graph-delta.test.js) ----
const noop = () => {};
let canvasStub;
const ctxStub = new Proxy({}, {
    get: (t, k) => {
        if (k === "canvas") return canvasStub;
        if (k === "measureText") return () => ({ width: 10 });
        if (k === "createLinearGradient") return () => ({ addColorStop: noop });
        return typeof k === "string" ? noop : undefined;
    },
    set: () => true,
});
canvasStub = {
    clientWidth: 1200, clientHeight: 800, width: 1200, height: 800,
    style: {}, classList: { add: noop, remove: noop },
    getContext: () => ctxStub, addEventListener: noop,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 1200, height: 800 }),
};

function loadGraph() {
    const clock = { now: 0 };
    const sandbox = {
        console,
        document: { getElementById: () => canvasStub, addEventListener: noop, documentElement: {}, body: {} },
        window: {
            devicePixelRatio: 2, innerWidth: 1200, innerHeight: 800, addEventListener: noop,
            // Swallow the JS->Swift messages (nodeClicked etc.) the click-release path posts.
            webkit: { messageHandlers: { cicada: { postMessage: noop } } },
        },
        requestAnimationFrame: noop, cancelAnimationFrame: noop,
        performance: { now: () => clock.now },
        setTimeout, clearTimeout, Date, JSON, Map, Set, Number, String, Boolean, Array, Object,
        Math: Object.create(Math, { random: { value: rnd } }),
        d3,
    };
    sandbox.globalThis = sandbox;
    sandbox.self = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(GRAPH_JS, "utf8"), sandbox, { filename: "graph.js" });
    vm.runInContext("canvas = document.getElementById('graph'); ctx = canvas.getContext('2d');", sandbox);
    // `let`/`const` module state is lexical, not a sandbox property: read it by expression.
    const get = (expr) => vm.runInContext(expr, sandbox);
    const call = (fn, arg) => vm.runInContext(`${fn}(${JSON.stringify(arg)})`, sandbox);
    return { sandbox, clock, get, call };
}

// ---- synthetic graph: hub-and-spoke core + facets + N isolates ----
const TYPES = ["person", "project", "company", "concept", "tool", "skill", "location", "media", "directory"];

const SIZES = {
    small:  { n: 300,  isolates: 100, hubs: 6,  facets: 20,  extraLinksPerNode: 3 },
    medium: { n: 1500, isolates: 500, hubs: 20, facets: 100, extraLinksPerNode: 3 },
    dense:  { n: 1500, isolates: 500, hubs: 20, facets: 100, extraLinksPerNode: 5 },
};

function synthetic({ n, isolates, hubs, facets, extraLinksPerNode }) {
    reseed(42);
    const nodes = [], links = [];
    for (let i = 0; i < hubs; i++) {
        nodes.push({ id: "h" + i, name: "H" + i, type: "hub", isHub: true, status: "active", confidence: 0.9, memberCount: 0 });
    }
    const core = n - isolates - facets - hubs;
    for (let i = 0; i < core; i++) {
        const hub = "h" + (i % hubs);
        nodes.push({ id: "c" + i, name: "C" + i, type: TYPES[i % TYPES.length], status: "active", confidence: 0.3 + rnd() * 0.7, hubId: hub });
        links.push({ source: hub, target: "c" + i });
        for (let k = 0; k < extraLinksPerNode; k++) {
            if (i > 0 && rnd() < 0.8) links.push({ source: "c" + i, target: "c" + Math.floor(rnd() * i) });
        }
    }
    for (let i = 0; i < facets; i++) {
        const parent = "c" + Math.floor(rnd() * core);
        nodes.push({ id: "f" + i, name: "F" + i, type: "concept", status: "active", confidence: 0.6, isFacet: true, parentId: parent, context: "engineering" });
        links.push({ source: parent, target: "f" + i, kind: "facetOf" });
    }
    for (let i = 0; i < isolates; i++) {
        nodes.push({ id: "i" + i, name: "I" + i, type: TYPES[i % TYPES.length], status: "active", confidence: 0.3 + rnd() * 0.7 });
    }
    return { nodes, links };
}

// ---- metrics ----
function kePerNode(nodes) { let k = 0; for (const n of nodes) k += n.vx * n.vx + n.vy * n.vy; return k / nodes.length; }
function maxSpeed(nodes) { let m = 0; for (const n of nodes) m = Math.max(m, Math.hypot(n.vx, n.vy)); return m; }
const quantile = (sorted, p) => sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))] : NaN;
const round = (v, d = 0) => (v == null || !isFinite(v)) ? v : +v.toFixed(d);

// Isolate = visible degree 0 (no entry in neighborsById) and not a hub. Radii are
// from the origin, which is the centre of the hub ring and of the type anchors.
function radii(get) {
    const vis = get("visibleNodes"), nb = get("neighborsById");
    const iso = vis.filter(n => !nb.has(n.id) && !n.isHub);
    const core = vis.filter(n => nb.has(n.id));
    const r = a => a.map(n => Math.hypot(n.x, n.y)).sort((x, y) => x - y);
    const ir = r(iso), cr = r(core);
    return {
        isoN: iso.length,
        isoMedian: round(quantile(ir, 0.5)), isoMax: round(ir[ir.length - 1]),
        coreMedian: round(quantile(cr, 0.5)), coreP90: round(quantile(cr, 0.9)), coreMax: round(cr[cr.length - 1]),
        ratioMaxToP90: round(ir[ir.length - 1] / quantile(cr, 0.9), 2),
        ratioMedToP90: round(quantile(ir, 0.5) / quantile(cr, 0.9), 2),
    };
}

// The node every throw scenario uses: the outermost connected non-hub, non-facet
// node with visible degree <= 3. Deterministic for a given synthetic + graph.js.
function peripheralNode(get) {
    const vis = get("visibleNodes"), nb = get("neighborsById");
    const cands = vis.filter(n => !n.isHub && !n.isFacet && nb.has(n.id) && nb.get(n.id).size <= 3);
    return cands.reduce((a, b) => Math.hypot(b.x, b.y) > Math.hypot(a.x, a.y) ? b : a);
}

// Follow one node after a release: how long its OUTWARD velocity component stays
// >= 0.5 wu/tick (coastTicks), how far out it got (coastDist, max projection on the
// throw direction), when |v| first drops below 0.1 (ticksToStop), when d3's own
// timer would have stopped (alpha < alphaMin; timerStopTick), and how far every
// OTHER visible node moved over the 60 ticks after release (otherDisp60).
function followRelease(sim, visibleNodes, node, ux, uy) {
    const rx = node.x, ry = node.y;
    const atRelease = visibleNodes.map(n => [n.x, n.y]);
    let coastTicks = null, coastDist = 0, ticksToStop = null, timerStopTick = null, otherDisp60 = null;
    for (let t = 1; t <= 300; t++) {
        sim.tick();
        const vOut = node.vx * ux + node.vy * uy;
        const proj = (node.x - rx) * ux + (node.y - ry) * uy;
        if (proj > coastDist) coastDist = proj;
        if (coastTicks === null && vOut < 0.5) coastTicks = t - 1;
        if (ticksToStop === null && Math.hypot(node.vx, node.vy) < 0.1) ticksToStop = t;
        if (timerStopTick === null && sim.alpha() < sim.alphaMin()) timerStopTick = t;
        if (t === 60) {
            let disp = 0, cnt = 0;
            visibleNodes.forEach((n, i) => { if (n !== node) { disp += Math.hypot(n.x - atRelease[i][0], n.y - atRelease[i][1]); cnt++; } });
            otherDisp60 = round(disp / cnt, 2);
        }
    }
    return { coastTicks: coastTicks ?? ">300", coastDist: round(coastDist), ticksToStop: ticksToStop ?? ">300", timerStopTick: timerStopTick ?? ">300", otherDisp60 };
}

// One full scenario on one synthetic. Returns a flat metrics object.
function runScenario(sizeName) {
    const size = SIZES[sizeName];
    const { sandbox, clock, get, call } = loadGraph();
    call("updateGraph", synthetic(size));
    const sim = get("simulation");
    sim.stop();
    const visibleNodes = get("visibleNodes");
    const out = { size: sizeName, n: size.n, links: get("visibleLinks").length };

    // 1. cold settle: 400 manual ticks from alpha 1.0
    let ticksToAlphaMin = null, keAtStop = null;
    const t0 = performance.now();
    for (let t = 1; t <= 400; t++) {
        sim.tick();
        if (ticksToAlphaMin === null && sim.alpha() < sim.alphaMin()) { ticksToAlphaMin = t; keAtStop = kePerNode(visibleNodes); }
    }
    out.msPerTick = round((performance.now() - t0) / 400, 2);
    out.ke400 = +kePerNode(visibleNodes).toExponential(1);
    out.maxSpeed400 = round(maxSpeed(visibleNodes), 2);
    out.ticksToAlphaMin = ticksToAlphaMin;
    out.keAtStop = keAtStop == null ? null : +keAtStop.toExponential(1);
    Object.assign(out, radii(get));

    // 2. free coast: mousedown on the peripheral node (the app's only way to raise
    //    alpha before a throw), one tick, release as a click (seeds 0), then set a
    //    28 wu/tick outward velocity by hand — the memo's bench, with graph.js's
    //    own alpha state at release.
    const node = peripheralNode(get);
    const tr = get("transform");
    const toScreen = (x, y) => [x * tr.k + tr.x, y * tr.k + tr.y];
    const r0 = Math.hypot(node.x, node.y), ux = node.x / r0, uy = node.y / r0;
    let [sx, sy] = toScreen(node.x, node.y);
    clock.now = 1000;
    sandbox.onMouseDown({ clientX: sx, clientY: sy, stopImmediatePropagation: noop });
    sim.stop();
    sim.tick();
    clock.now += 5;
    sandbox.onMouseUp({});
    sim.stop();
    node.vx = 28 * ux; node.vy = 28 * uy;
    out.freeAlphaAtRelease = round(sim.alpha(), 3);
    const free = followRelease(sim, visibleNodes, node, ux, uy);
    out.freeCoastTicks = free.coastTicks; out.freeCoastDist = free.coastDist; out.freeTicksToStop = free.ticksToStop;

    // 3. drag-throw through the real handlers: press, six 28-wu moves 16.7 ms apart
    //    (ticking once per move, as the app would), release 5 ms after the last one.
    //    seededDragVelocity's EMA turns the 28 wu/tick pointer motion into ~26.
    for (let t = 0; t < 200; t++) sim.tick(); // let the free coast die out first
    [sx, sy] = toScreen(node.x, node.y);
    clock.now = 5000;
    sandbox.onMouseDown({ clientX: sx, clientY: sy, stopImmediatePropagation: noop });
    sim.stop();
    out.holdAlphaTarget = sim.alphaTarget();
    const stepScreen = 28 * tr.k;
    let holdKE = 0;
    for (let i = 1; i <= 6; i++) {
        clock.now += 1000 / 60;
        sx += stepScreen * ux; sy += stepScreen * uy;
        sandbox.onMouseMove({ clientX: sx, clientY: sy });
        sim.tick();
        holdKE += kePerNode(visibleNodes);
    }
    out.holdKE = +(holdKE / 6).toExponential(1);
    clock.now += 5;
    sandbox.onMouseUp({});
    sim.stop();
    out.seededSpeed = round(Math.hypot(node.vx, node.vy), 1);
    out.alphaAtRelease = round(sim.alpha(), 3);
    const thrown = followRelease(sim, visibleNodes, node, ux, uy);
    out.throwCoastTicks = thrown.coastTicks; out.throwCoastDist = thrown.coastDist;
    out.throwTicksToStop = thrown.ticksToStop; out.throwTimerStopTick = thrown.timerStopTick;
    out.otherDisp60 = thrown.otherDisp60;
    return out;
}

// The app's most frequent reheat: an SSE version tick after a Sleep pushes a
// delta with no structural change (or one renamed node) onto a settled layout,
// and updateGraphDelta reheats at 0.3. Measures how far the settled nodes move
// by the time d3's timer would stop again — per class, because the residual is
// the packed connected core (facets first), not the isolate discs. "Settled"
// is 400 cold ticks, the same state radii() reads. Returns null metrics if the
// delta entry point is missing (a future graph.js that renames it).
function runDeltaNoop(sizeName) {
    const size = SIZES[sizeName];
    const { get, call } = loadGraph();
    call("updateGraph", synthetic(size));
    let sim = get("simulation");
    sim.stop();
    for (let t = 0; t < 400; t++) sim.tick();
    const nb = get("neighborsById");
    const before = new Map(get("visibleNodes").map(n => [n.id, [n.x, n.y, n.isHub ? "hub" : nb.has(n.id) ? "core" : "iso"]]));
    call("updateGraphDelta", { added: [], updated: [], removed: [] });
    sim = get("simulation");
    sim.stop();
    let stopTick = null;
    for (let t = 1; t <= 600 && stopTick === null; t++) { sim.tick(); if (sim.alpha() < sim.alphaMin()) stopTick = t; }
    const disp = { core: [], iso: [], hub: [] };
    for (const n of get("visibleNodes")) {
        const b = before.get(n.id);
        if (b) disp[b[2]].push(Math.hypot(n.x - b[0], n.y - b[1]));
    }
    const mean = a => a.length ? a.reduce((p, c) => p + c, 0) / a.length : NaN;
    const mx = a => a.length ? Math.max(...a) : NaN;
    return {
        size: sizeName,
        deltaNoopStopTick: stopTick ?? ">600",
        deltaNoopCoreMean: round(mean(disp.core), 1), deltaNoopCoreMax: round(mx(disp.core)),
        deltaNoopIsoMean: round(mean(disp.iso), 1), deltaNoopIsoMax: round(mx(disp.iso)),
    };
}

module.exports = { GRAPH_JS, SIZES, loadGraph, synthetic, runScenario, runDeltaNoop, kePerNode, maxSpeed, radii };
