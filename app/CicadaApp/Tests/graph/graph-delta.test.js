#!/usr/bin/env node
//
// Regression net for graph.js's delta ingest (§5.6). Run it with:
//
//     node app/CicadaApp/Tests/graph/graph-delta.test.js
//
// It loads the real `Resources/graph/graph.js` into a vm context with a stubbed
// canvas/document and a chainable no-op `d3`: the point is graph.js's data
// bookkeeping (which nodes and links exist, whether positions and optional
// fields survive an update), not the force layout, which d3 owns and which a
// unit test can't assert anything stable about anyway. Positions are assigned
// by hand to stand in for a settled simulation.
//
// Not part of `swift test` (SwiftPM's test target is Tests/CicadaAppTests);
// this is a plain node script so the JS half of the delta transport has a
// regression net at all.

const fs = require("fs");
const vm = require("vm");
const path = require("path");

const dir = path.join(__dirname, "..", "..", "Sources", "CicadaApp", "Resources", "graph");

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

function freshSandbox() {
    const sandbox = {
        console,
        document: { getElementById: () => canvasStub, addEventListener: noop, documentElement: {}, body: {} },
        window: { devicePixelRatio: 2, innerWidth: 1200, innerHeight: 800, addEventListener: noop },
        requestAnimationFrame: noop, cancelAnimationFrame: noop,
        setTimeout, clearTimeout, Math, Date, JSON, Map, Set, Number, String, Boolean, Array, Object,
    };
    sandbox.globalThis = sandbox;
    sandbox.self = sandbox;
    vm.createContext(sandbox);
    // Chainable no-op d3 — graph.js only needs the calls to not throw.
    const chainable = () => new Proxy(function () {}, {
        get: () => chainable(),
        apply: () => chainable(),
    });
    sandbox.d3 = new Proxy({}, { get: () => chainable() });
    vm.runInContext(fs.readFileSync(path.join(dir, "graph.js"), "utf8"), sandbox, { filename: "graph.js" });
    // init() is never called (it wires zoom/drag/keyboard), so bind the two
    // globals the ingest path needs by hand.
    vm.runInContext("canvas = document.getElementById('graph'); ctx = canvas.getContext('2d');", sandbox);
    return sandbox;
}

const run = (sandbox, src) => vm.runInContext(src, sandbox);
const call = (sandbox, fn, arg) => run(sandbox, `${fn}(${JSON.stringify(arg)})`);
const settle = (sandbox) =>
    run(sandbox, "nodes.forEach((n, i) => { n.x = 100 + i * 37; n.y = 200 - i * 11; n.vx = 0.5; n.vy = -0.25; });");

let failures = 0;
const check = (label, cond) => {
    console.log((cond ? "PASS " : "FAIL ") + label);
    if (!cond) failures += 1;
};

const node = (id, type, hash, extra = {}) => ({
    id, name: id.toUpperCase(), type, status: "active", confidence: 0.9, tags: [],
    degree: 0, isHub: false, hasPending: false, memberCount: 0, contentHash: hash, ...extra,
});

