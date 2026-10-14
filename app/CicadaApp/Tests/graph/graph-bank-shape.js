// A synthetic graph with the SHAPE of the owner's real bank (2026-10-14, measured by the coordinator; no names,
// no real values — every id is a placeholder). Deterministic for a given seed.
//
//   3,698 nodes, ~41,570 links (parallel links included: a pair joined by several claims draws several lines)
//   150 components: one giant of 3,529, then 6, 4, 3, 3, 3, 2 x 6, and 138 isolated singletons
//   degrees: max 2,092 (the owner's own page), then 174, 150 x 5, 140, 105, 104; median 2
//   star centres with 226, 44, 23, 9, 8, 8, 8 and 7 degree-1 leaves (the 226 hang off the owner's page)
//   type hubs (server `hub:` nodes, capped at 150 members) and tag hubs, members carrying `hubId`
//   ~100 facet satellites on core pages
//
// The dense core is planted as COMMUNITIES (Chung-Lu inside each, 85 % of core links intra-community), so the
// organisation of the equilibrium can be measured: `community` is a test-only field graph.js never reads.
"use strict";

// `opts.isolates`: [[type, count], ...] replaces the 138 isolates of random type — e.g. LIVE_ISOLATES_2026_10_14, the
// 1,000 isolates (bookmarks just imported, mostly `media`) the live graph carried after #285.
const LIVE_ISOLATES_2026_10_14 = [["media", 860], ["skill", 87], ["concept", 23], ["tool", 13], ["company", 8],
                                  ["project", 3], ["location", 3], ["person", 2], ["directory", 1]];

