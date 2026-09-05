// The graph canvas in light mode (Track P, recent-work #1). `graph.js` baked
// the dark palette into every drawn colour — node labels "#ECEDF2", tooltip
// grounds "rgba(14, 15, 20, …)", contextless edges "#262A33" — while the
// canvas itself is transparent (index.html:11) and PR #49/#60 shipped a real
// Light mode. Flip to Light and the product's front door had unreadable
// labels on near-black cards floating over a light window.
//
// Two invariants, both cheap: every key resolves in BOTH palettes (a half-
// filled table is a mid-draw `undefined` fillStyle, i.e. a silently black
// canvas), and an unknown mode falls back rather than throwing.
//
// G109 rule, restated: a theme change is a REPAINT. `setTheme` must never
// touch the simulation — no `alpha`, no `alphaTarget`, no `restart()`. The
// release path never bumps alpha, and a colour swap is not even a release.
const assert = require("assert");
const { loadGraph, synthetic, SIZES } = require("./graph-physics-harness");

const { sandbox, get, call } = loadGraph();
call("updateGraph", synthetic(SIZES.small));
const sim = get("simulation");
sim.stop();
for (let t = 0; t < 60; t++) sim.tick();

const palettes = get("PALETTES");
const modes = Object.keys(palettes);
assert.deepStrictEqual(modes.sort(), ["dark", "light"], "exactly two palettes");

const keys = Object.keys(palettes.dark).sort();
assert.ok(keys.length >= 7, `expected the full palette, got ${keys.join(",")}`);
for (const mode of modes) {
    assert.deepStrictEqual(Object.keys(palettes[mode]).sort(), keys, `${mode} is missing a key`);
    for (const k of keys) {
        const v = palettes[mode][k];
        assert.ok(typeof v === "string" && v.length > 0, `${mode}.${k} must be a colour string`);
        assert.ok(/^(#|rgba?\()/.test(v), `${mode}.${k} is not a CSS colour: ${v}`);
    }
}
assert.notDeepStrictEqual(palettes.dark, palettes.light, "the two palettes must actually differ");

// Default is dark (what the page loads with, before Swift pushes anything).
assert.strictEqual(get("PALETTE"), palettes.dark);

sandbox.setTheme("light");
assert.strictEqual(get("PALETTE"), palettes.light);
assert.strictEqual(get("themeMode"), "light");

// Unknown / null / undefined fall back to dark instead of throwing mid-draw.
sandbox.setTheme("solarized");
assert.strictEqual(get("PALETTE"), palettes.dark, "an unknown mode falls back to dark");
sandbox.setTheme(null);
assert.strictEqual(get("PALETTE"), palettes.dark);

// A contextless edge takes the palette's edge colour, in both modes.
sandbox.setTheme("light");
assert.strictEqual(get("contextColor(null)"), palettes.light.edge);
sandbox.setTheme("dark");
assert.strictEqual(get("contextColor(null)"), palettes.dark.edge);
// A CONTEXT-coloured edge is identity, not theme — unchanged by the flip.
const before = get("contextColor('engineering')");
sandbox.setTheme("light");
assert.strictEqual(get("contextColor('engineering')"), before);

// R10: repaint only. Alpha is untouched across a flip.
sandbox.setTheme("dark");
const alphaBefore = sim.alpha();
sandbox.setTheme("light");
sandbox.setTheme("dark");
assert.strictEqual(sim.alpha(), alphaBefore, "a theme change must never reheat the simulation");

console.log("All graph theme checks passed.");
