#!/usr/bin/env node
//
// Owner 2026-11-25: one bubble per list of saved things. Run it with:
//
//     node app/CicadaApp/Tests/graph/graph-bubbles.test.js
//
// Loads the real graph.js and d3 (graph-physics-harness.js) and checks what the canvas does with a payload's `bubbles`:
// a closed bubble keeps its members out of the layout and the draw and draws their links to itself; an earned page stays
// a node joined to its bubble; opening packs the members inside the bubble's circle at fixed places without reheating
// the layout; Esc closes at once; a reveal of a folded page opens its bubble and lands on it; a delta that moves a page
// out of a bubble seeds it beside the bubble; a payload without bubbles is untouched.
"use strict";
const harness = require("./graph-physics-harness.js");

let failed = 0;
function check(name, ok, detail = "") {
    console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? "  [" + detail + "]" : ""}`);
    if (!ok) failed += 1;
}

function payload({ members = 40, earned = true, extra = {} } = {}) {
    const nodes = [], links = [];
    for (let i = 0; i < 30; i++) nodes.push({ id: "page-" + i, name: "Page " + i, type: "concept", status: "active", confidence: 0.7 });
    for (let i = 1; i < 30; i++) links.push({ source: "page-0", target: "page-" + i, label: "related to" });
    const ids = [];
    for (let i = 0; i < members; i++) {
        const id = "video-" + String(i).padStart(3, "0");
        ids.push(id);
        nodes.push({ id, name: "Video " + i, type: "media", status: "active", confidence: 0.5, quiet: true });
    }
    // three saved videos are about page-1: one line from the bubble, not three
    for (const id of ids.slice(0, 3)) links.push({ source: id, target: "page-1", label: "about" });
    nodes.push({ id: "talked-video", name: "Talked video", type: "media", status: "active", confidence: 0.5 });
    links.push({ source: "talked-video", target: "page-2", label: "about" });
    const bubble = {
        id: "list:youtube-playlists", name: "YouTube: Playlists", kindNoun: "videos", count: ids.length, mark: "youtube-playlist",
        members: ids, folders: [{ key: "youtube-playlists-a", name: "Alpha", members: ids.slice(0, 10) }],
        outside: earned ? ["talked-video"] : [], ...extra,
    };
    return { nodes, links, bubbles: [bubble] };
}

function load(data) {
    const h = harness.loadGraph({ frames: true });
    const posts = [];
    h.sandbox.window.webkit.messageHandlers.cicada.postMessage = (m) => posts.push(JSON.parse(m));
    h.call("updateGraph", data);
    h.disarmFit();
    h.runUntilStop(600);
    return { h, posts };
}

const ids = (h, expr) => h.get(`${expr}.map(n => n.id)`);
const linkPairs = (h) => h.get("links.map(l => [typeof l.source === 'object' ? l.source.id : l.source, typeof l.target === 'object' ? l.target.id : l.target].join('>'))");

// ---- closed
{
    const { h } = load(payload());
    const shown = new Set(ids(h, "visibleNodes"));
    check("a closed bubble is one node and none of its members are", shown.has("list:youtube-playlists") && !shown.has("video-000") && !shown.has("video-039"),
          `${shown.size} drawn`);
    check("... and the simulation holds only what is drawn", h.get("simulation.nodes().length") === shown.size);
    check("every page is still in the payload's page set", h.get("rawNodes.length") === 30 + 40 + 1);
    const pairs = linkPairs(h);
    const fromBubble = pairs.filter(p => p === "list:youtube-playlists>page-1");
    check("three members' links to one page are one line from the bubble", fromBubble.length === 1, pairs.filter(p => p.includes("list:")).join(","));
    check("an earned page stays a node, joined to its bubble", shown.has("talked-video") && pairs.includes("talked-video>list:youtube-playlists"));
    const r = h.get("nodeRadius(bubbleNodeById.get('list:youtube-playlists'))");
    const median = h.get("(() => { const r = visibleNodes.filter(n => !n.isBubble).map(nodeRadius).sort((a,b)=>a-b); return r[Math.floor(r.length/2)]; })()");
    check("the bubble is bigger than a page, never dominant", r > median && r < median * 12, `${r.toFixed(1)} vs median ${median.toFixed(1)}`);
    check("a bubble is never culled by the min-degree filter", (() => {
        h.call("applyFilters", { minDegree: 50 });
        return ids(h, "visibleNodes").includes("list:youtube-playlists");
    })());
    h.call("applyFilters", { minDegree: 0 });
    check("its label says what it holds", h.get("labelText(bubbleNodeById.get('list:youtube-playlists'))") === "YouTube: Playlists · " + (40).toLocaleString() + " videos");
}

// ---- open, close
{
    const { h, posts } = load(payload());
    const alphaBefore = h.get("simulation.alpha()");
    const opened = h.get("openBubble('list:youtube-playlists', { animate: false })");
    check("a bubble opens", opened === true && h.get("openBubbleId") === "list:youtube-playlists");
    check("... and Swift is told", posts.some(p => p.type === "bubbleOpened" && p.id === "list:youtube-playlists"));
    check("opening reheats nothing", h.get("simulation.alpha()") === alphaBefore);
    const L = h.get("({ cx: openLayout.cx, cy: openLayout.cy, r: openLayout.r, n: openLayout.members.length, folders: openLayout.folders.length, leafR: openLayout.leafR })");
    check("every member is laid out inside the open circle: the folder, and one ring for the pages in no folder", L.n === 40 && L.folders === 2, JSON.stringify(L));
    const outside = h.get(`openLayout.members.filter(n => Math.hypot(n.x - ${L.cx}, n.y - ${L.cy}) + n._packedR > ${L.r} + 1e-6).length`);
    check("... none past its edge", outside === 0);
    check("a member is picked where it is drawn", (() => {
        const m = h.get("openLayout.members[5]");
        const sx = m.x * h.get("transform.k") + h.get("transform.x"), sy = m.y * h.get("transform.k") + h.get("transform.y");
        const hit = h.get(`pickNode(${sx}, ${sy})`);
        return hit && hit.id === m.id;
    })());
    check("the camera fits the open bubble", Math.abs(h.get("transform.k") - h.get("openLayout.fitK")) < 1e-9);
    const before = h.get("openLayout.before");
    h.get("onKeyDown({ key: 'Escape', preventDefault() {} })");
    check("Esc goes to the page, which closes panels and the column before the bubble", posts.some(p => p.type === "escape") && h.get("openBubbleId") !== null);
    h.get("closeOpenBubble(false)");
    check("the page's close (Esc's) closes it at once", h.get("openBubbleId") === null && h.get("openLayout") === null);
    check("... the camera is back where it was", Math.abs(h.get("transform.k") - before.k) < 1e-9);
    check("... and Swift is told", posts.some(p => p.type === "bubbleClosed"));
    check("... and its members hold no stale place", h.get("rawNodes.filter(n => n.id.startsWith('video-') && (n.x != null || n._packed)).length") === 0);
}

// ---- clicks outside, a lost release, folding under the pointer
{
    const { h, posts } = load(payload());
    h.get("openBubble('list:youtube-playlists', { animate: false })");
    h.get("pressStart = { x: 2, y: 2, moved: false, onNode: false, pan: false }");
    h.get("onZoomGestureEnd({ sourceEvent: { type: 'mouseup', clientX: 2, clientY: 2 } })");
    check("a click outside an open bubble asks the page, which closes panels and the column first",
          posts.some(p => p.type === "bubbleOutsideClicked") && h.get("openBubbleId") !== null);
    const m = h.get("openLayout.members[3]");
    const sx = m.x * h.get("transform.k") + h.get("transform.x"), sy = m.y * h.get("transform.k") + h.get("transform.y");
    posts.length = 0;
    h.get(`pressStart = { x: ${sx}, y: ${sy}, moved: false, onNode: false, pan: false }`);
    h.get(`onZoomGestureEnd({ sourceEvent: { type: 'mouseup', clientX: ${sx + 1}, clientY: ${sy} } })`);
    check("... one inside it, between its pages, is an ordinary empty-canvas click", posts.some(p => p.type === "backgroundClicked"));
    h.get("pressMember = openLayout.members[0]");
    h.get("cancelInteraction()");
    check("a lost release forgets the pressed page", h.get("pressMember") === null);
    h.get("closeBubble({})");
}
{
    const { h } = load(payload({ earned: true }));
    h.get("hoveredNode = visibleNodes.find(n => n.id === 'talked-video')");
    const next = payload();
    next.bubbles[0].members = [...next.bubbles[0].members, "talked-video"];
    next.bubbles[0].outside = [];
    h.call("updateGraphDelta", { added: [], updated: [], removed: [], bubbles: next.bubbles, isFull: false });
    check("a page that folds while under the pointer is no longer hovered", h.get("hoveredNode") === null);
}

// ---- reveal and search
{
    const { h } = load(payload());
    const landed = h.get("revealNode('video-007')");
    check("revealing a folded page opens its bubble and lands on it", landed === true && h.get("openBubbleId") === "list:youtube-playlists");
    const n = h.get("foldedById.get('video-007')");
    const sx = n.x * h.get("transform.k") + h.get("transform.x");
    check("... centred on the page", Math.abs(sx - h.get("width") / 2) < 1, `${sx.toFixed(1)}`);
    check("... and it can be kept in view as the selection", h.get("ensureVisible('video-007', false)") === true);
    h.get("closeBubble({})");
    h.call("highlightSearch", JSON.stringify(["video-003"]));
    check("a search match inside a closed bubble rings the bubble", h.get("searchHighlight.has('list:youtube-playlists')"));
}

// ---- deltas
{
    const { h } = load(payload());
    const b = h.get("bubbleNodeById.get('list:youtube-playlists')");
    const next = payload();
    next.bubbles[0].members = next.bubbles[0].members.filter(id => id !== "video-020");
    next.bubbles[0].outside = ["talked-video", "video-020"];
    h.call("updateGraphDelta", { added: [], updated: [], removed: [], bubbles: next.bubbles, isFull: false });
    const moved = h.get("visibleNodes.find(n => n.id === 'video-020')");
    check("a page that leaves its bubble becomes a node", Boolean(moved));
    check("... seeded beside its bubble", moved && Math.hypot(moved.x - b.x, moved.y - b.y) < 200, moved ? `${Math.hypot(moved.x - b.x, moved.y - b.y).toFixed(0)} wu` : "");
    const pageX = h.get("visibleNodes.find(n => n.id === 'page-5').x");
    h.call("updateGraphDelta", { added: [], updated: [{ id: "video-021", name: "Renamed", type: "media", status: "active", confidence: 0.5, quiet: true }], removed: ["video-022"], isFull: false });
    check("an update to a folded page keeps it folded, a removal drops it", !ids(h, "visibleNodes").includes("video-021") && !h.get("foldedById.has('video-022')") && h.get("foldedById.get('video-021').name") === "Renamed");
    check("... and moves no settled page", h.get("visibleNodes.find(n => n.id === 'page-5').x") === pageX);
    h.call("updateGraphDelta", { added: [], updated: [], removed: [], bubbles: [], isFull: false });
    check("bubbles going away unfold every page", ids(h, "visibleNodes").includes("video-000") && !ids(h, "visibleNodes").includes("list:youtube-playlists"));
}

// ---- no bubbles: untouched
{
    const data = payload();
    delete data.bubbles;
    const { h } = load(data);
    check("a payload without bubbles draws every page", h.get("visibleNodes.length") === 71 && h.get("links") === h.get("links"));
}

if (failed) { console.log(`\n${failed} bubble check(s) FAILED.`); process.exit(1); }
console.log("\nAll bubble checks passed.");
