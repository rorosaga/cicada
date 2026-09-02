#!/usr/bin/env node
//
// Regression net for graph.js's logo layer (G59). Run it with:
//
//     node app/CicadaApp/Tests/graph/graph-logo.test.js
//
// Same vm-sandbox trick as graph-delta.test.js: load the real graph.js with a
// stubbed canvas/document and a chainable no-op d3, then poke the globals. The
// point is the bookkeeping (does the toggle land, does an image register, does
// hasLogo survive an update) — not the pixels, which canvas owns.

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

// Minimal Image stub: records the src it was given and fires onload at once,
// so `setNodeLogos` reaches its "ready" state deterministically.
function ImageStub() {
    this.src = "";
    this.onload = null;
    this.onerror = null;
    Object.defineProperty(this, "srcSetter", { value: true });
}

function freshSandbox() {
    const sandbox = {
        console,
        document: { getElementById: () => canvasStub, addEventListener: noop, documentElement: {}, body: {} },
        window: { devicePixelRatio: 2, innerWidth: 1200, innerHeight: 800, addEventListener: noop },
        requestAnimationFrame: noop, cancelAnimationFrame: noop,
        setTimeout, clearTimeout, Math, Date, JSON, Map, Set, Number, String, Boolean, Array, Object,
        Image: ImageStub,
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
// showLogos is off until Swift says otherwise, and applyFilters carries it.
{
    const sb = freshSandbox();
    check("showLogos defaults to false", run(sb, "filters.showLogos") === false);
    call(sb, "applyFilters", { showLogos: true });
    check("applyFilters turns showLogos on", run(sb, "filters.showLogos") === true);
    call(sb, "applyFilters", { showLogos: false });
    check("applyFilters turns showLogos back off", run(sb, "filters.showLogos") === false);
}

// ---------------------------------------------------------------- case 2
// A filter payload without the key must not clobber the current setting —
// the same "in f" contract every other axis follows.
{
    const sb = freshSandbox();
    call(sb, "applyFilters", { showLogos: true });
    call(sb, "applyFilters", { minDegree: 2 });
    check("an unrelated filter update leaves showLogos alone",
        run(sb, "filters.showLogos") === true);
}

// ---------------------------------------------------------------- case 3
// setNodeLogos registers one entry per id and is additive across calls.
{
    const sb = freshSandbox();
    call(sb, "setNodeLogos", { a: "data:image/png;base64,AAA", b: "data:image/png;base64,BBB" });
    check("setNodeLogos registers both ids", run(sb, "logoImages.size") === 2);
    check("the src is handed to the Image", run(sb, "logoImages.get('a').img.src") === "data:image/png;base64,AAA");

    call(sb, "setNodeLogos", { c: "data:image/png;base64,CCC" });
    check("a second call adds without dropping the first", run(sb, "logoImages.size") === 3);

    // Re-sending the same id must not rebuild the Image (which would restart
    // the decode and flicker the node on every delta push).
    const before = run(sb, "logoImages.get('a').img");
    call(sb, "setNodeLogos", { a: "data:image/png;base64,AAA" });
    check("re-sending an unchanged id reuses the existing Image",
        run(sb, "logoImages.get('a').img") === before);
}

// ---------------------------------------------------------------- case 4
// hasLogo survives a full update and a delta update, like every other field.
{
    const sb = freshSandbox();
    call(sb, "updateGraph", {
        nodes: [node("a", "company", "h1", { hasLogo: true }), node("b", "tool", "h2")],
        links: [],
    });
    check("hasLogo survives updateGraph",
        run(sb, "nodes.find(n => n.id === 'a').hasLogo") === true &&
        run(sb, "!nodes.find(n => n.id === 'b').hasLogo") === true);

    run(sb, "nodes.forEach((n, i) => { n.x = 100 + i * 37; n.y = 200 - i * 11; });");
    call(sb, "updateGraphDelta", {
        added: [], updated: [node("b", "tool", "h3", { hasLogo: true })], removed: [],
        isFull: false,
    });
    check("a delta can turn hasLogo on for an existing node",
        run(sb, "nodes.find(n => n.id === 'b').hasLogo") === true);
    check("the updated node kept its position",
        run(sb, "nodes.find(n => n.id === 'b').x") === 137);
}

console.log(failures === 0 ? "\nAll graph logo checks passed." : `\n${failures} check(s) FAILED.`);
process.exit(failures === 0 ? 0 : 1);