function bankShaped(seed = 7, opts = {}) {
    let s = seed >>> 0;
    const rnd = () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
    const pick = (arr) => arr[Math.floor(rnd() * arr.length)];
    // `opts.typeMix` replaces the pages' type mix (e.g. one type dominating, which pulls the body toward its anchor)
    const TYPE_MIX = opts.typeMix || [["person", 25], ["concept", 25], ["project", 12], ["tool", 12], ["company", 10],
                                      ["location", 5], ["skill", 5], ["media", 3], ["directory", 2], ["repo", 1]];
    const typeTotal = TYPE_MIX.reduce((a, [, w]) => a + w, 0);
    const randType = () => { let r = rnd() * typeTotal; for (const [t, w] of TYPE_MIX) { if ((r -= w) < 0) return t; } return "concept"; };
    const nodes = [], links = [];
    const node = (id, extra = {}) => {
        const n = { id, name: id, type: randType(), status: "active", confidence: 0.3 + rnd() * 0.7, ...extra };
        nodes.push(n);
        return n;
    };
    const link = (a, b, extra = {}) => links.push({ source: a, target: b, ...extra });

    // ---- the giant: 3,529 nodes ----
    const owner = node("owner", { type: "person", confidence: 1, isOwner: true });
    // 16 hubs: 5 type hubs at the 150 cap, one at 140, then tag hubs.
    const hubSizes = [150, 150, 150, 150, 150, 140, 60, 45, 40, 30, 25, 20, 15, 10, 8, 6];
    const hubs = hubSizes.map((sz, i) => node("hub" + i, { type: "hub", isHub: true, confidence: 1, _size: sz }));
    // star centres (ordinary pages) and their leaves
    const STAR_LEAVES = [44, 23, 9, 8, 8, 8, 7];
    const stars = STAR_LEAVES.map((_, i) => node("star" + i));
    const leaves = [];
    for (let i = 0; i < 226; i++) leaves.push([node("ol" + i), owner]);
    STAR_LEAVES.forEach((k, i) => { for (let j = 0; j < k; j++) leaves.push([node(`sl${i}-${j}`), stars[i]]); });
    // facets: 100 satellites, parents chosen from the core below
    const FACETS = 100;
    // the rest of the giant: a planted-community core and a low-degree periphery
    const giantTarget = 3529;
    const fixed = 1 + hubs.length + stars.length + leaves.length + FACETS;
    const rest = giantTarget - fixed;
    const CORE = 1650;
    const PERIPHERY = rest - CORE;
    const COMMUNITIES = 12;
    const core = [];
    for (let i = 0; i < CORE; i++) {
        // Chung-Lu weight, skewed low and capped at 100 (the real degrees after the top ten sit at <= 104)
        const w = 8 + 92 * Math.pow(rnd(), 1.3);
        core.push(node("c" + i, { community: i % COMMUNITIES, _w: w }));
    }
    const periphery = [];
    for (let i = 0; i < PERIPHERY; i++) periphery.push(node("p" + i));
    const byCommunity = (k) => core.filter(c => c.community === k);
    // the star centres live in communities too
    stars.forEach((st, i) => { st.community = i % COMMUNITIES; st._w = 20; core.push(st); });
    // a few named high-degree pages (174, 105, 104 in the real list)
    core[0]._w = 174; core[1]._w = 105; core[2]._w = 104;

    // leaves -> their centre (degree 1)
    for (const [leaf, centre] of leaves) link(centre.id, leaf.id);
    // periphery: degree 1-2. Most pages the owner names and one other page names (owner + core); some named by two
    // core pages; a few hang off one core page (at most a handful per page — the real leaf counts after the eight
    // stars are <= 7).
    let ownerLinks = 226;
    for (const p of periphery) {
        const r = rnd();
        const c = pick(core);
        p.community = c.community;
        link(c.id, p.id);
        if (r < 0.6) { link(owner.id, p.id); ownerLinks++; }
        else if (r < 0.85) link(pick(byCommunity(p.community)).id, p.id);
    }
    // the owner's remaining links go to core pages (some twice: parallel links)
    while (ownerLinks < 2092) { link(owner.id, pick(core).id); ownerLinks++; }
    // hubs: members are the core and periphery, the first hub claiming a node is its hubId
    const memberPool = core;
    hubs.forEach((h) => {
        const seen = new Set();
        while (seen.size < h._size) {
            const m = pick(memberPool);
            if (seen.has(m.id)) continue;
            seen.add(m.id);
            link(h.id, m.id, { label: "member of" });
            if (!m.hubId) m.hubId = h.id;
        }
        delete h._size;
    });
    // core: Chung-Lu, 85 % intra-community, 25 % of the edges doubled or tripled (parallel claims)
    const byComm = Array.from({ length: COMMUNITIES }, () => []);
    for (const c of core) byComm[c.community].push(c);
    const cum = (arr) => { let t = 0; return arr.map(n => (t += n._w)); };
    const commCum = byComm.map(cum);
    const allCum = cum(core);
    const draw = (arr, cumArr) => { const r = rnd() * cumArr[cumArr.length - 1]; let lo = 0, hi = cumArr.length - 1; while (lo < hi) { const m = (lo + hi) >> 1; if (cumArr[m] < r) lo = m + 1; else hi = m; } return arr[lo]; };
    const TOTAL = 41570;                       // the small components add 20 links and the facets 100, below
    while (links.length < TOTAL - FACETS - 20) {
        const a = draw(core, allCum);
        const b = rnd() < 0.85 ? draw(byComm[a.community], commCum[a.community]) : draw(core, allCum);
        if (a === b) continue;
        const mult = rnd() < 0.25 ? (rnd() < 0.7 ? 2 : 3) : 1;
        for (let k = 0; k < mult; k++) link(a.id, b.id, { label: "rel" + k });
    }
    // facets
    for (let i = 0; i < FACETS; i++) {
        const parent = pick(core);
        node(`${parent.id}#f${i}`, { type: parent.type, isFacet: true, parentId: parent.id, context: "engineering" });
        link(`${parent.id}#f${i}`, parent.id, { label: "facetOf", kind: "facetOf", context: "engineering" });
    }

    // ---- small components: 6, 4, 3, 3, 3, then six pairs ----
    const smallSizes = [6, 4, 3, 3, 3, 2, 2, 2, 2, 2, 2];
    smallSizes.forEach((sz, ci) => {
        const ids = [];
        for (let j = 0; j < sz; j++) ids.push(node(`sc${ci}-${j}`).id);
        // a star for the 6, a path otherwise
        for (let j = 1; j < sz; j++) link(sz === 6 ? ids[0] : ids[j - 1], ids[j]);
    });
    // ---- isolated singletons: 138 of random type, or the given mix ----
    if (opts.isolates) {
        let k = 0;
        for (const [type, count] of opts.isolates) for (let i = 0; i < count; i++) node("iso" + k++, { type });
    } else {
        for (let i = 0; i < 138; i++) node("iso" + i);
    }

    for (const n of nodes) delete n._w;
    return { nodes, links };
}

// Connected components over a {nodes, links} payload (string endpoints). Largest first.
function components(g) {
    const parent = new Map(g.nodes.map(n => [n.id, n.id]));
    const find = (x) => { while (parent.get(x) !== x) { parent.set(x, parent.get(parent.get(x))); x = parent.get(x); } return x; };
    for (const l of g.links) {
        const a = find(typeof l.source === "object" ? l.source.id : l.source);
        const b = find(typeof l.target === "object" ? l.target.id : l.target);
        if (a !== b) parent.set(a, b);
    }
    const groups = new Map();
    for (const n of g.nodes) { const r = find(n.id); if (!groups.has(r)) groups.set(r, []); groups.get(r).push(n.id); }
    return [...groups.values()].sort((a, b) => b.length - a.length);
}

