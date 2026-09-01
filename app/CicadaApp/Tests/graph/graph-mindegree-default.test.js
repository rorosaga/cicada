#!/usr/bin/env node
//
// Regression net for G84a — graph.js's built-in `filters.minDegree` default
// must agree with Swift's (`GraphFilter.swift` `minDegree = 0`). They used to
// disagree (JS defaulted to 1, dropping every zero-degree node) which only
// showed up on the COLD paint, before Swift's own `applyFilters` push landed
// — see `Coordinator.pushGraphData()` in `GraphView.swift`. Run with:
//
//     node app/CicadaApp/Tests/graph/graph-mindegree-default.test.js
//
// Not part of `swift test` (SwiftPM's test target is Tests/CicadaAppTests);
// this is a plain node script, same harness shape as graph-delta.test.js.

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
    const chainable = () => new Proxy(function () {}, {
        get: () => chainable(),
        apply: () => chainable(),
    });
    sandbox.d3 = new Proxy({}, { get: () => chainable() });
    vm.runInContext(fs.readFileSync(path.join(dir, "graph.js"), "utf8"), sandbox, { filename: "graph.js" });
    vm.runInContext("canvas = document.getElementById('graph'); ctx = canvas.getContext('2d');", sandbox);
    return sandbox;
}

const run = (sandbox, src) => vm.runInContext(src, sandbox);
const call = (sandbox, fn, arg) => run(sandbox, `${fn}(${JSON.stringify(arg)})`);

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
// graph.js's OWN default must be minDegree 0, matching GraphFilter.swift,
// before any applyFilters() call ever reaches the page.
{
    const sb = freshSandbox();
    check("filters.minDegree defaults to 0 (matches GraphFilter.swift)",
        run(sb, "filters.minDegree") === 0);
}

// ---------------------------------------------------------------- case 2
// A cold `updateGraph` push containing a zero-degree (isolated) node must
// leave it visible under the default filter — no applyFilters() call yet,
// exactly the state the canvas is in between graph.js loading and Swift's
// pushGraphData() completion handler running applyFilters().
{
    const sb = freshSandbox();
    call(sb, "updateGraph", {
        nodes: [
            node("a", "person", "h1"),
            node("isolated", "concept", "h2"), // no links touch this node
        ],
        links: [],
    });
    const visibleIds = run(sb, "visibleNodes.map(n => n.id)");
    check("a zero-degree node survives the cold paint under the default filter",
        visibleIds.includes("isolated"));
    check("its sibling is visible too", visibleIds.includes("a"));
}

console.log(failures === 0 ? "\nAll graph min-degree default checks passed." : `\n${failures} check(s) FAILED.`);
process.exit(failures === 0 ? 0 : 1);