// ---------------------------------------------------------------- case 1
// add / update / remove leave every untouched node exactly where it was.
{
    const sb = freshSandbox();
    call(sb, "updateGraph", {
        nodes: [node("a", "person", "h1"), node("b", "project", "h2"), node("c", "tool", "h3"), node("d", "concept", "h4")],
        links: [{ source: "a", target: "b", label: "works_on" }, { source: "b", target: "c", label: "uses" }],
    });
    settle(sb);
    const before = Object.fromEntries(run(sb, "nodes.map(n => [n.id, n.x, n.y])").map(([id, x, y]) => [id, [x, y]]));

    call(sb, "updateGraphDelta", {
        added: [node("e", "company", "h5")],
        updated: [{ ...node("b", "project", "h2b"), confidence: 0.42, name: "B RENAMED" }],
        removed: ["d"],
        links: [
            { source: "a", target: "b", label: "works_on" },
            { source: "b", target: "c", label: "uses" },
            { source: "a", target: "e", label: "at" },
        ],
        isFull: false,
    });
    const after = Object.fromEntries(run(sb, "nodes.map(n => [n.id, n.x, n.y])").map(([id, x, y]) => [id, [x, y]]));
    const ids = run(sb, "nodes.map(n => n.id)");
    const b = run(sb, "nodes.find(n => n.id === 'b')");

    check("removed node is gone", !ids.includes("d"));
    check("added node is present", ids.includes("e"));
    check("updated node kept its position", before.b[0] === after.b[0] && before.b[1] === after.b[1]);
    check("untouched nodes kept their positions",
        before.a[0] === after.a[0] && before.a[1] === after.a[1] &&
        before.c[0] === after.c[0] && before.c[1] === after.c[1]);
    check("updated node took the new fields",
        b.confidence === 0.42 && b.name === "B RENAMED" && b.contentHash === "h2b");
    check("added node was seeded with a position",
        Number.isFinite(after.e[0]) && Number.isFinite(after.e[1]));
    check("links were replaced with the supplied set", run(sb, "links.length") === 3);
    check("added/updated positions landed in prevPositions",
        run(sb, "prevPositions.has('e') && prevPositions.has('b')"));
    check("removed node dropped out of prevPositions", run(sb, "!prevPositions.has('d')"));

    // A second delta with no `links` key must leave links alone apart from the
    // ones dangling off the removal.
    call(sb, "updateGraphDelta", { added: [], updated: [], removed: ["e"], isFull: false });
    check("removing a node also drops its dangling link", run(sb, "links.length") === 2);
    check("a delta never falls back to a full reset", run(sb, "nodes.some(n => n.id === 'a')"));
}

// ---------------------------------------------------------------- case 2
// An updated node must be able to LOSE an optional field. The Swift encoder
// omits hubId/parentId/isFacet/context/observers/contexts when empty, so a
// plain Object.assign would keep the stale value forever.
{
    const sb = freshSandbox();
    call(sb, "updateGraph", {
        nodes: [
            node("hub:people", "hub", "h0", { isHub: true }),
            node("p", "person", "h1", {
                hubId: "hub:people", isFacet: true, parentId: "p",
                context: "engineering", observers: ["agent"], contexts: ["engineering"],
            }),
        ],
        links: [],
    });
    settle(sb);
    call(sb, "updateGraphDelta", {
        added: [], removed: [], isFull: false,
        updated: [node("p", "person", "h2")],   // no hubId / isFacet / parentId / context
    });
    const p = run(sb, "nodes.find(n => n.id === 'p')");
    check("update clears a hubId the payload no longer carries", p.hubId === undefined);
    check("update clears isFacet/parentId/context",
        !p.isFacet && p.parentId === undefined && p.context === undefined);
    check("update clears observers/contexts", p.observers === undefined && p.contexts === undefined);
    check("update keeps the fields the payload does carry",
        p.contentHash === "h2" && p.type === "person" && p.confidence === 0.9);
}

// ---------------------------------------------------------------- case 3
// The full-path fallback must not lose the payload: a delta that arrives before
// there is a simulation (or with isFull) has no `nodes` key, and handing it to
// updateGraph verbatim used to blank the canvas — the bank-switch bug.
{
    const sb = freshSandbox();
    call(sb, "updateGraphDelta", {
        added: [node("a", "person", "h1"), node("b", "project", "h2")],
        updated: [], removed: [],
        links: [{ source: "a", target: "b", label: "works_on" }],
        isFull: false,
    });
    check("a delta on an empty sim falls back to a LOSSLESS full update",
        run(sb, "nodes.length") === 2 && run(sb, "links.length") === 1);

    const sb2 = freshSandbox();
    call(sb2, "updateGraphDelta", {
        nodes: [node("a", "person", "h1")],
        links: [],
        isFull: true,
    });
    check("an isFull payload still goes through updateGraph unchanged",
        run(sb2, "nodes.length") === 1);
}

console.log(failures === 0 ? "\nAll graph delta checks passed." : `\n${failures} check(s) FAILED.`);
process.exit(failures === 0 ? 0 : 1);