function shapeSummary(g) {
    const deg = new Map(g.nodes.map(n => [n.id, 0]));
    for (const l of g.links) { deg.set(l.source, deg.get(l.source) + 1); deg.set(l.target, deg.get(l.target) + 1); }
    const ds = [...deg.values()].sort((a, b) => b - a);
    const comps = components(g).map(c => c.length);
    return {
        nodes: g.nodes.length, links: g.links.length, components: comps.length,
        giant: comps[0], next: comps.slice(1, 12), singletons: comps.filter(c => c === 1).length,
        pairs: comps.filter(c => c === 2).length, topDegrees: ds.slice(0, 10), medianDegree: ds[Math.floor(ds.length / 2)],
    };
}

// The filter Swift pushes after every graph push (GraphFilter's defaults): archived and dropped hidden.
const SWIFT_DEFAULT_FILTER = { minConfidence: 0, minDegree: 0, types: [], statuses: ["active", "decaying"], tags: [],
                               contexts: [], observers: [], showLogos: false };

const quantile = (sorted, p) => sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))];

// Geometry of a laid-out bank-shaped graph. Radii are from the giant component's centroid, in units of the giant's
// p95 radius (R95). `community` is the generator's planted community, a field graph.js never reads.
function bankGeometry(get, g) {
    const giantIds = new Set(components(g)[0]);
    const vis = get("visibleNodes");
    const giant = vis.filter(n => giantIds.has(n.id));
    const cx = giant.reduce((a, n) => a + n.x, 0) / giant.length;
    const cy = giant.reduce((a, n) => a + n.y, 0) / giant.length;
    const r = n => Math.hypot(n.x - cx, n.y - cy);
    const R95 = quantile(giant.map(r).sort((a, b) => a - b), 0.95);
    const outside = vis.filter(n => !giantIds.has(n.id)).map(n => r(n) / R95).sort((a, b) => a - b);
    const byId = new Map(vis.map(n => [n.id, n]));
    const leafDist = (prefix, centre) => vis.filter(n => n.id.startsWith(prefix))
        .map(n => Math.hypot(n.x - byId.get(centre).x, n.y - byId.get(centre).y)).sort((a, b) => a - b);
    const ownerLeaves = leafDist("ol", "owner");
    const star44 = leafDist("sl0-", "star0");
    // organisation: mean distance between planted-community centroids / mean distance of a page to its own centroid
    const comm = new Map();
    for (const n of vis) if (n.community >= 0 && /^c\d/.test(n.id)) {
        if (!comm.has(n.community)) comm.set(n.community, []);
        comm.get(n.community).push(n);
    }
    const cents = [...comm.values()].map(a => [a.reduce((t, n) => t + n.x, 0) / a.length, a.reduce((t, n) => t + n.y, 0) / a.length, a]);
    let intra = 0, ic = 0, inter = 0, cc = 0;
    for (const [x, y, a] of cents) for (const n of a) { intra += Math.hypot(n.x - x, n.y - y); ic += 1; }
    for (let i = 0; i < cents.length; i++) for (let j = i + 1; j < cents.length; j++) {
        inter += Math.hypot(cents[i][0] - cents[j][0], cents[i][1] - cents[j][1]); cc += 1;
    }
    // overlap: the share of nodes whose disc cuts into another's by more than 10 %
    const rad = get("nodeRadius");
    const sorted = [...vis].sort((a, b) => a.x - b.x);
    const inOverlap = new Set();
    for (let i = 0; i < sorted.length; i++) {
        const a = sorted[i], ra = rad(a);
        for (let j = i + 1; j < sorted.length; j++) {
            const b = sorted[j];
            if (b.x - a.x > ra + 100) break;
            if (Math.hypot(a.x - b.x, a.y - b.y) < (ra + rad(b)) * 0.9) { inOverlap.add(a.id); inOverlap.add(b.id); }
        }
    }
    // roundness. coverage: degrees around the centroid that satellites (nodes outside the giant) occupy, i.e. 360
    // minus the largest empty angular gap. hullFill: the convex hull of every node over the centroid-centred circle
    // through the farthest node (1 = a disc). rimSpread: over 24 angular bins, the farthest node per bin, max / min
    // (1 = round; a slab or a line on one side shows as a large ratio).
    const angles = vis.filter(n => !giantIds.has(n.id)).map(n => Math.atan2(n.y - cy, n.x - cx)).sort((a, b) => a - b);
    let gap = angles.length ? angles[0] + 2 * Math.PI - angles[angles.length - 1] : 2 * Math.PI;
    for (let i = 1; i < angles.length; i++) gap = Math.max(gap, angles[i] - angles[i - 1]);
    const pts = vis.map(n => [n.x, n.y]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const lower = [], upper = [];
    for (const p of pts) { while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop(); lower.push(p); }
    for (const p of [...pts].reverse()) { while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop(); upper.push(p); }
    const hull = lower.slice(0, -1).concat(upper.slice(0, -1));
    let hullArea = 0;
    for (let i = 0; i < hull.length; i++) { const a = hull[i], b = hull[(i + 1) % hull.length]; hullArea += a[0] * b[1] - b[0] * a[1]; }
    hullArea = Math.abs(hullArea) / 2;
    const rMax = Math.max(...vis.map(r));
    const BINS = 24, rim = new Array(BINS).fill(0);
    for (const n of vis) {
        const b = Math.min(BINS - 1, Math.floor(((Math.atan2(n.y - cy, n.x - cx) + Math.PI) / (2 * Math.PI)) * BINS));
        rim[b] = Math.max(rim[b], r(n));
    }
    return {
        coverageDeg: Math.round(360 - gap * 180 / Math.PI),
        hullFill: +(hullArea / (Math.PI * rMax * rMax)).toFixed(2),
        rimSpread: +(Math.max(...rim) / Math.max(1, Math.min(...rim))).toFixed(2),
        giantN: giant.length, R95: Math.round(R95),
        farthestR: +(Math.max(...vis.map(r)) / R95).toFixed(2),
        outsideMinR: +outside[0].toFixed(2), outsideMaxR: +outside[outside.length - 1].toFixed(2),
        ownerLeafMed: Math.round(quantile(ownerLeaves, 0.5)), ownerLeafMax: Math.round(ownerLeaves[ownerLeaves.length - 1]),
        star44LeafMed: Math.round(quantile(star44, 0.5)), star44LeafMax: Math.round(star44[star44.length - 1]),
        commSep: +((inter / cc) / (intra / ic)).toFixed(2),
        overlapPct: Math.round(100 * inOverlap.size / vis.length),
    };
}

// A cold open of the bank-shaped graph through graph.js's real entry points (updateGraph, then the filter Swift
// re-asserts), stepped like d3's own timer until it stops. Times every tick; the only machine-dependent numbers are
// the ms ones.
function coldOpen(harness, seed = 7, opts = {}) {
    const h = harness.loadGraph({ frames: true });
    const g = bankShaped(seed, opts);
    h.call("updateGraph", g);
    h.call("applyFilters", SWIFT_DEFAULT_FILTER);
    h.get("simulation").stop();   // the harness steps by hand; d3's own timer must not run beside it
    h.disarmFit();
    const vis = h.get("visibleNodes");
    const times = [];
    let stopTick = null, stillTick = null;
    for (let t = 1; t <= 1000; t++) {
        const t0 = performance.now();
        const running = h.step();
        times.push(performance.now() - t0);
        if (stillTick === null) {
            const sp = vis.map(n => Math.hypot(n.vx, n.vy)).sort((a, b) => a - b);
            if (quantile(sp, 0.95) < 1) stillTick = t;
        }
        if (!running) { stopTick = t; break; }
    }
    const ke = vis.reduce((k, n) => k + n.vx * n.vx + n.vy * n.vy, 0) / vis.length;
    const vmax = Math.sqrt(Math.max(...vis.map(n => n.vx * n.vx + n.vy * n.vy)));
    const sortedTimes = [...times].sort((a, b) => a - b);
    // after the stop: how many frames the redraw loop still asks for
    let frames = 0;
    while (h.pumpFrame() > 0 && frames < 1000) frames += 1;
    return {
        h, g,
        metrics: {
            stopTick, stillTick,
            msTickP50: +quantile(sortedTimes, 0.5).toFixed(1), msTickP95: +quantile(sortedTimes, 0.95).toFixed(1),
            secondsToStop: +(times.reduce((a, b) => a + b, 0) / 1000).toFixed(2),
            keAtStop: +ke.toExponential(1), vmaxAtStop: +vmax.toFixed(2),
            framesAfterStop: frames,
            ...bankGeometry(h.get, g),
        },
    };
}

module.exports = { LIVE_ISOLATES_2026_10_14, bankShaped, components, shapeSummary, bankGeometry, coldOpen, SWIFT_DEFAULT_FILTER };

if (require.main === module) console.log(JSON.stringify(shapeSummary(bankShaped())));
