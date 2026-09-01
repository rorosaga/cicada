#!/usr/bin/env node
//
// Regression net for a Devin PR #23 review finding on G84b (graph.js drag
// deceleration): dragVX/dragVY used to retain the last movement delta
// INDEFINITELY. Repro: grab a node, move it, PAUSE for a second while still
// holding the button (no mousemove events fire during a stationary hold, so
// the EMA velocity estimate is simply never updated), then release — the
// stationary node launched off in the direction you were moving a second
// ago. Worse than the original "stops dead" behavior because it's surprising
// rather than merely inert.
//
// The fix is `seededDragVelocity(lastSampleTime, now, vx, vy)` in graph.js —
// a pure function, extracted specifically so this is testable without a live
// DOM/pointer pipeline: it decides what velocity a release RIGHT NOW should
// actually seed, zeroing it whenever the last recorded move sample is older
// than DRAG_STALE_MS. Run with:
//
//     node app/CicadaApp/Tests/graph/graph-drag-velocity.test.js
//
// Not part of `swift test` (SwiftPM's test target is Tests/CicadaAppTests);
// this is a plain node script, same harness shape as the other Tests/graph/*
// scripts. Graph.js's actual mouse-event wiring (onMouseDown/Move/Up) is not
// exercised here — see the task report for the manual drag-and-pause check.

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
        // Real graph.js code (onMouseDown/Move/Up) reads `performance.now()`,
        // but this test only calls the pure `seededDragVelocity` helper
        // directly, never those handlers — this stub exists purely so
        // loading the whole file doesn't throw if that ever changes.
        performance: { now: () => 0 },
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

let failures = 0;
const check = (label, cond) => {
    console.log((cond ? "PASS " : "FAIL ") + label);
    if (!cond) failures += 1;
};

const sb = freshSandbox();
const staleMs = run(sb, "DRAG_STALE_MS");
check("DRAG_STALE_MS is a small, sane window (0 < x <= 500ms)", staleMs > 0 && staleMs <= 500);

const seeded = (lastSampleTime, now, vx, vy) =>
    run(sb, `seededDragVelocity(${JSON.stringify(lastSampleTime)}, ${now}, ${vx}, ${vy})`);

// ---------------------------------------------------------------- case 1
// A fresh sample (the pointer moved just before release) passes the
// tracked velocity through unchanged — this is the "genuine flick throws"
// half of the contract.
{
    const r = seeded(1000, 1000 + staleMs / 2, 3.5, -2.1);
    check("fresh sample: vx passed through unchanged", r.vx === 3.5);
    check("fresh sample: vy passed through unchanged", r.vy === -2.1);
}

// A sample exactly at the boundary (dt === DRAG_STALE_MS) is still fresh —
// only STRICTLY older than the window goes stale.
{
    const r = seeded(1000, 1000 + staleMs, 4, 4);
    check("boundary sample (dt === DRAG_STALE_MS) is still fresh", r.vx === 4 && r.vy === 4);
}

// ---------------------------------------------------------------- case 2
// A stale sample — this IS the bug repro: grab, move (sets vx/vy AND a
// sample timestamp), pause past the window, release. Must zero regardless
// of how large the stale vx/vy still are.
{
    const r = seeded(1000, 1000 + staleMs + 1, 3.5, -2.1);
    check("stale sample (just past the window): vx zeroed", r.vx === 0);
    check("stale sample (just past the window): vy zeroed", r.vy === 0);
}
{
    // The exact repro from the review: a real flick's velocity (large),
    // then a full second of holding still before release.
    const r = seeded(1000, 2000, 40, -25);
    check("1s stale hold with a large tracked velocity still zeroes", r.vx === 0 && r.vy === 0);
}

// ---------------------------------------------------------------- case 3
// lastSampleTime === null (never moved — e.g. a fresh grab with no
// mousemove yet, or the post-release reset) must also zero, not throw or
// pass through whatever vx/vy happen to be.
{
    const r = seeded(null, 12345, 9, 9);
    check("null lastSampleTime (never moved) zeroes", r.vx === 0 && r.vy === 0);
}

// ---------------------------------------------------------------- case 4
// A plain click (never crossed the drag-threshold, so vx/vy are still their
// reset 0) must keep releasing motionless — the pre-existing behavior this
// fix must not disturb.
{
    const r = seeded(1000, 1000 + 5, 0, 0);
    check("a plain click (0 velocity) stays at 0 regardless of freshness", r.vx === 0 && r.vy === 0);
}

console.log(failures === 0 ? "\nAll graph drag-velocity checks passed." : `\n${failures} check(s) FAILED.`);
process.exit(failures === 0 ? 0 : 1);
