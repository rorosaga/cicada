// Cicada graph view — HTML5 canvas renderer backed by d3-force.
//
// History: this used to be an SVG renderer that ran the d3-force simulation
// directly against <circle> and <text> elements. That works fine for a few
// hundred nodes but at 1500+ nodes the per-tick DOM mutation cost dominates,
// the Gaussian blur filter on every node turns the GPU into a space heater,
// and the default alpha decay never lets the simulation settle. This file
// replaces all of that with a canvas pipeline following the same pattern as
// Bostock's canonical @d3/force-directed-graph-canvas Observable and
// vasturiano/force-graph. d3-force stays in place as the layout engine —
// it does not care what you render with.
//
// v2 adds focus/ego mode, three-tier semantic zoom, hub-anchored layout,
// status-opacity + pending-pulse preattentive encodings, and incremental
// updateGraph (position preservation) so post-sleep refreshes settle instead
// of exploding. The canvas + quadtree pipeline is untouched.

// MUST stay byte-identical to CicadaTheme.entityColor(for:) — Tailwind-400-band
// hues on the darker #111213 graphite base (Direction D, DS-1) so all 8 pop and clear ~4.5:1+ contrast.
const typeColors = {
    person:   "#5AA8FF",
    project:  "#B57BFF",
    company:  "#FF8A3D",
    concept:  "#3BD97A",
    tool:     "#2DD4BF",
    deadline: "#FF5C5C",
    skill:    "#F2C744",
    location: "#AEB6C4",
    media:    "#F65BA6",
    hub:      "#E0A93A",   // deeper amber gold — distinct from skill gold + project purple
    directory:"#7AA0C4",   // slate blue-gray "Finder folder" — mirrors CicadaTheme.entityColor(.directory)
    repo:     "#5B6472",   // dark slate — subtle, read-time synthetic node (backlog G-repo)
    unknown:  "#9BA1AE",
};

// Soft per-type cluster anchors. These are only used by the xType/yType
// forces at low strength, so the layout still obeys link and charge forces
// — the anchors just nudge same-type nodes toward each other. Obsidian-like
// grouping without a Louvain pass. Nodes that orbit a hub use hubGravity
// instead (see startSimulation) and ignore these anchors.
// Type-cluster anchor positions (world units). Spread ~1.5x wider than the
// original ±300 ring so the per-type clusters sit farther apart and read as
// distinct groups instead of one clump; the soft anchor strength + center pull
// still keep them coherent. The "fit" zoom reframes to whatever spread is used.
const typeClusterPositions = {
    person:   [   0, -450],
    project:  [ 420, -150],
    company:  [ 270,  360],
    concept:  [-270,  360],
    tool:     [-420, -150],
    deadline: [   0,  450],
    skill:    [ 450,  150],
    location: [-450,  150],
    media:    [ -90, -540],
    directory:[-450, -360],
    repo:     [ 540, -360],
    hub:      [   0,    0],
};

// Context color mirror of CicadaTheme.contextColor (claim layer §2a). Known
// core contexts are hard-coded; unknown ones hash to a stable HSL hue so the
// graph never flickers. Used to color edge strokes + facet node fills.
const CONTEXT_COLORS = {
    engineering:   "#2DD4BF",   // = tool
    family:        "#F65BA6",   // = media
    philosophical: "#B57BFF",   // = project
    career:        "#FF8A3D",   // = company
    cross:         "#F2C744",   // = skill (cross-context bridge stays loudest)
    general:       "#7A8290",
};
const OBSERVER_BADGE_COLORS = {
    agent:    "#8896FF",   // the pre-G137 accent, frozen — an observer's identity, not the theme (R-M8)
    rodrigo:  "#5AA8FF",   // blue (person)
    external: "#F65BA6",   // pink (media)
};

// Track P — the canvas is transparent (index.html), so only the DRAWN colours
// were dark-locked. Two tables, one key per drawn surface, each value the
// exact `CicadaTheme.Dark`/`.Light` twin so the chrome and the canvas agree.
// `labelShadow` is a HALO, not a drop shadow: on a light ground a black blur
// around dark text is what made light mode unreadable, so the light value is
// the background colour instead. `edge` takes `borderLight` in BOTH modes
// (Direction D, R-DS2): `border` is now the opaque twin of the faint resting
// ring (#E3E3E1 on #F7F7F5, #222324 on #111213), invisible as a 1px line in
// light and ~1.2:1 in dark, while `borderLight` keeps the edges' measured
// 1.4–1.5:1.
//
// CONTEXT_COLORS and OBSERVER_BADGE_COLORS above are deliberately NOT in here:
// they are IDENTITY colours (which context, which observer), and an identity
// that changes hue with the theme stops being an identity.
const PALETTES = {
    dark: {
        label:       "#F5F5F6",                    // = CicadaTheme.Dark.textPrimary
        labelShadow: "rgba(0, 0, 0, 0.85)",
        plate:       "rgba(17, 18, 19, 0.85)",     // = Dark.background
        plateStrong: "rgba(17, 18, 19, 0.92)",     // = Dark.background
        plateText:   "#C7CBD6",
        edge:        "#323334",                    // = Dark.borderLight
        nodeStroke:  "#FFFFFF",
    },
    light: {
        label:       "#141415",                    // = CicadaTheme.Light.textPrimary
        labelShadow: "rgba(247, 247, 245, 0.95)",  // = Light.background, as a halo
        plate:       "rgba(255, 255, 255, 0.92)",  // = Light.surface
        plateStrong: "rgba(255, 255, 255, 0.96)",  // = Light.surface
        plateText:   "#38393C",                    // = Light.textSecondary
        edge:        "#CFCFCE",                    // = Light.borderLight
        nodeStroke:  "#141415",                    // = Light.textPrimary
    },
};
let themeMode = "dark";
let PALETTE = PALETTES.dark;

// Pushed from `GraphView.updateNSView` the same way setPanToggle /
// setHoverSuppressed are. R10: this is a REPAINT — it swaps a table and asks
// for a frame. It must never touch `simulation`, `alpha`, `alphaTarget` or
// `restart()` (G109: the release path never bumps alpha; a colour change is
// not even a release, and a re-layout would throw away every node position
// the person has dragged). An unknown mode falls back to dark rather than
// leaving `undefined` in a fillStyle, which paints a silently black canvas.
function setTheme(mode) {
    const next = PALETTES[String(mode)] ? String(mode) : "dark";
    if (next === themeMode) return;
    themeMode = next;
    PALETTE = PALETTES[next];
    scheduleRedraw();
}

function hashHue(str) {
    let h = 0;
    for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0;
    return Math.abs(h) % 360;
}
function contextColor(context) {
    if (!context) return PALETTE.edge;   // contextless edge = the theme border
    if (CONTEXT_COLORS[context]) return CONTEXT_COLORS[context];
    return `hsl(${hashHue(context)}, 55%, 68%)`;
}
function observerBadgeColor(wire) {
    if (!wire || wire === "agent") return OBSERVER_BADGE_COLORS.agent;
    if (wire.startsWith("external:")) return OBSERVER_BADGE_COLORS.external;
    // G117 R2: the wire protocol reserves exactly "agent" and "external:" —
    // anything else is the owner, whatever slug onboarding resolved (the
    // legacy "rodrigo", the fresh-bank keyword "owner", or a name-derived
    // slug like "bob-example"). A dictionary-miss fallback to "external"
    // used to mislabel every one of those as External the moment the
    // resolved value stopped being the bare literal "rodrigo".
    return OBSERVER_BADGE_COLORS.rodrigo;
}

const MIN_ZOOM = 0.1;               // 2026-10-15: 0.2 -> 0.1, so a 5k-node graph with bigger dots still fits
const MAX_ZOOM = 6.0;
const LABEL_MIN_SCREEN_RADIUS = 6;  // only label nodes whose on-screen radius clears this
const DRAG_CLICK_THRESHOLD = 4;     // pixels of movement before a mousedown becomes a drag
const DOUBLE_CLICK_MS = 320;        // window for the second click of a double-click

// Semantic-zoom tiers. Past HUBS_ONLY observer badges draw; past NODE_LABELS logos draw; past EDGE_LABELS edge labels
// appear at link midpoints. Every link draws at every zoom and node names fade in by on-screen size (2026-10-15,
// `drawAmbientLabels`).
const ZOOM_HUBS_ONLY   = 0.45;
const ZOOM_NODE_LABELS = 1.2;
const ZOOM_EDGE_LABELS = 2.2;

const LABEL_BUDGET = 200;           // max node labels rendered per frame

const STATUS_ALPHA = { active: 0.92, decaying: 0.5, archived: 0.28, dropped: 0.0 };
// Owner ruling 2026-10-20: a page only an import made, not yet mentioned (`quiet` on the node). Its fill fades to
// QUIET_FILL_ALPHA and a hairline ring in its own type hue keeps the dot findable — depth is a ring (DR-9), never the
// accent (DR-5), and the type hues do not move (DR-8). A hover still lights it fully.
const QUIET_FILL_ALPHA = 0.28;
const QUIET_RING_ALPHA = 0.8;
const LINK_ALPHA = 0.55;            // a neutral link at rest (the theme's edge colour)
const LINK_ALPHA_CONTEXT = 0.22;    // a link in its context's hue at rest
// Link width (G109 proportion pass, owner 2026-10-15: "the lines connecting nodes are too big compared to the size of
// the nodes, they should be super thin"). At rest a link is LINK_WIDTH_OF_DOT of the smallest dot's on-screen
// diameter, never wider than LINK_WIDTH_MAX_PT: a hairline that stays well under the dots at every zoom. Thinner than
// one device pixel it is drawn one device pixel wide at a proportionally lower alpha (`linkStroke`), which is what a
// sub-pixel line looks like anyway, minus the smear. A link a hover or a focus lights is LINK_LIT_PT wide.
const LINK_WIDTH_OF_DOT = 0.12;
const LINK_WIDTH_MAX_PT = 0.75;
const LINK_LIT_PT = 1;

const PULSE_RING_FROM = 1.5;        // screen px past the dot where the pulse ring starts ...
const PULSE_RING_TRAVEL = 4;        // ... and how far it travels out before it fades
const PULSE_COLOR = "#FFCB57";      // amber attention color for pending pulse (= CicadaTheme.pendingPulse)

// Surface uncaught JS errors to the Swift side — a silent exception here
// renders as an inexplicably blank canvas otherwise.
window.onerror = (message, source, line, col, error) => {
    try {
        window.webkit.messageHandlers.cicada.postMessage(
            JSON.stringify({
                type: "jsError",
                message: String(message),
                source: String(source || ""),
                line: line || 0,
                col: col || 0,
                stack: error && error.stack ? String(error.stack) : "",
            })
        );
    } catch (e) { /* no handler (standalone browser) */ }
};

// DS-3a — the one sender for the messages Swift answers as page actions. try/catch because the page
// also runs standalone in a browser (no handler), exactly like the posts above.
function postToSwift(msg) {
    try { window.webkit.messageHandlers.cicada.postMessage(JSON.stringify(msg)); } catch (e) { /* standalone */ }
}

// ---------- Module-level state ----------

let canvas, ctx;
let width = 0;
let height = 0;
let dpr = 1;

let simulation;
let nodes = [];
let links = [];
let visibleNodes = [];
let visibleLinks = [];
let neighborsById = new Map();  // id -> Set<id> for hover highlighting + focus BFS

let memberToHub = new Map();    // member id -> hub id, for hubGravity force
let hubAnchors = new Map();     // hub id -> [x, y] anchor on the hub ring

// Filter state. enabledTypes/currentMinDegree collapsed into this object so
// the toolbar can push one applyFilters() call covering every dimension.
let filters = {
    types: null,        // null = all types; otherwise Set<string>
    statuses: null,     // null = all except dropped; otherwise Set<string>
    minConfidence: 0,
    tags: null,         // null/empty = no tag filter; otherwise Set<string>
    // G84a: must agree with Swift's default (GraphFilter.swift `minDegree = 0`).
    // This used to default to 1 here while Swift defaulted to 0, so the very
    // first cold paint (before Swift's applyFilters push landed) ran on this
    // stricter default and dropped every zero-degree node until the user
    // touched any filter control. Now both start at "show isolated nodes."
    minDegree: 0,
    contexts: null,     // null = all contexts; otherwise Set<string> — DROPS non-matching edges/facets
    observers: null,    // null = all observers; otherwise Set<string> — DIMS non-matching nodes (kept visible)
    // G59: draw cached brand marks inside the node discs. Off by default —
    // drawImage per node costs real frames on a 1800-node graph, and the
    // colored discs are the primary type signal. Toggled from the Swift
    // filter popover.
    showLogos: false,
};

// G59: id -> { img, ready }. Fed by `setNodeLogos`, which Swift calls with
// base64 data URLs (the webview can't reach the bearer-authenticated API).
// Entries are additive and reused: rebuilding an Image restarts its decode and
// flickers the node on every delta push.
const logoImages = new Map();

function setNodeLogos(payload) {
    const data = typeof payload === "string" ? JSON.parse(payload) : payload;
    let added = 0;
    for (const [id, src] of Object.entries(data || {})) {
        const existing = logoImages.get(id);
        if (existing && existing.img && existing.img.src === src) continue;
        if (typeof Image !== "function") continue;
        const entry = { img: new Image(), ready: false };
        entry.img.onload = () => { entry.ready = true; scheduleRedraw(); };
        entry.img.onerror = () => { logoImages.delete(id); };
        entry.img.src = src;
        logoImages.set(id, entry);
        added += 1;
    }
    if (added) scheduleRedraw();
}

// Focus / ego mode.
let focusNodeId = null;         // ego anchor; null = full graph
let focusHops = 2;
let focusSet = null;            // Set<id> inside the focus neighborhood (incl anchor)

let searchHighlight = null;     // Set<id> from toolbar search, or null

const prevPositions = new Map();// id -> {x,y,vx,vy} carried across updateGraph() calls
let pulsePhase = 0;             // animation clock for pending-item pulse rings
let anyPending = false;         // true if any visible node hasPending — gates the pulse RAF

let transform = d3.zoomIdentity;
let currentZoom;

let hoveredNode = null;
// Shift = pan mode (owner request, 2026-09-02): while Shift is held the pointer
// never picks a node — no hover highlight, no drag — and a press anywhere,
// node or empty space, falls through to d3-zoom's pan. Mouse events carry the
// modifier state, so the mode tracks the key even when the web view never saw
// a keydown (the page is often not first responder while the pointer merely
// hovers); keyup/blur restore the hover pick at the last pointer position
// without waiting for the next move. Releasing Shift mid-drag does not drop
// the node: the drag branch in onMouseMove/onMouseUp runs untouched.
let panModifierHeld = false;
let panToggled = false;         // toolbar toggle (Swift → setPanToggle); sticky twin of Shift
// Hover is suppressed while the entity detail card is open (owner, 2026-09-03:
// "as I move my cursor it still highlights the nodes while an entity page is
// open"). Swift mirrors `selectedEntity != nil` here; clicks still work so a
// second node can be selected, only the hover pick is quiet.
let hoverSuppressed = false;
function setHoverSuppressed(on) {
    hoverSuppressed = !!on;
    if (hoverSuppressed && hoveredNode) { hoveredNode = null; scheduleRedraw(); }
    if (hoverSuppressed && canvas && !panModifierHeld) canvas.style.cursor = "";
}
function setPanToggle(on) {
    panToggled = !!on;
    setPanMode(panToggled);
}
// DS-3a R-DG9 — the entity whose column is open. Swift pushes it on every change (`GraphJS.setSelectedNode`).
// It draws a neutral ring (draw(), beside the search ring) and is kept in view after every resize: the
// column takes up to 560 pt of the canvas, and a node clicked on its right half would otherwise vanish.
// Only the zoom TRANSFORM moves, never its scale, and nothing here touches `simulation` (G109).
let selectedNodeId = null;
const KEEP_IN_VIEW_PAD = 80;   // px inside the canvas edge, the same margin revealNode fits with
// A G123 reveal owns the transform while its transition runs (revealNode sets this, its end clears it).
// `revealEntity` selects AND reveals in one update, and d3 transitions of one name are exclusive — a
// keep-in-view pan started beside the reveal (or `zoom.transform` on a resize, which interrupts) would
// cancel the zoom to the neighbourhood. The reveal's end re-checks instead (R-DG9).
let revealing = false;
let revealSeq = 0;             // which reveal holds `revealing` (revealNode)
function setSelectedNode(id) {
    selectedNodeId = id ? String(id) : null;
    const shown = selectedNodeId ? ensureVisible(selectedNodeId, true) : false;
    scheduleRedraw();
    return shown;
}
function axisShift(s, extent) {
    const pad = Math.min(KEEP_IN_VIEW_PAD, extent / 2);
    if (s < pad) return pad - s;
    if (s > extent - pad) return (extent - pad) - s;
    return 0;
}
function ensureVisible(id, animate) {
    const n = visibleNodes.find((x) => x.id === id);
    if (!n || n.x == null || width <= 0 || height <= 0) return false;
    if (revealing) return true;   // the reveal lands on it, then re-checks (revealNode)
    const dx = axisShift(n.x * transform.k + transform.x, width);
    const dy = axisShift(n.y * transform.k + transform.y, height);
    if (dx === 0 && dy === 0) return true;
    const t = d3.zoomIdentity.translate(transform.x + dx, transform.y + dy).scale(transform.k);
    if (currentZoom) {
        const sel = d3.select(canvas);
        if (animate) sel.transition().duration(250).call(currentZoom.transform, t);
        else sel.call(currentZoom.transform, t);
    } else {
        transform = t;   // headless (no zoom behaviour attached): apply directly, as revealNode does
    }
    return true;
}
let lastPointer = null;         // { sx, sy } of the last mousemove, for the keyup re-pick
function setPanMode(on) {
    if (on === panModifierHeld) return;
    panModifierHeld = on;
    if (!canvas) return;
    if (on) {
        if (hoveredNode) { hoveredNode = null; scheduleRedraw(); }
        canvas.style.cursor = "grab";
        return;
    }
    const picked = lastPointer ? pickNode(lastPointer.sx, lastPointer.sy) : null;
    if (picked !== hoveredNode) { hoveredNode = picked; scheduleRedraw(); }
    canvas.style.cursor = picked ? "pointer" : "";
}
let draggingNode = null;
let pressStart = null;          // { x, y } screen coords of mousedown for click-vs-drag
let lastClickTime = 0;          // for double-click detection
let lastClickId = null;

// G84b: throw-velocity tracking for the dragged node. While fx/fy are set,
// d3 zeroes the node's OWN vx/vy every tick (it's pinned, not physically
// simulated), so at release vx/vy are exactly 0 and a throw is impossible by
// construction unless we seed them ourselves from the pointer's own motion.
// `dragVX`/`dragVY` are an exponentially-smoothed world-units-per-tick
// velocity estimate, sampled in onMouseMove and consumed (then reset) in
// onMouseUp. Timestamps are `performance.now()` (monotonic — immune to
// system-clock adjustments mid-gesture), never `Date.now()`.
let dragVX = 0;
let dragVY = 0;
let lastDragSample = null;      // { t, x, y } world coords + performance.now() at last sample
const DRAG_VELOCITY_SMOOTHING = 0.35;  // weight given to each new sample (EMA)
const SIM_TICK_MS = 1000 / 60;         // d3's timer runs on rAF, ~60fps
// Devin review (PR #23): dragVX/dragVY used to retain the last movement delta
// indefinitely — grab a node, move it, PAUSE while still holding (no more
// mousemove events fire, so the EMA is simply never updated), then release,
// and the stationary node launched off in the direction you were moving a
// second ago. Worse than the pre-G84b stop-dead behavior because it's
// surprising rather than merely inert. DRAG_STALE_MS is the "still moving"
// vs "parked" cutoff, checked at RELEASE time against how long it's been
// since the last recorded move sample (not against the next move's delta,
// which is exactly why a stall-then-release used to slip through).
const DRAG_STALE_MS = 100;             // ~6 ticks at 60fps; a real flick's last sample is always fresher than this

let hubsOnlyMode = false;       // set true when the payload is the hubs-only tier

let needsRedraw = false;
let rafHandle = null;

// Audit 2026-10-02 A07: the page is told when it is on screen (`setGraphActive`, from GraphView — the
// Graph tab selected and its window not occluded, minimized or hidden). Inactive, no frame is requested
// and the d3 timer is stopped; `simSuspended` remembers a simulation that was still moving so resume
// continues it at its own alpha — never a reheat.
let graphActive = true;
let simSuspended = false;
// A07: a pulse-only frame (physics settled, a pending node on screen) runs on a timer at ~30 fps, and
// the ring's phase follows elapsed time, so it keeps the ~1 s period the per-frame step gave at 60 fps.
const PULSE_FRAME_MS = 1000 / 30;
const PULSE_CYCLES_PER_SECOND = 0.96;
let pulseTimer = null;

// ---------- Field accessors (defensive: server fields may be absent) ----------
//
// The new GraphNode fields land in a later backend wave. Until then they are
// undefined on the wire; the wire is camelCase today but we accept snake_case
// too so the graph degrades gracefully either way.

function nodeIsHub(n) {
    return Boolean(n.isHub ?? n.is_hub ?? (n.type === "hub"));
}

function nodeHasPending(n) {
    return Boolean(n.hasPending ?? n.has_pending);
}

function nodeIsQuiet(n) {
    return Boolean(n.quiet);
}

function nodeMemberCount(n) {
    return Number(n.memberCount ?? n.member_count ?? 0);
}

function nodeHubId(n) {
    return n.hubId ?? n.hub_id ?? null;
}

// Server degree is authoritative for sizing once present; otherwise the
// degree computed locally from links (computeDegree) is used. Both live on
// n.degree, so this just reads it.
function nodeDegree(n) {
    return Number(n.degree || 0);
}

// ---------- Claim-layer field accessors (§2) ----------

function nodeIsFacet(n) {
    return Boolean(n.isFacet ?? n.is_facet);
}

function nodeParentId(n) {
    return n.parentId ?? n.parent_id ?? null;
}

function nodeContext(n) {
    return n.context ?? null;
}

function nodeObservers(n) {
    const o = n.observers;
    return Array.isArray(o) ? o : [];
}

function nodeContexts(n) {
    const c = n.contexts;
    return Array.isArray(c) ? c : [];
}

// A node "matches" the observer filter if any of its observers is selected.
// Facet nodes inherit their parent's match via their own (parent-copied)
// observer list when present; if a node has no observer info it matches (so the
// legacy graph never dims to nothing).
function nodeMatchesObservers(n) {
    if (!filters.observers) return true;
    const obs = nodeObservers(n);
    if (!obs.length) return true;
    return obs.some(o => filters.observers.has(o));
}

// A node passes the context filter if it has no context info, OR is a facet in
// a selected context, OR (for a parent node) has at least one selected context.
function nodeMatchesContexts(n) {
    if (!filters.contexts) return true;
    if (nodeIsFacet(n)) {
        const c = nodeContext(n);
        return c ? filters.contexts.has(c) : true;
    }
    const ctxs = nodeContexts(n);
    if (!ctxs.length) return true;
    return ctxs.some(c => filters.contexts.has(c));
}

// ---------- Init ----------

// Apply the initial centering transform exactly once, the first time the
// canvas has real dimensions. Manual zoom/pan afterwards is never overridden.
let hasCentered = false;
// First-load fit (owner, 2026-09-03: "the zoomed-out look should be the
// default"): centerOnce() only places the origin; the graph's real extent is
// unknown until the cold layout has spread, so the first updateGraph arms a
// one-shot fit that fires after INITIAL_FIT_TICKS ticks. Later data pushes
// (deltas, bank switches with a warm prevPositions) never re-fit — the
// person's own zoom is the state to keep (the WKWebView now survives tab
// switches, see ContentView.detailContent).
const INITIAL_FIT_TICKS = 90;
let initialFitTicksLeft = -1;   // -1 = not armed
function armInitialFit() { initialFitTicksLeft = INITIAL_FIT_TICKS; }
function tickInitialFit() {
    if (initialFitTicksLeft < 0) return;
    if (--initialFitTicksLeft > 0) return;
    initialFitTicksLeft = -1;
    fitGraph(true);
}
// G109 (2026-10-14): a layout can now end before INITIAL_FIT_TICKS (settleCheck; a 12-node graph stops near step 80),
// so the layout's end runs a fit still pending. Left armed, it fired on the next restart — mid-drag.
function finishInitialFit() {
    if (initialFitTicksLeft < 0) return;
    initialFitTicksLeft = -1;
    fitGraph(true);
}

// QA 2026-10-16 ("not centred on first show": the cluster top-left, the right third empty, the control bar over a
// label). The first fit can run while the canvas still has a size it is about to lose — the page not on screen yet
// (the WKWebView outlives tab switches, and entering the demo switches banks from Settings), or a column still
// opening — so the graph sits in the corner of the view it finally gets. Until something else moves the view (the
// person's zoom or pan, a reveal, a focus), the automatic fit is still the view: a resize fits again, at once (the
// resize is the motion). `autoFit` is the transform that fit set; the view is still the fit's while `transform`
// equals it.
let autoFit = null;
function viewIsStillTheFit() {
    if (!autoFit || !transform) return false;
    const close = (a, b) => Math.abs(a - b) <= 0.5 + 1e-6 * Math.abs(b);
    return close(transform.x, autoFit.x) && close(transform.y, autoFit.y) && Math.abs(transform.k - autoFit.k) < 1e-6;
}
// The fit a resize applies, or null when the view is the person's (or nothing can be fitted).
function refitForResize() {
    if (selectedNodeId || !viewIsStillTheFit() || !visibleNodes.length) return null;
    const t = transformForNodes(visibleNodes, FIT_PAD);
    if (!t) return null;
    autoFit = t;
    return t;
}
function centerOnce() {
    if (hasCentered || width <= 0 || height <= 0 || !currentZoom) return;
    hasCentered = true;
    d3.select(canvas).call(
        currentZoom.transform,
        d3.zoomIdentity.translate(width / 2, height / 2).scale(0.6),
    );
}

// The WKWebView is created with a zero frame and only gets its real size from the SwiftUI layout pass
// AFTER this script ran — without centerOnce here the origin stays at the top-left corner and the whole
// graph renders off-canvas (the "blank graph" bug). DS-3a: the entity column narrows the canvas, so
// the open node is kept in view on every resize — without an animation, because the resize itself is
// already the column's motion.
function onResize() {
    resizeCanvas();
    centerOnce();
    if (selectedNodeId) ensureVisible(selectedNodeId, false);
    const refit = refitForResize();
    if (refit && currentZoom) d3.select(canvas).call(currentZoom.transform, refit);
    scheduleRedraw();
}

// Shift is the momentary pan. Esc: an ego focus is graph.js's own and closes first; otherwise the page
// decides what Esc closes (the find field, the Legend, the Reader, the column — DR-28), so it is posted
// and prevented here — WebKit must not ALSO forward it up the responder chain, or one press would close
// two things (DS-3a R-DG11).
function onKeyDown(e) {
    if (e.key === "Shift") setPanMode(true);
    if (e.key !== "Escape") return;
    e.preventDefault();
    if (focusNodeId) { clearFocus(); return; }
    postToSwift({ type: "escape" });
}

function init() {
    canvas = document.getElementById("graph");
    ctx = canvas.getContext("2d");

    resizeCanvas();
    window.addEventListener("resize", onResize);

    // Zoom/pan. We drive d3.zoom on the canvas element and store the result
    // in a local transform object; draw() applies that transform manually
    // in world space via ctx.translate/scale. We do NOT set a DOM transform
    // attribute anymore — there is no DOM tree under the canvas to move.
    currentZoom = makeZoom();
    d3.select(canvas).call(currentZoom);

    // Initial centering transform — put origin in the middle of the canvas
    // at a slightly-zoomed-out starting scale so the whole graph is visible.
    // No-op while the canvas is still 0x0; the resize listener retries.
    centerOnce();

    // Suppress d3's default double-click zoom; double-click is our focus
    // gesture now (handled in onMouseUp, not here).
    d3.select(canvas).on("dblclick.zoom", null);

    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("keyup", (e) => {
        if (e.key === "Shift" && !panToggled) setPanMode(false);
    });
    // A Cmd-Tab or app switch while Shift is down never delivers the keyup.
    // A09: and a drag whose release never arrives (an app switch mid-drag) ends here too.
    window.addEventListener("blur", onWindowBlur);

    wireMouseEvents();

    // Signal ready. The Swift side is waiting on this before pushing data.
    try {
        window.webkit.messageHandlers.cicada.postMessage(
            JSON.stringify({ type: "graphReady" })
        );
    } catch (e) {
        console.log("graphReady (no handler):", e);
    }
}

function resizeCanvas() {
    dpr = window.devicePixelRatio || 1;
    width = canvas.clientWidth || window.innerWidth;
    height = canvas.clientHeight || window.innerHeight;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    // Reset the transform stack and apply the HiDPI scale once. draw()
    // applies the pan/zoom transform on top of this on every frame.
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

// ---------- Zoom actions (called from Swift) ----------

function zoomIn() {
    d3.select(canvas).transition().duration(250).call(currentZoom.scaleBy, 1.4);
}

function zoomOut() {
    d3.select(canvas).transition().duration(250).call(currentZoom.scaleBy, 0.7);
}

// zoomReset re-centers at the default scale. fitGraph fits the whole graph to
// the viewport — what the toolbar "Fit" button wants. zoomReset is kept for
// the existing Swift zoomAction (.reset) call path.
function zoomReset() {
    d3.select(canvas).transition().duration(400).call(
        currentZoom.transform,
        d3.zoomIdentity.translate(width / 2, height / 2).scale(0.6),
    );
}

const FIT_PAD = 60;                   // screen px round the fitted graph
function fitGraph(automatic = false) {
    if (!currentZoom) return;   // headless (no zoom behaviour attached), as revealNode/ensureVisible handle it
    if (!visibleNodes.length) { zoomReset(); return; }
    const t = transformForNodes(visibleNodes, FIT_PAD);
    if (!t) { zoomReset(); return; }
    // The first-load fit is remembered so a resize can follow it (`refitForResize`); a fit the person asked for is
    // theirs, and so is the view after it.
    autoFit = automatic ? t : null;
    d3.select(canvas).transition().duration(400).call(currentZoom.transform, t);
}

// Build a zoom transform that fits the bbox of the given nodes into the
// viewport with `pad` screen pixels of margin. Returns null if degenerate.
function transformForNodes(nodeList, pad) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of nodeList) {
        if (n.x == null || n.y == null) continue;
        const r = nodeRadius(n);
        if (n.x - r < minX) minX = n.x - r;
        if (n.y - r < minY) minY = n.y - r;
        if (n.x + r > maxX) maxX = n.x + r;
        if (n.y + r > maxY) maxY = n.y + r;
    }
    if (!isFinite(minX)) return null;
    const bw = Math.max(maxX - minX, 1);
    const bh = Math.max(maxY - minY, 1);
    const k = Math.max(
        MIN_ZOOM,
        Math.min(MAX_ZOOM, Math.min((width - pad * 2) / bw, (height - pad * 2) / bh)),
    );
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    return d3.zoomIdentity
        .translate(width / 2, height / 2)
        .scale(k)
        .translate(-cx, -cy);
}

// ---------- Data ingest ----------

// Incremental update: snapshot the current sim's positions, swap in the new
// node/link arrays, then re-seed each node — known nodes keep their previous
// position, genuinely-new nodes get seeded near their hub/type anchor. The
// sim reheats low (0.3) when we had prior positions so a post-sleep refresh
// of a handful of nodes settles instead of re-laying-out from random. This is
// the fix for "post-sleep layout explodes."
function updateGraph(dataStr) {
    const data = typeof dataStr === "string" ? JSON.parse(dataStr) : dataStr;

    resizeCanvas();
    centerOnce();

    // 1. snapshot positions of the current sim before we replace anything.
    for (const n of nodes) {
        if (n.x != null) prevPositions.set(n.id, { x: n.x, y: n.y, vx: n.vx || 0, vy: n.vy || 0 });
    }

    nodes = data.nodes || [];
    links = data.links || [];
    hubsOnlyMode = Boolean(data.hubsOnly ?? data.hubs_only);

    computeDegree();
    buildHubIndex();

    // 2. seed positions: reuse previous for known nodes; place genuinely-new
    // nodes near their hub or type anchor.
    beginSeeding();
    const fresh = new Set();
    let carried = 0;
    for (const n of nodes) {
        const p = prevPositions.get(n.id);
        if (p) {
            carried += 1;
            n.x = p.x; n.y = p.y; n.vx = 0; n.vy = 0;
        } else {
            const s = seedPositionFor(n);
            n.x = s.x; n.y = s.y; n.vx = 0; n.vy = 0;
            fresh.add(n.id);
        }
    }

    // Review r1 #3: a full push replaces every node object. A drag in progress follows the live object for its id
    // (its pin moves with it), so no later hold or release acts on a replaced one; a drag whose node left ends.
    if (draggingNode) {
        const live = nodes.find(n => n.id === draggingNode.id);
        if (live) {
            live.x = draggingNode.x; live.y = draggingNode.y;
            live.fx = draggingNode.fx; live.fy = draggingNode.fy;
            live.vx = 0; live.vy = 0;
            draggingNode = live;
        } else {
            cancelInteraction();
        }
    }

    rebuildVisible();
    rebuildNeighborsIndex();
    // Item 6: on a canvas that already has a layout, only the newcomers move (`relax`); a first paint lays out all.
    // Proportion pass (review, 2026-10-15): "already has a layout" means some node of THIS push carries a position.
    // A push where none does (another bank, after the blank push a bank switch sends first) is a first paint: a cold
    // layout, the dot scale chosen afresh, and a fit. One whose carried layout asks for a dot scale more than
    // SIZE_RELAYOUT_FROM away from the current one (a switch back to a bank whose positions are cached, a bank sharing
    // ids with the last one) lays out every node from where it is, so the scale can follow, and fits.
    const cold = carried === 0;
    let rescale = false;
    if (!cold) {
        const want = wantedScaleNow();
        rescale = want !== null && Math.abs(Math.log(want / sizeScale)) > Math.log(SIZE_RELAYOUT_FROM);
    }
    if (cold) startSimulation({ reheat: 1.0, seeded: fresh });
    else if (rescale) startSimulation({ reheat: 0.3, seeded: fresh });
    else startSimulation({ reheat: 0.3, relax: fresh, seeded: fresh });
    if (cold || rescale) armInitialFit();

    if (focusNodeId) { computeFocusSet(); applyFocusPinning(); }
    scheduleRedraw();
}

// Incremental *delta* update (§5.6). The Swift side diffs two /graph snapshots
// by node id + contentHash and sends only what moved:
//   { added: [node], updated: [node], removed: [id], links?: [link] }
// Unlike updateGraph, this never rebuilds the node array from the payload — it
// mutates the live objects the simulation already holds, so every untouched
// node keeps its exact x/y/vx/vy and the layout doesn't re-explode after a
// Sleep cycle that changed one entity. `links` is present only when the link
// set actually changed; absent means "leave the links alone".
// Keys the Swift encoder omits when empty/false, so `updateGraphDelta` has to
// clear them explicitly before merging an updated node (see below).
const DELTA_OPTIONAL_KEYS = ["hubId", "observers", "contexts", "isFacet", "parentId", "context"];

function updateGraphDelta(dataStr) {
    const data = typeof dataStr === "string" ? JSON.parse(dataStr) : dataStr;

    // A delta is only meaningful on top of an existing simulation. A full
    // payload, or a first paint, goes down the full path — reshaped so nothing
    // is lost: a delta payload has no `nodes` key, so handing it to
    // updateGraph verbatim would wipe the canvas.
    if (data.isFull || !nodes.length) {
        return updateGraph(Array.isArray(data.nodes) ? data : {
            nodes: [...(data.added || []), ...(data.updated || [])],
            links: data.links || [],
        });
    }

    resizeCanvas();

    const added = (data.added || []).slice();
    const updated = data.updated || [];
    const removed = data.removed || [];

    // 1. Removals — drop the nodes, plus any link left dangling by them.
    if (removed.length) {
        const gone = new Set(removed);
        nodes = nodes.filter(n => !gone.has(n.id));
        links = links.filter(l => {
            const sid = typeof l.source === "object" ? l.source.id : l.source;
            const tid = typeof l.target === "object" ? l.target.id : l.target;
            return !gone.has(sid) && !gone.has(tid);
        });
        for (const id of removed) prevPositions.delete(id);
        if (focusNodeId && gone.has(focusNodeId)) focusNodeId = null;
    }

    // 2. Updates — copy the new fields onto the *existing* object so its
    // simulation state (x/y/vx/vy, any drag pin, d3's index) survives. An
    // "updated" node we don't actually have is treated as an addition.
    if (updated.length) {
        const byId = new Map(nodes.map(n => [n.id, n]));
        for (const u of updated) {
            const cur = byId.get(u.id);
            if (!cur) { added.push(u); continue; }
            const x = cur.x, y = cur.y, vx = cur.vx, vy = cur.vy;
            const fx = cur.fx, fy = cur.fy, index = cur.index;
            // Object.assign can only add or overwrite keys, so a field the
            // Swift encoder omits when empty/false would keep its stale value
            // (a node that stops being a facet, or loses its hub, would keep
            // the old parentId/hubId until the next full push). Clear the
            // known-optional keys first; the payload re-supplies whatever is
            // still true.
            for (const k of DELTA_OPTIONAL_KEYS) delete cur[k];
            Object.assign(cur, u);
            cur.x = x; cur.y = y; cur.vx = vx; cur.vy = vy;
            cur.fx = fx; cur.fy = fy; cur.index = index;
        }
    }

    // 3. Links — replaced wholesale when the payload carries them. Fresh
    // objects with *string* endpoints, exactly like updateGraph: d3.forceLink
    // rewrites endpoints into node references once the sim starts, and reusing
    // those stale references would resurrect removed nodes.
    if (Array.isArray(data.links)) {
        links = data.links.map(l => ({
            ...l,
            source: typeof l.source === "object" ? l.source.id : l.source,
            target: typeof l.target === "object" ? l.target.id : l.target,
        }));
    }

    // 4. Additions — append, then (after the hub index is rebuilt, so anchors
    // exist) seed each one near its hub or type cluster.
    if (added.length) {
        const present = new Set(nodes.map(n => n.id));
        for (const a of added) {
            if (present.has(a.id)) continue;
            present.add(a.id);
            nodes.push(a);
        }
    }

    computeDegree();
    buildHubIndex();

    beginSeeding();
    const fresh = new Set();
    for (const a of added) {
        const n = nodes.find(x => x.id === a.id);
        if (!n || n.x != null) continue;
        const p = prevPositions.get(n.id);
        if (p) { n.x = p.x; n.y = p.y; n.vx = 0; n.vy = 0; }
        else { const s = seedPositionFor(n); n.x = s.x; n.y = s.y; n.vx = 0; n.vy = 0; fresh.add(n.id); }
    }

    // Keep the position cache current for the touched nodes, so a later FULL
    // updateGraph (bank switch back, forced full push) re-seeds them where they
    // are now instead of throwing them back at their type anchor.
    for (const t of [...added, ...updated]) {
        const n = nodes.find(x => x.id === t.id);
        if (n && n.x != null) prevPositions.set(n.id, { x: n.x, y: n.y, vx: n.vx || 0, vy: n.vy || 0 });
    }

    rebuildVisible();
    rebuildNeighborsIndex();
    // Item 6 (2026-10-08): a delta relaxes only the nodes it brings; every settled node is held where it is
    // (`holdSettled`) and a delta that brings none starts no layout at all. It used to reheat the whole graph at
    // 0.3, which on the dense bench moved the settled core 80 wu mean / 573 max for a delta that changed nothing —
    // and a push that landed while the page was hidden replayed that motion when the person came back.
    startSimulation({ reheat: 0.3, relax: fresh, seeded: fresh });

    if (focusNodeId) { computeFocusSet(); applyFocusPinning(); }
    scheduleRedraw();
}

// Degree from links. This has to run BEFORE d3.forceLink mutates the link
// objects (it replaces the string id endpoints with node refs). The server
// degree is authoritative for sizing once present, but the JS recompute is
// still needed for visibility/min-degree filtering against the current
// (possibly filtered) link set, so we keep it. We only overwrite n.degree
// when the server did not already provide one.
function computeDegree() {
    const degreeMap = new Map();
    const pairSeen = new Set();
    const neighbours = new Map();
    links.forEach(l => {
        const sid = typeof l.source === "object" ? l.source.id : l.source;
        const tid = typeof l.target === "object" ? l.target.id : l.target;
        degreeMap.set(sid, (degreeMap.get(sid) || 0) + 1);
        degreeMap.set(tid, (degreeMap.get(tid) || 0) + 1);
        if (sid === tid) return;
        const key = sid < tid ? sid + "\u0000" + tid : tid + "\u0000" + sid;
        if (pairSeen.has(key)) return;
        pairSeen.add(key);
        neighbours.set(sid, (neighbours.get(sid) || 0) + 1);
        neighbours.set(tid, (neighbours.get(tid) || 0) + 1);
    });
    nodes.forEach(n => {
        const computed = degreeMap.get(n.id) || 0;
        // Local degree drives min-degree visibility; keep it on _localDegree.
        n._localDegree = computed;
        // Size reads DISTINCT neighbours over every link the payload carries (2026-10-15): parallel claims between one
        // pair are one connection on screen, and a filter never resizes a node.
        n._neighbours = neighbours.get(n.id) || 0;
        // Server degree wins for sizing if it was supplied (>0 or explicitly set).
        if (n.degree == null) n.degree = computed;
    });
}

// Build memberToHub + hubAnchors from the current node/link set. A node's hub
// is taken from its hubId field if present; otherwise inferred from a link to
// any hub node (member-edge inference). Hubs are placed on an evenly-spaced
// ring so they read as the centers of gravity.
function buildHubIndex() {
    memberToHub = new Map();
    hubAnchors = new Map();

    const hubs = nodes.filter(nodeIsHub);
    if (!hubs.length) return;

    const R = 400;
    hubs.forEach((h, i) => {
        const angle = (i / hubs.length) * 2 * Math.PI;
        hubAnchors.set(h.id, [Math.cos(angle) * R, Math.sin(angle) * R]);
    });

    const hubIds = new Set(hubs.map(h => h.id));

    // Explicit hubId on member nodes takes priority.
    for (const n of nodes) {
        const hid = nodeHubId(n);
        if (hid && hubIds.has(hid)) memberToHub.set(n.id, hid);
    }

    // Member-edge inference for nodes without an explicit hubId: if a node
    // links to exactly one hub, treat that hub as its parent.
    if (memberToHub.size < nodes.length) {
        const hubLinksFor = new Map(); // node id -> Set<hub id>
        for (const l of links) {
            const sid = typeof l.source === "object" ? l.source.id : l.source;
            const tid = typeof l.target === "object" ? l.target.id : l.target;
            if (hubIds.has(sid) && !hubIds.has(tid)) {
                if (!hubLinksFor.has(tid)) hubLinksFor.set(tid, new Set());
                hubLinksFor.get(tid).add(sid);
            }
            if (hubIds.has(tid) && !hubIds.has(sid)) {
                if (!hubLinksFor.has(sid)) hubLinksFor.set(sid, new Set());
                hubLinksFor.get(sid).add(tid);
            }
        }
        for (const [nid, hs] of hubLinksFor) {
            if (memberToHub.has(nid)) continue;
            if (hs.size === 1) memberToHub.set(nid, [...hs][0]);
        }
    }

    // §2c: facet satellites gravitate toward their parent subject. Route them
    // through the SAME hubGravity machinery by mapping facet -> parentId. This
    // is additive: a facet whose parent isn't on the graph is simply left out.
    const nodeIds = new Set(nodes.map(n => n.id));
    for (const n of nodes) {
        if (!nodeIsFacet(n)) continue;
        const pid = nodeParentId(n);
        if (pid && nodeIds.has(pid)) memberToHub.set(n.id, pid);
    }
}

// G109 (2026-10-14): newcomers that share an anchor spread on a Vogel-phyllotaxis disc around it — d3's own initial
// arrangement — instead of all landing within ±30 wu of one point. A cold paint of the bank-shaped synthetic seeded
// ~3,500 pages on ~15 points; the first ~25 ticks were then every node at the speed clamp, blowing the pile apart.
// `beginSeeding` resets the per-anchor counters for one push.
const SEED_SPACING = 22;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
let seedCounts = new Map();
let seedNodeById = new Map();
function beginSeeding() {
    seedCounts = new Map();
    seedNodeById = new Map(nodes.map(n => [n.id, n]));
}
function seedAround(key, x, y) {
    const k = seedCounts.get(key) || 0;
    seedCounts.set(key, k + 1);
    const r = SEED_SPACING * Math.sqrt(k + 0.5);
    const a = k * GOLDEN_ANGLE + (Math.random() - 0.5) * 0.2;
    return { x: x + r * Math.cos(a), y: y + r * Math.sin(a) };
}

function seedPositionFor(n) {
    // 2026-10-15: a page with a big fan starts in the middle — d3 moves an end of a link in inverse proportion to its
    // link count, so the owner's page, seeded at the person anchor, barely moved and settled off to one side.
    if ((n._neighbours || 0) > DISSUADE_FROM && !nodeIsHub(n)) return seedAround("middle", 0, 0);
    // If the node belongs to a hub and that hub already has a position, seed
    // near it so new members land in the right cluster.
    const hid = memberToHub.get(n.id);
    if (hid) {
        const hub = seedNodeById.get(hid);
        if (hub && hub.x != null) return seedAround(hid, hub.x, hub.y);
        const anchor = hubAnchors.get(hid);
        if (anchor) return seedAround(hid, anchor[0], anchor[1]);
    }
    if (nodeIsHub(n)) {
        const anchor = hubAnchors.get(n.id);
        if (anchor) return seedAround(n.id, anchor[0], anchor[1]);
    }
    const type = typeClusterPositions[n.type];
    if (type) return seedAround("type:" + n.type, type[0], type[1]);
    return seedAround("origin", 0, 0);
}

// After the components are known: a newcomer that is a satellite starts in its band slot, not at its type anchor
// inside the body (it used to cross the body to get there).
function seedSatellites(seeded) {
    if (!seeded || !seeded.size || !satelliteUnits.length) return;
    layoutBand();
    for (const u of satelliteUnits) {
        u.nodes.forEach((n, k) => {
            if (!seeded.has(n.id)) return;
            const r = k === 0 ? 0 : (2 * nodeRadius(n) + LEAF_LINK_GAP) * Math.sqrt(k);
            n.x = u.x + r * Math.cos(k * GOLDEN_ANGLE);
            n.y = u.y + r * Math.sin(k * GOLDEN_ANGLE);
            n.vx = 0; n.vy = 0;
        });
    }
}

function rebuildVisible() {
    const typeFilter = filters.types;
    const statusFilter = filters.statuses;
    const tagFilter = filters.tags;
    const minConf = filters.minConfidence;
    const minDeg = filters.minDegree;

    visibleNodes = nodes.filter(n => {
        // Facet sub-nodes are exempt from the min-degree cull (they only ever
        // hold a single facetOf edge to their parent).
        if (!nodeIsFacet(n) && (n._localDegree || 0) < minDeg) return false;
        if (typeFilter && !typeFilter.has(n.type)) return false;
        if (statusFilter && !statusFilter.has(n.status)) return false;
        if ((n.confidence || 0) < minConf) return false;
        if (tagFilter && tagFilter.size > 0) {
            const tags = n.tags || [];
            if (!tags.some(t => tagFilter.has(t))) return false;
        }
        // Context filter DROPS non-matching facet/context nodes (so "engineering
        // only" removes other facet satellites). Observer filter only DIMS, so
        // it is applied in draw(), not here.
        if (!nodeMatchesContexts(n)) return false;
        return true;
    });

    const visibleIds = new Set(visibleNodes.map(n => n.id));
    visibleLinks = links.filter(l => {
        const sid = typeof l.source === "object" ? l.source.id : l.source;
        const tid = typeof l.target === "object" ? l.target.id : l.target;
        if (!visibleIds.has(sid) || !visibleIds.has(tid)) return false;
        // Context filter drops edges asserted in a non-selected context (an
        // edge with no context is context-blind and always passes).
        if (filters.contexts && l.context && !filters.contexts.has(l.context)) return false;
        return true;
    });

    anyPending = visibleNodes.some(nodeHasPending);
}

function rebuildNeighborsIndex() {
    neighborsById = new Map();
    visibleLinks.forEach(l => {
        const sid = typeof l.source === "object" ? l.source.id : l.source;
        const tid = typeof l.target === "object" ? l.target.id : l.target;
        if (!neighborsById.has(sid)) neighborsById.set(sid, new Set());
        if (!neighborsById.has(tid)) neighborsById.set(tid, new Set());
        neighborsById.get(sid).add(tid);
        neighborsById.get(tid).add(sid);
    });
}

// Per-tick force pulling each member node toward its hub's current position.
// This gives the graph real centers of gravity instead of a uniform blob.
// G109: `alpha` is what d3 passes every force each tick (1.0 cold -> alphaMin).
// This force used to ignore it — a permanent `strength`-per-tick spring that,
// against the never-alpha-scaled forceCollide, kept ~1,500 nodes bouncing for
// ever (KE/node plateau ~20 at tick 400 on the bench, 4e-4 once scaled). That
// bounce is what velocityDecay 0.45 / alphaMin 0.05 were papering over. The
// nominal 0.05 is unchanged, so a cold layout at alpha 1.0 is identical to
// before for its first ticks. The id map is built once per simulation in
// initialize() (d3 calls it when the force is bound and when nodes change),
// not on every tick — the force now also runs on every drag frame.
function hubGravityForce(strength) {
    let byId = new Map();
    function force(alpha) {
        if (!memberToHub.size) return;
        const k = strength * alpha;
        for (const n of visibleNodes) {
            const hid = memberToHub.get(n.id);
            if (!hid) continue;
            const hub = byId.get(hid);
            if (!hub) continue;
            n.vx += (hub.x - n.x) * k;
            n.vy += (hub.y - n.y) * k;
        }
    }
    force.initialize = (simNodes) => { byId = new Map(simNodes.map(n => [n.id, n])); };
    return force;
}

// ---------- G109 layout (2026-10-14): one spring per pair, bodies and a band of satellites ----------
//
// Measured on a synthetic with the owner's bank's shape (Tests/graph/graph-bank-shape.js: 3,698 nodes, 41,570
// links, one 3,529-node component, a 2,092-degree page, 138 isolates and 11 small components), the layout this
// replaces never reached equilibrium: a fixed link strength of 0.28 on every one of a dense page's ~100 links is a
// spring constant of ~28 per tick, far past what an explicit integrator holds, so the core oscillated until the alpha
// cut-off froze it mid-motion (KE/node still 130, the fastest node at 48 wu/tick, at tick 135); the never-alpha-scaled
// collide kept what was left boiling (`collideForce`). Leaves were thrown far from their page by the body's summed
// charge (the 2,092-degree page's 226 leaves at a median 933 wu, a 44-leaf star's at 800, its farthest at 1,400 — the
// star "far outside on long links"), and a pair or a triple, with no anchor of its own, was pushed past the body's
// edge: the "two small nodes far away".
//
// What the layout does now, and where each idea comes from:
//   - The simulation gets ONE link per connected pair (`buildSimLinks`), and draw() strokes one hairline per pair and
//     colour (`drawLinks`, 2026-10-15): parallel claims between a pair no longer stack. Its strength is d3's own
//     default, 1 / min(neighbours of either end), weakened by sqrt(DISSUADE_FROM / n) on a link to a page with more
//     than DISSUADE_FROM (50) neighbours, never on a leaf's link (ForceAtlas2's "dissuade hubs"; see `linkStrength`).
//     Never stronger than d3's default, so stable by construction.
//   - Every body page has the same charge, BODY_CHARGE (2026-10-15, Obsidian's single repel force). A charge that grew
//     with a page's neighbours carved holes round heavy pages and lined the rest into chains (see `chargeStrength`).
//     A page with more than DISSUADE_FROM neighbours is seeded in the middle and pulled there (`anchorStrength`).
//   - A link's rest length is the two discs plus a gap, shorter for a leaf, so a star reads as a star.
//   - Components: the largest, and any bigger than SATELLITE_MAX, are BODIES and repel each other. Every smaller
//     component — an isolate, a pair, a triple — is a SATELLITE: the bodies' charge neither reaches it nor counts
//     it, and it is held by an alpha-scaled spring to its place in a loose HALO round the body (2026-10-15; it
//     replaced #287's annulus of per-type arcs). Each unit's angle and depth are hashed from its own id, so the scatter
//     is irregular and stable across pushes, and the halo follows the body's own edge as the layout breathes (see
//     `layoutBand`). Obsidian leaves its orphans round the main cluster the same way; cytoscape's fcose/cola pack
//     disconnected components beside the main one rather than simulating them against it.
const SATELLITE_MAX = 30;            // a component this size or smaller (and not the largest) is packed in the band
const LINK_GAP = 24;                 // wu between two linked discs
const LEAF_LINK_GAP = 8;             // ... when one end has a single neighbour
const CHARGE_K = 40;                 // a body page's charge is -CHARGE_K * sqrt(2) (BODY_CHARGE)
const CHARGE_DISTANCE_MAX = 700;
const CHARGE_THETA = 1.2;            // Barnes-Hut accuracy; 0.9 -> 1.2 took the charge from ~14 to ~10 ms a tick here
const BAND_GAP = 40;                 // wu, at least, from the body's edge to the halo's inner edge
const BAND_GAP_FRAC = 0.06;          // ... or this share of the body's radius, whichever is larger
const BAND_SLOT_PAD = 4;             // wu around each satellite's footprint
const BAND_SPRING = 0.6;             // strength of the pull to a satellite's slot (x alpha, like forceX)
const VMAX_WU_PER_TICK = 60;         // speed clamp; a 1000 px/s flick at k=0.6 seeds ~28
// The halo (2026-10-15): how loose it is. Each satellite claims HALO_SPACING footprints of room, and the halo is never
// thinner than HALO_MIN_FRAC of the body's radius; its outer reach wobbles by HALO_WOBBLE of its thickness.
const HALO_SPACING = 3;
const HALO_MIN_ROOM = 1.8;           // ... and never less than this many of its footprints at the current dot scale
const HALO_MIN_FRAC = 0.22;
const HALO_WOBBLE = 0.3;
const HALO_EDGE_BINS = 36;           // angular bins the body's edge is read in

let simLinks = [];                    // one per connected pair, endpoints resolved to node objects
let drawLinks = [];                   // one per connected pair and colour: what draw() strokes
let simDegree = new Map();            // id -> distinct visible neighbours
let simNodeById = new Map();          // id -> visible node
let bodyNodes = [];                   // the nodes the bodies' charge acts on
let satelliteUnits = [];              // [{ key, type, nodes, footprint, angle, depth, x, y }]
const satelliteOf = new Map();        // id -> its unit

// Resolves every visible link's endpoints to the live node objects (draw() reads them, as it read what forceLink
// left there) and returns one simulation link per unordered pair.
function buildSimLinks() {
    const byId = new Map(visibleNodes.map(n => [n.id, n]));
    simNodeById = byId;
    const pairs = new Map();
    const drawn = new Set();
    drawLinks = [];
    for (const l of visibleLinks) {
        const s = byId.get(typeof l.source === "object" ? l.source.id : l.source);
        const t = byId.get(typeof l.target === "object" ? l.target.id : l.target);
        if (!s || !t) continue;
        l.source = s; l.target = t;
        if (s === t) continue;
        const key = s.id < t.id ? s.id + "\u0000" + t.id : t.id + "\u0000" + s.id;
        // 2026-10-15: parallel claims between a pair drew one line each on top of each other (41,570 lines for 9,046
        // pairs on the owner's graph), so a pair's alpha compounded with its claim count; now a pair draws once per
        // colour, and every line is the same hairline.
        const dkey = key + "\u0000" + (l.context || "");
        if (!drawn.has(dkey)) { drawn.add(dkey); drawLinks.push(l); }
        const p = pairs.get(key);
        if (p) p.count += 1;
        else pairs.set(key, { source: s, target: t, count: 1 });
    }
    simLinks = [...pairs.values()];
    simDegree = new Map();
    for (const l of simLinks) {
        simDegree.set(l.source.id, (simDegree.get(l.source.id) || 0) + 1);
        simDegree.set(l.target.id, (simDegree.get(l.target.id) || 0) + 1);
    }
}

// A stable number in [0, 1) from a unit's key and a salt (FNV-1a): a satellite's place in the halo is a function of
// its own id alone, so it keeps its place across pushes whatever else arrives or leaves.
function unitHash(key, salt) {
    let h = 2166136261 ^ salt;
    for (let i = 0; i < key.length; i++) { h ^= key.charCodeAt(i); h = Math.imul(h, 16777619); }
    h ^= h >>> 13; h = Math.imul(h, 0x5bd1e995); h ^= h >>> 15;
    return (h >>> 0) / 4294967296;
}

// Components over the simulation links; the small ones become satellite units with a stable index in their sector.
function assignComponents() {
    const parent = new Map(visibleNodes.map(n => [n.id, n.id]));
    const find = (x) => { while (parent.get(x) !== x) { const g = parent.get(parent.get(x)); parent.set(x, g); x = g; } return x; };
    for (const l of simLinks) {
        const a = find(l.source.id), b = find(l.target.id);
        if (a !== b) parent.set(a, b);
    }
    const groups = new Map();
    for (const n of visibleNodes) {
        const r = find(n.id);
        if (!groups.has(r)) groups.set(r, []);
        groups.get(r).push(n);
    }
    const comps = [...groups.values()].sort((a, b) => b.length - a.length);
    bodyNodes = [];
    satelliteUnits = [];
    satelliteOf.clear();
    comps.forEach((members, i) => {
        // The largest component is a body unless it is a single node; anything past SATELLITE_MAX is a body too.
        if (members.length > SATELLITE_MAX || (i === 0 && members.length > 1)) {
            for (const n of members) bodyNodes.push(n);
            return;
        }
        // The unit's key (lowest id) is what places it in the halo, so it keeps its place across pushes.
        let lead = members[0], key = members[0].id;
        for (const n of members) {
            if ((simDegree.get(n.id) || 0) > (simDegree.get(lead.id) || 0)) lead = n;
            if (n.id < key) key = n.id;
        }
        let rmaxBase = 0;
        for (const n of members) rmaxBase = Math.max(rmaxBase, baseRadius(n));
        // Its place: an angle anywhere around the body, and a depth into the halo from two draws averaged — most
        // satellites sit in the halo's middle and fewer toward either edge, so both edges are soft.
        const angle = unitHash(key, 1) * 2 * Math.PI;
        const depth = (unitHash(key, 2) + unitHash(key, 3)) / 2;
        const unit = { key, type: lead.type, nodes: members, rmaxBase, footprint: 0, room: 0, angle, depth, x: 0, y: 0 };
        satelliteUnits.push(unit);
        for (const n of members) satelliteOf.set(n.id, unit);
    });
    refreshFootprints();
}

// A satellite's footprint at a dot scale: a singleton is its disc; a component spreads about one link length per ring
// of neighbours.
function unitFootprint(u, scale) {
    const rmax = u.rmaxBase * scale;
    return 2 * rmax + 2 * BAND_SLOT_PAD + (u.nodes.length > 1 ? (2 * rmax + LINK_GAP) * Math.sqrt(u.nodes.length - 1) : 0);
}

// Each satellite's footprint and the room it claims in the halo, at the current dot scale (`sizeScale`). The room is
// what it was at scale 1 (HALO_SPACING footprints), never less than HALO_MIN_ROOM of its footprint now (2026-10-15
// proportion pass): bigger dots fill the halo's room instead of widening the halo, so the halo keeps its share of the
// fitted view and the body is not pushed into a smaller middle.
function refreshFootprints() {
    for (const u of satelliteUnits) {
        u.footprint = unitFootprint(u, sizeScale);
        u.room = Math.max(HALO_SPACING * unitFootprint(u, 1), HALO_MIN_ROOM * u.footprint);
    }
}

// Where the halo is this tick. Exposed for the tests.
//
// G109 look pass (2026-10-15, owner: "it looks like a weird circle"). #287's ring stacked the satellites into columns
// of an exact annulus, each type an arc: 846 saved links became neat concentric rows of identical dots, a printed
// necklace. Obsidian's unlinked notes end up around the body too, but as a loose, irregular scatter — a halo. This is
// that halo, placed rather than simulated (the band's guarantees stay: out of the body's charge, alpha-scaled spring,
// nothing flies away):
//   - the halo follows the body's own edge, read per angle (HALO_EDGE_BINS bins, smoothed, half-blended with the
//     body's p99 radius), so it echoes the body's shape instead of ruling a circle round it;
//   - it is as thick as HALO_SPACING footprints of room per satellite need, never thinner than HALO_MIN_FRAC of the
//     body's radius, and its outer reach wobbles by a few slow waves, so the whole reads as an organic blob;
//   - each satellite's angle and depth come from its own id (`unitHash`), so the scatter is random-looking — uneven
//     density, small clumps and gaps, no rows — and still deterministic and stable across pushes.
function layoutBand() {
    let cx = 0, cy = 0;
    const radii = new Float64Array(bodyNodes.length);
    for (const n of bodyNodes) { cx += n.x; cy += n.y; }
    if (bodyNodes.length) { cx /= bodyNodes.length; cy /= bodyNodes.length; }
    const binMax = new Float64Array(HALO_EDGE_BINS);
    bodyNodes.forEach((n, i) => {
        const dx = n.x - cx, dy = n.y - cy;
        const r = Math.hypot(dx, dy);
        radii[i] = r;
        const b = Math.min(HALO_EDGE_BINS - 1, Math.floor(((Math.atan2(dy, dx) + Math.PI) / (2 * Math.PI)) * HALO_EDGE_BINS));
        if (r > binMax[b]) binMax[b] = r;
    });
    radii.sort();
    const edge = radii.length ? radii[Math.floor(0.99 * (radii.length - 1))] : 0;
    // the edge per angle: each bin's farthest page (capped at the p99 radius, so one stray page makes no bulge),
    // averaged over its neighbours and blended half-and-half with the p99 circle
    const edgeAt = new Float64Array(HALO_EDGE_BINS);
    for (let b = 0; b < HALO_EDGE_BINS; b++) {
        let sum = 0;
        for (let o = -2; o <= 2; o++) sum += Math.min(edge, binMax[(b + o + HALO_EDGE_BINS) % HALO_EDGE_BINS] || edge * 0.6);
        edgeAt[b] = 0.5 * edge + 0.5 * (sum / 5);
    }
    const gap = Math.max(BAND_GAP, BAND_GAP_FRAC * edge);
    const inner = edge + gap;
    let area = 0;
    for (const u of satelliteUnits) area += u.room * u.room;
    const thickness = Math.max(HALO_MIN_FRAC * Math.max(edge, 1), Math.sqrt(inner * inner + area / Math.PI) - inner);
    const wobble = (a) => 0.5 * Math.sin(2 * a + 0.7) + 0.3 * Math.sin(3 * a + 2.1) + 0.2 * Math.sin(5 * a + 4.4);
    for (const u of satelliteUnits) {
        const a = u.angle;
        const fb = ((a + Math.PI) / (2 * Math.PI)) * HALO_EDGE_BINS;
        const b0 = Math.floor(fb) % HALO_EDGE_BINS, b1 = (b0 + 1) % HALO_EDGE_BINS, t = fb - Math.floor(fb);
        const base = edgeAt[b0] * (1 - t) + edgeAt[b1] * t + gap;
        const rr = base + thickness * u.depth * (1 + HALO_WOBBLE * wobble(a));
        u.x = cx + rr * Math.cos(a);
        u.y = cy + rr * Math.sin(a);
    }
    return { cx, cy, edge, inner, thickness };
}

// The satellites' pull to their slot, alpha-scaled like forceX (G109 rule 1).
function bandForce(strength) {
    return function force(alpha) {
        if (!satelliteUnits.length) return;
        layoutBand();
        const k = strength * alpha;
        for (const u of satelliteUnits) {
            for (const n of u.nodes) {
                n.vx += (u.x - n.x) * k;
                n.vy += (u.y - n.y) * k;
            }
        }
    };
}

// d3's collide, its strength scaled by alpha below COLLIDE_FULL_ALPHA (G109 rule 1). Unscaled, it was the energy left
// in a cooled layout: the alpha-scaled forces compress the core less and less as alpha falls, collide re-resolves
// the same discs at full strength every tick, and with velocityDecay 0.2 the core boiled — on the bank-shaped
// synthetic KE/node 11 at tick 125 with it, 6e-3 without. Scaled, every force keeps the same ratio as the layout
// cools, so the equilibrium it cools toward stops moving. A hold (alphaTarget 0.1) keeps it at full strength.
const ALPHA_DECAY = 0.05;
const VELOCITY_DECAY = 0.2;
const COLLIDE_STRENGTH = 0.85;
const COLLIDE_FULL_ALPHA = 0.03;
const COLLIDE_PAD = 4;                // wu around each disc
function collideForce() {
    const inner = d3.forceCollide().radius(d => nodeRadius(d) + COLLIDE_PAD).strength(COLLIDE_STRENGTH);
    const f = (alpha) => {
        inner.strength(COLLIDE_STRENGTH * Math.min(1, alpha / COLLIDE_FULL_ALPHA));
        inner(alpha);
    };
    f.initialize = (nodes, random) => inner.initialize(nodes, random);
    f.inner = inner;
    return f;
}

// A d3 force that only sees some of the simulation's nodes (the bodies' charge).
function restrictForce(inner, pick) {
    const f = (alpha) => inner(alpha);
    f.initialize = (nodes, random) => inner.initialize(nodes.filter(pick), random);
    f.inner = inner;
    return f;
}

// One charge for every body page (2026-10-15, Obsidian's single "repel force"). It grew with a page's neighbours
// (-CHARGE_K * sqrt(n + 1), ForceAtlas2's degree-weighted repulsion), so each heavy page — the owner's at -1,790, hubs
// and busy pages at -300 to -600 against -80 for a typical one — cleared a hole round itself, and the pages squeezed
// between the holes lined up into chains: a foam of ruled arcs across the body (measured on the bank shape: capping
// the count at 50 still drew it, at 6 faintly, a uniform charge not at all). A hub still reads by its fan: the
// dissuaded links (`linkStrength`) let its neighbours spread instead of ringing it.
const BODY_CHARGE = -CHARGE_K * Math.SQRT2;
function chargeStrength() {
    return BODY_CHARGE;
}

// d3's default strength, 1 / min(neighbours of either end), dissuaded further on a link to a page with more than
// DISSUADE_FROM neighbours by sqrt(DISSUADE_FROM / its neighbours) (2026-10-15). At d3's default, each of the owner's
// ~2,000 neighbours — most with 2-4 neighbours — was held to it by a strong spring of one rest length, while the body's
// charge pushed them all outward alike: they settled on a CIRCLE round the owner's page (and smaller ones round the
// next heaviest pages), and those circles crossed the body as ruled arcs of dots. Weaker, a page stays with its own
// cluster and the big page's links fan out to it — ForceAtlas2's "dissuade hubs", applied only past a fan's size and
// never to a leaf, so a star keeps d3's tight springs. Never stronger than d3's default, so as stable.
const DISSUADE_FROM = 50;
function linkStrength(l) {
    const a = simDegree.get(l.source.id) || 1, b = simDegree.get(l.target.id) || 1;
    const lo = Math.min(a, b), hi = Math.max(a, b);
    // a leaf (one neighbour) keeps d3's full spring: it belongs in its page's fan, however big the page
    return (1 / lo) * (hi > DISSUADE_FROM && lo > 1 ? Math.sqrt(DISSUADE_FROM / hi) : 1);
}

function linkDistance(l) {
    const leaf = Math.min(simDegree.get(l.source.id) || 0, simDegree.get(l.target.id) || 0) <= 1;
    return nodeRadius(l.source) + nodeRadius(l.target) + (leaf ? LEAF_LINK_GAP : LINK_GAP);
}

// Guard, not a force: with velocityDecay at 0.2 a reheat can launch a node;
// this rescales any velocity above VMAX down to it. Registered LAST so it sees
// the summed velocity (d3 applies forces in insertion order, then damping).
// Deliberately not alpha-scaled — it can only remove energy, so it cannot
// re-create the plateau that rule "alpha-scale every custom force" guards.
function clampSpeedForce() {
    return function force() {
        for (const n of visibleNodes) {
            const s = Math.hypot(n.vx, n.vy);
            if (s > VMAX_WU_PER_TICK) { const k = VMAX_WU_PER_TICK / s; n.vx *= k; n.vy *= k; }
        }
    };
}

// Item 6 — the settled nodes a layout of newcomers holds still, id -> the {x, y} it pinned them at. A hold is the
// layout's own: it ends with that layout (d3's "end", or the next startSimulation), and it never takes over a pin
// someone else set (a drag, focus mode) nor clears one when it ends.
let layoutHolds = new Map();
// The ids the current layout relaxes (null = every node). Review r1 #2: a push that arrives before that layout ends
// (alpha still above alphaMin, running or held while the page is hidden) adds to it instead of replacing it.
let layoutRelax = null;

function holdSettled(relax) {
    for (const n of visibleNodes) {
        if (relax.has(n.id) || n.fx != null || n.x == null) continue;
        n.fx = n.x; n.fy = n.y;
        layoutHolds.set(n.id, { x: n.x, y: n.y });
    }
}

function holdAroundDrag(node) {
    releaseHolds();
    const relax = new Set([node.id, ...(neighborsById.get(node.id) || [])]);
    layoutRelax = relax;
    holdSettled(relax);
}

function releaseHolds() {
    if (!layoutHolds.size) return;
    const byId = new Map(nodes.map(n => [n.id, n]));
    for (const [id, p] of layoutHolds) {
        const n = byId.get(id);
        if (!n || n.fx !== p.x || n.fy !== p.y) continue;           // moved on by a drag: not ours any more
        if (draggingNode && draggingNode.id === id) continue;
        if (focusNodeId && focusSet && !focusSet.has(id)) continue;  // focus mode wants it pinned
        n.fx = null; n.fy = null; n.vx = 0; n.vy = 0;
    }
    layoutHolds.clear();
}

// `relax`: the ids that may move (null = all, a first layout). An empty set starts no layout — nothing moves, the
// simulation is rebuilt over the new arrays and left at rest.
function startSimulation({ reheat = 1.0, relax = null, seeded = null } = {}) {
    // An unfinished layout's work carries over: its nodes keep moving and it keeps its heat. A push that brings
    // nothing new then simply continues it; one that brings newcomers joins them to it.
    const current = simulation ? simulation.alpha() : 0;
    const unfinished = Boolean(simulation) && typeof current === "number" && current >= simulation.alphaMin();
    const bringsWork = relax === null || relax.size > 0;
    if (unfinished) {
        const carried = current;
        if (relax === null || layoutRelax === null) relax = null;
        else relax = new Set([...layoutRelax, ...relax]);
        reheat = bringsWork ? Math.max(carried, reheat) : carried;
    }
    if (simulation) simulation.stop();
    releaseHolds();
    layoutRelax = relax;
    buildSimLinks();
    assignComponents();
    seedSatellites(seeded);
    if (relax === null) beginSizeAdapt(reheat);

    simulation = d3.forceSimulation(visibleNodes)
        .alphaDecay(ALPHA_DECAY)
        // G109: 0.2 (d3 default 0.4). Each tick keeps 80% of velocity, so a 28 wu/tick flick coasts ~13 ticks
        // instead of 6. graph-physics.test.js guards it.
        .velocityDecay(VELOCITY_DECAY)
        // G109: d3's default. The runway a throw needs; a settled layout ends earlier on its own (`settleCheck`).
        .alphaMin(0.001)
        .force("link", d3.forceLink(simLinks).distance(linkDistance).strength(linkStrength))
        .force("charge", restrictForce(
            d3.forceManyBody().strength(chargeStrength).distanceMax(CHARGE_DISTANCE_MAX).theta(CHARGE_THETA),
            d => !satelliteOf.has(d.id)))
        .force("center", d3.forceCenter(0, 0).strength(0.04))
        .force("collision", collideForce())
        // Hubs are pulled toward their ring anchor; members toward their hub; other body pages softly toward
        // their type's anchor. Satellites ignore all three: the band places them.
        .force("xType", d3.forceX(d => xAnchor(d)).strength(d => anchorStrength(d)))
        .force("yType", d3.forceY(d => yAnchor(d)).strength(d => anchorStrength(d)))
        .force("hubGravity", hubGravityForce(0.05))
        .force("band", bandForce(BAND_SPRING))
        .force("clampSpeed", clampSpeedForce())
        .on("tick", () => { adaptSize(); tickInitialFit(); settleCheck(); scheduleRedraw(); })
        .on("end", () => { simulation.stop(); sizeAdapting = false; releaseHolds(); layoutRelax = null; finishInitialFit(); });

    if (relax && relax.size === 0) {
        simulation.alpha(0).stop();
        return;
    }
    if (relax) holdSettled(relax);
    simulation.alpha(reheat).restart();
    holdIfInactive();
}

function isBigPage(d) {
    return (simDegree.get(d.id) || 0) > DISSUADE_FROM && !nodeIsHub(d);
}

function xAnchor(d) {
    if (isBigPage(d)) return 0;
    if (nodeIsHub(d) && hubAnchors.has(d.id)) return hubAnchors.get(d.id)[0];
    return typeClusterPositions[d.type]?.[0] ?? 0;
}

function yAnchor(d) {
    if (isBigPage(d)) return 0;
    if (nodeIsHub(d) && hubAnchors.has(d.id)) return hubAnchors.get(d.id)[1];
    return typeClusterPositions[d.type]?.[1] ?? 0;
}

// 2026-10-15: 0.08 -> 0. Every hub was pinned to an evenly spaced ring 400 wu out, and its members, pulled to it
// (hubGravity), drew that ring as arcs of dots through the body — a ruled circle inside the circle. Free, a hub settles
// where its members and links put it; the ring is now only where a cold paint seeds it.
const HUB_ANCHOR_STRENGTH = 0;
const BIG_PAGE_PULL = 0.3;
function anchorStrength(d) {
    if (satelliteOf.has(d.id)) return 0;                    // G109: the band places satellites
    if (nodeIsHub(d) && hubAnchors.has(d.id)) return HUB_ANCHOR_STRENGTH;
    // A page with a fan bigger than DISSUADE_FROM is pulled to the middle, not to its type's anchor (2026-10-15). d3
    // moves an end of a link in inverse proportion to its link count, so the owner's ~2,000 links barely move it: the
    // crowd's charge pushed it ~500 wu out in the first 15 ticks of a cold layout and its links never brought it back
    // (with 0.04 it rested 500 wu off the middle). ForceAtlas2 gives such pages more gravity for the same reason.
    if (isBigPage(d)) return BIG_PAGE_PULL;
    // hubGravity handles members — while their hub (or a facet's parent) is on screen. One a filter hid used to keep
    // no anchor at all and drift; it falls back to its type's anchor.
    if (simNodeById.has(memberToHub.get(d.id))) return 0;
    return 0.04;                                            // soft type clustering
}

// G109 (2026-10-14): the layout ends when it is still, not when alpha runs out. d3's own cut-off (alpha < alphaMin)
// used to freeze a layout that was still moving (KE/node 130 and a node at 48 wu/tick, at tick 135, on the
// bank-shaped synthetic). Now every force cools with alpha, so the motion dies on its own; and a layout that has
// cooled below SETTLE_ALPHA ends as soon as it LOOKS still — no node faster than SETTLE_MAX_SPEED and at most
// SETTLE_SHARE of them faster than SETTLE_SPEED wu a tick (a few leaves easing in are not worth more frames). d3's
// step() stops the timer and fires "end" right after this tick handler. Never during a hold or a drag: a throw's
// runway is alphaTarget 0 and a moving node, which the max-speed bound keeps going.
const SETTLE_ALPHA = 0.05;
const SETTLE_SPEED = 0.3;
const SETTLE_MAX_SPEED = 1.0;
const SETTLE_SHARE = 0.02;
function settleCheck() {
    if (!simulation || draggingNode || simulation.alphaTarget() > 0) return false;
    if (simulation.alpha() > SETTLE_ALPHA) return false;
    const slow2 = SETTLE_SPEED * SETTLE_SPEED, max2 = SETTLE_MAX_SPEED * SETTLE_MAX_SPEED;
    let fast = 0, free = 0;
    for (const n of visibleNodes) {
        if (n.fx != null) continue;
        free += 1;
        const v2 = n.vx * n.vx + n.vy * n.vy;
        if (v2 > max2) return false;
        if (v2 > slow2) fast += 1;
    }
    if (fast > SETTLE_SHARE * free) return false;
    simulation.alpha(0);
    return true;
}

// G109 look pass (owner, 2026-10-15: "it looks like a weird circle … look at pictures of an Obsidian vault"). A node is
// a small dot sized by how connected it is, as in Obsidian, with confidence a small second term: a leaf is ~3 wu, the
// median page ~3.5, a 150-member hub ~8, the owner's page with ~2,000 neighbours ~23 — large, never dominant (max /
// median ~6.5, was ~21). Distinct neighbours, not raw links (computeDegree): the owner's page counted 16,679 raw links
// and drew a 206 wu disc over the centre. Hubs are sized like every page — they read by their size and their fan, not
// by a floor and a ring. §2c: facet satellites stay the smallest dots.
const R_BASE = 2.2;
const R_CONFIDENCE = 0.8;
const R_PER_SQRT_NEIGHBOUR = 0.45;
const R_NEIGHBOURS_CAP = 2500;
function nodeRadius(d) {
    return sizeScale * baseRadius(d);
}
// A node's size relative to the others, in layout units at scale 1: bigger means more connected.
function baseRadius(d) {
    if (nodeIsFacet(d)) return 1.5 + (d.confidence || 0) * 1.5;
    const nb = Math.min(R_NEIGHBOURS_CAP, d._neighbours ?? nodeDegree(d));
    return R_BASE + (d.confidence || 0) * R_CONFIDENCE + R_PER_SQRT_NEIGHBOUR * Math.sqrt(nb);
}

// G109 proportion pass (owner, 2026-10-15: "nodes can be a bit bigger, relative to the amount of nodes there are in the
// graph, so that they also have a limit of how big and how small they can be, in a way that it always looks good and
// proportional"). One scale, `sizeScale`, multiplies every dot (`nodeRadius`), and the layout uses the scaled radii
// (collide, link rest lengths, the halo's footprints), so a bigger dot never lands on its neighbour. The scale is
// chosen so that, at the zoom that fits the graph to the view, the MEDIAN dot's on-screen radius is
//
//     clamp( sqrt(DOT_COVER x view area / (pi x visible nodes)),  DOT_MIN_PT,  DOT_MAX_PT )
//
// i.e. the dots cover about DOT_COVER of the fitted view, a 50-node graph's dots stop at the ceiling and a 5k-node
// graph's at the floor. #291's dots covered 1.3 % of the view on the owner's shape; a leaf was a 0.7 pt speck under a
// 1 pt line. The fit zoom depends on the layout, which depends on the dots, so the scale FOLLOWS THE FIT while a full
// layout is hot (`adaptSize`, each tick while alpha >= SIZE_ADAPT_UNTIL, damped): the fit zoom of the bank's shape is
// within ~5 % of its final value by then, and the scale is fixed for the cooler rest of the settle, so the settling
// guarantees hold. A layout of newcomers (a push) keeps the scale: settled, held dots never grow into each other.
const DOT_COVER = 0.06;
const DOT_MIN_PT = 2.2;
const DOT_MAX_PT = 8;
const SIZE_SCALE_MIN = 0.25;
const SIZE_SCALE_MAX = 4;
const SIZE_ADAPT_UNTIL = 0.15;
const SIZE_ADAPT_UNTIL_WARM = 0.02;  // ... for a warm full layout (a filter change, reheat < 1): its whole run
const SIZE_RELAYOUT_FROM = 1.25;      // a full push whose layout wants a scale this far off lays out every node
const SIZE_ADAPT_RATE = 0.3;          // the share of the (log) distance to the wanted scale taken per tick
let sizeScale = 1;
let sizeAdapting = false;
let sizeAdaptUntil = SIZE_ADAPT_UNTIL;
let sizeBaseMedian = R_BASE;          // the visible pages' median baseRadius, read once per layout

function dotTargetPt(count) {
    const free = Math.sqrt(DOT_COVER * width * height / (Math.PI * Math.max(1, count)));
    return Math.max(DOT_MIN_PT, Math.min(DOT_MAX_PT, free));
}

let sizeBaseMin = R_BASE;             // ... and the smallest dot's, which sets a link's width
function measureBaseRadii() {
    const radii = visibleNodes.filter(n => !nodeIsFacet(n)).map(baseRadius).sort((a, b) => a - b);
    sizeBaseMedian = radii.length ? radii[Math.floor(radii.length / 2)] : R_BASE;
    // the smallest dot drawn, a facet's included
    sizeBaseMin = visibleNodes.reduce((m, n) => Math.min(m, baseRadius(n)), radii.length ? radii[0] : R_BASE);
    return radii.length;
}

// A full layout chooses its scale as it runs. A cold one (reheat 1) settles its extent early, so the scale is fixed
// below SIZE_ADAPT_UNTIL; a warm one (a filter change at reheat 0.3) starts from where every node was and its extent
// keeps changing to the end — 251 pages filtered out of 4,544 contract the whole run (review: an adapt cut at 0.15 left
// them at a 10 pt median, over the ceiling) — so it adapts until SIZE_ADAPT_UNTIL_WARM.
function beginSizeAdapt(reheat) {
    sizeAdapting = measureBaseRadii() > 0;
    sizeAdaptUntil = reheat >= 1 ? SIZE_ADAPT_UNTIL : SIZE_ADAPT_UNTIL_WARM;
}

// The scale the fit of the current positions asks for, clamped; null when there is nothing to fit.
function wantedScaleNow() {
    if (!(width > 0 && height > 0) || !measureBaseRadii()) return null;
    const t = transformForNodes(visibleNodes, FIT_PAD);
    if (!t) return null;
    const want = dotTargetPt(visibleNodes.length) / (sizeBaseMedian * t.k);
    return Math.max(SIZE_SCALE_MIN, Math.min(SIZE_SCALE_MAX, want));
}

// A resting link's stroke at zoom k: { width, alpha } in screen points, the alpha a factor on the link's own.
function linkStroke(k) {
    const smallest = 2 * sizeBaseMin * sizeScale * k;
    const w = Math.min(LINK_WIDTH_MAX_PT, LINK_WIDTH_OF_DOT * smallest);
    const device = 1 / (dpr || 1);
    return w >= device ? { width: w, alpha: 1 } : { width: device, alpha: w / device };
}

function adaptSize() {
    if (!sizeAdapting || !simulation) return;
    if (simulation.alpha() < sizeAdaptUntil) { sizeAdapting = false; return; }
    if (!(width > 0 && height > 0)) return;
    const t = transformForNodes(visibleNodes, FIT_PAD);
    if (!t) return;
    const want = dotTargetPt(visibleNodes.length) / (sizeBaseMedian * t.k);
    const next = Math.max(SIZE_SCALE_MIN, Math.min(SIZE_SCALE_MAX, sizeScale * Math.pow(want / sizeScale, SIZE_ADAPT_RATE)));
    if (Math.abs(next - sizeScale) < 0.002 * sizeScale) return;
    sizeScale = next;
    refreshFootprints();
    simulation.force("link").distance(linkDistance);           // d3 re-reads every rest length
    simulation.force("collision").inner.radius(d => nodeRadius(d) + COLLIDE_PAD);
}

// ---------- Focus / ego mode ----------

function computeFocusSet() {
    if (!focusNodeId) { focusSet = null; return; }
    const seen = new Set([focusNodeId]);
    let frontier = [focusNodeId];
    for (let h = 0; h < focusHops; h++) {
        const next = [];
        for (const id of frontier) {
            for (const nb of (neighborsById.get(id) || [])) {
                if (!seen.has(nb)) { seen.add(nb); next.push(nb); }
            }
        }
        frontier = next;
    }
    focusSet = seen;
}

// Pin context nodes (outside focus) so the sim only relaxes the focused
// subgraph; un-pin everything when focus is cleared.
function applyFocusPinning() {
    for (const n of visibleNodes) {
        const inFocus = !focusSet || focusSet.has(n.id);
        if (focusNodeId && !inFocus) {
            if (n.x != null) { n.fx = n.x; n.fy = n.y; }
        } else if ((!draggingNode || draggingNode.id !== n.id) && !layoutHolds.has(n.id)) {
            n.fx = null; n.fy = null;
        }
    }
}

function setFocus(id, hops) {
    focusNodeId = id || null;
    focusHops = Number(hops) || 2;
    computeFocusSet();
    applyFocusPinning();
    if (simulation) simulation.alpha(0.4).restart();
    holdIfInactive();
    if (focusNodeId) animateZoomToFocus();
    scheduleRedraw();
}

function clearFocus() {
    for (const n of visibleNodes) {
        if (!draggingNode || draggingNode.id !== n.id) { n.fx = null; n.fy = null; }
    }
    const wasFocused = focusNodeId !== null;
    focusNodeId = null;
    focusSet = null;
    if (simulation) simulation.alpha(0.2).restart();
    holdIfInactive();
    scheduleRedraw();
    if (wasFocused) {
        try {
            window.webkit.messageHandlers.cicada.postMessage(
                JSON.stringify({ type: "focusCleared" })
            );
        } catch (e) { /* no handler */ }
    }
}

function animateZoomToFocus() {
    if (!focusSet) return;
    const focusNodes = visibleNodes.filter(n => focusSet.has(n.id));
    const t = transformForNodes(focusNodes, 80);
    if (t) d3.select(canvas).transition().duration(400).call(currentZoom.transform, t);
}

// ---------- Search highlight + focus-on-node (no ego mode) ----------

function highlightSearch(idsStr) {
    let arr = [];
    try { arr = JSON.parse(idsStr); } catch (e) { arr = []; }
    searchHighlight = (arr && arr.length) ? new Set(arr) : null;
    scheduleRedraw();
}

// G123: land the viewport on a node and its neighbourhood — the search
// field's ⏎, and the seam Ask citations / Activity chips reveal through.
// Moves only the zoom transform; the simulation is never reheated (G109 rule).
// Returns false when the node is not in the visible set (hidden by a filter),
// so the caller can say so instead of silently doing nothing.
function revealNode(id) {
    const n = visibleNodes.find(x => x.id === id);
    if (!n || n.x == null) return false;
    const nb = neighborsById.get(id) || new Set();
    const group = [n];
    for (const m of visibleNodes) {
        if (nb.has(m.id)) group.push(m);
        if (group.length >= 40) break;
    }
    const fit = transformForNodes(group, 80);
    // Readable scale, centred on the node itself so the eye lands on it.
    const k = Math.min(MAX_ZOOM, Math.max(1.0, fit ? fit.k : 1.6));
    const t = d3.zoomIdentity.translate(width / 2, height / 2).scale(k).translate(-n.x, -n.y);
    if (currentZoom) {
        // DS-3a R-DG9 — the reveal owns the transform until it lands; a keep-in-view pan would cancel it
        // (same-name d3 transitions are exclusive). Its end re-checks, because the entity column may have
        // narrowed the canvas under it. Anything that stops it — a wheel or drag (interrupt), or a zoom
        // button, fit or focus scheduled before it started (cancel, d3 v7) — just drops the hold, so the
        // hold can never outlive its transition.
        // A second reveal cancels the first, whose handler must not release the second's hold: a sequence number.
        const seq = ++revealSeq;
        const release = () => { if (seq === revealSeq) revealing = false; };
        revealing = true;
        d3.select(canvas).transition().duration(450).call(currentZoom.transform, t)
            .on("end", () => { release(); if (!revealing && selectedNodeId) ensureVisible(selectedNodeId, true); })
            .on("interrupt cancel", release);
    } else {
        transform = t;   // headless (no zoom behaviour attached): apply directly
    }
    scheduleRedraw();
    return true;
}

function focusOnNode(id) {
    const n = visibleNodes.find(x => x.id === id) || nodes.find(x => x.id === id);
    if (!n || n.x == null) return;
    const t = d3.zoomIdentity
        .translate(width / 2, height / 2)
        .scale(Math.max(transform.k, 1.6))
        .translate(-n.x, -n.y);
    d3.select(canvas).transition().duration(400).call(currentZoom.transform, t);
    scheduleRedraw();
}

// ---------- Render loop ----------

function scheduleRedraw() {
    if (needsRedraw || !graphActive) return;
    needsRedraw = true;
    rafHandle = requestAnimationFrame(() => {
        rafHandle = null;
        needsRedraw = false;
        if (!graphActive) return;
        if (anyPending) pulsePhase = (performance.now() / 1000) * PULSE_CYCLES_PER_SECOND;
        draw();
        // Keep redrawing while the sim is still producing movement. Once
        // alpha drops below alphaMin the sim stops on its own. A settled graph
        // with a pending node ON SCREEN keeps the pulse ring going on a ~30 fps
        // timer (A07); one with no pending item, or only off-screen ones,
        // drops to zero CPU.
        const simActive = simulation && simulation.alpha() > simulation.alphaMin();
        if (simActive) {
            scheduleRedraw();
        } else if (anyPending && pendingOnScreen()) {
            schedulePulse();
        }
    });
}

function schedulePulse() {
    if (pulseTimer !== null || !graphActive) return;
    pulseTimer = setTimeout(() => { pulseTimer = null; scheduleRedraw(); }, PULSE_FRAME_MS);
}

// A07: is any pending node's ring inside the canvas? The ring reaches ~6 px past the node.
function pendingOnScreen() {
    const k = transform.k;
    for (const n of visibleNodes) {
        if (!nodeHasPending(n) || n.x == null) continue;
        const reach = nodeRadius(n) * k + PULSE_RING_FROM + PULSE_RING_TRAVEL + 1;
        const sx = n.x * k + transform.x, sy = n.y * k + transform.y;
        if (sx > -reach && sx < width + reach && sy > -reach && sy < height + reach) return true;
    }
    return false;
}

// Swift → JS (A07): the Graph tab is on screen, or not. Inactive cancels the queued frame and pulse
// timer, ends any drag (A09) and stops the d3 timer; active resumes a simulation that was still moving
// at its own alpha and redraws once. Positions and the zoom transform are never touched.
function setGraphActive(on) {
    on = Boolean(on);
    if (on === graphActive) return;
    graphActive = on;
    if (!on) {
        cancelInteraction();
        if (rafHandle !== null) cancelAnimationFrame(rafHandle);
        rafHandle = null;
        needsRedraw = false;
        if (pulseTimer !== null) clearTimeout(pulseTimer);
        pulseTimer = null;
        holdIfInactive();
        return;
    }
    if (simSuspended && simulation) {
        simSuspended = false;
        simulation.restart();
    }
    scheduleRedraw();
}

// Called after every `simulation.restart()`: an inactive graph never leaves the d3 timer running (a data
// push from SSE while another tab is showing lays out once the person comes back).
function holdIfInactive() {
    if (graphActive || !simulation) return;
    if (simulation.alpha() > simulation.alphaMin()) simSuspended = true;
    simulation.stop();
}

function draw() {
    if (!ctx) return;

    // Start from the HiDPI-scaled identity so the next transform we push
    // is in CSS pixels from the canvas's top-left.
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    ctx.save();
    ctx.translate(transform.x, transform.y);
    ctx.scale(transform.k, transform.k);

    const hoverActive = hoveredNode !== null;
    const neighbors = hoverActive
        ? (neighborsById.get(hoveredNode.id) || new Set())
        : null;

    const focusActive = focusSet !== null;

    // ---- Links ----
    // One path per (colour, alpha), not one stroke per link (G109, 2026-10-14): the owner's graph draws ~41,600
    // links, and a beginPath/stroke per link was 41,600 canvas flushes a frame; now it is one per bucket (a handful).
    // Buckets draw faintest first so a hovered or focused edge lands on top, as it did when it was drawn last.
    // 2026-10-15 (Obsidian's look): every pair draws once (`drawLinks`) as a hairline, at every zoom — the links are
    // the structure (fans round a hub, threads between clusters), so the fit view no longer drops all but the hubs'
    // links. A coloured (context) link is fainter than a neutral one: its hue is bright. Its width follows the dots
    // (`linkStroke`, proportion pass): always well under the smallest dot; a lit link is LINK_LIT_PT.
    const buckets = new Map();
    for (const l of drawLinks) {
        const src = l.source;
        const tgt = l.target;
        if (typeof src !== "object" || typeof tgt !== "object") continue;

        let alpha = l.context ? LINK_ALPHA_CONTEXT : LINK_ALPHA;
        let lit = false;
        if (focusActive) {
            const bothIn = focusSet.has(src.id) && focusSet.has(tgt.id);
            alpha = bothIn ? Math.max(alpha, 0.7) : 0.04;
            lit = bothIn;
        }
        if (hoverActive) {
            const touchesHover =
                src.id === hoveredNode.id ||
                tgt.id === hoveredNode.id;
            if (!touchesHover) { alpha = Math.min(alpha, 0.08); lit = false; }
            else { alpha = 0.9; lit = true; }
        }
        // §2a: context-colored edges. An edge with a context paints in its
        // context hue; a contextless (legacy) edge keeps the flat gray.
        const style = l.context ? contextColor(l.context) : PALETTE.edge;
        const key = alpha + "|" + style + "|" + lit;
        let bucket = buckets.get(key);
        if (!bucket) { bucket = { alpha, style, lit, links: [] }; buckets.set(key, bucket); }
        bucket.links.push(l);
    }
    const rest = linkStroke(transform.k);
    for (const bucket of [...buckets.values()].sort((a, b) => a.alpha - b.alpha)) {
        ctx.globalAlpha = bucket.lit ? bucket.alpha : bucket.alpha * rest.alpha;
        ctx.lineWidth = (bucket.lit ? LINK_LIT_PT : rest.width) / transform.k;
        ctx.strokeStyle = bucket.style;
        ctx.beginPath();
        for (const l of bucket.links) {
            ctx.moveTo(l.source.x, l.source.y);
            ctx.lineTo(l.target.x, l.target.y);
        }
        ctx.stroke();
    }

    // ---- Nodes ----
    for (const n of visibleNodes) {
        const r = nodeRadius(n);
        const isFacet = nodeIsFacet(n);
        // §2c: facet sub-nodes fill with their context color instead of the
        // type color, so the engineering/family satellites read as contexts.
        const color = isFacet
            ? contextColor(nodeContext(n))
            : (typeColors[n.type] || typeColors.unknown);

        // Status drives base opacity. Focus dimming and hover dimming stack on
        // top: a node outside the focus neighborhood fades to context.
        let alpha = STATUS_ALPHA[n.status] ?? 0.92;
        const quiet = nodeIsQuiet(n);
        if (quiet) alpha = Math.min(alpha, QUIET_FILL_ALPHA);
        // §3a: observer filter DIMS (not deletes) non-matching nodes so the
        // contrast reads as "this is the slice X asserts." Reuses focus-alpha.
        if (!nodeMatchesObservers(n)) alpha = Math.min(alpha, 0.1);
        if (focusActive && !focusSet.has(n.id)) alpha = Math.min(alpha, 0.06);
        if (hoverActive) {
            const isHover = n.id === hoveredNode.id;
            const isNeighbor = neighbors.has(n.id);
            if (!isHover && !isNeighbor) alpha = Math.min(alpha, 0.15);
            else alpha = Math.max(alpha, 1);
        }

        // Pending-item pulse ring (preattentive "needs you"). A slow
        // expanding/fading ring driven by pulsePhase. Drawn before the node
        // fill so the node sits on top. 2026-10-15: it hugs the dot (1.5 -> 5.5 px out, was 6 -> 16 px): around a
        // 1 px dot at the fit zoom the wide ring read as an empty brown circle floating in the graph.
        if (nodeHasPending(n) && alpha > 0.1) {
            const t = pulsePhase % 1;
            const pr = r + (PULSE_RING_FROM + t * PULSE_RING_TRAVEL) / transform.k;
            ctx.globalAlpha = (1 - t) * 0.6 * alpha;
            ctx.lineWidth = 1.5 / transform.k;
            ctx.strokeStyle = PULSE_COLOR;
            ctx.beginPath();
            ctx.arc(n.x, n.y, pr, 0, Math.PI * 2);
            ctx.stroke();
        }

        ctx.globalAlpha = alpha;

        // Decaying nodes get a dashed stroke so the viewer can tell they
        // are on their way out. Canvas doesn't have a per-shape dash cache
        // so we set the line dash inline — cheap at this scale.
        if (n.status === "decaying") {
            ctx.strokeStyle = color;
            ctx.lineWidth = 1.5 / transform.k;
            ctx.setLineDash([4 / transform.k, 3 / transform.k]);
        }

        // Glow only for the hovered node. The original implementation put
        // an SVG feGaussianBlur on every circle and that was the single
        // biggest perf cost in the SVG version.
        if (hoverActive && n.id === hoveredNode.id) {
            ctx.shadowColor = color;
            ctx.shadowBlur = 12;
        } else {
            ctx.shadowBlur = 0;
        }

        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        ctx.fill();

        // G59: the entity's own brand mark, clipped to the disc. Only past the
        // node-label zoom tier — below that the marks smear into indistinct
        // pixels and cost a drawImage per node for nothing.
        if (filters.showLogos && n.hasLogo && transform.k >= ZOOM_NODE_LABELS && alpha > 0.2) {
            const entry = logoImages.get(n.id);
            if (entry && entry.ready) {
                ctx.save();
                ctx.beginPath();
                ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
                ctx.clip();
                ctx.drawImage(entry.img, n.x - r, n.y - r, r * 2, r * 2);
                ctx.restore();
                ctx.globalAlpha = alpha;
            }
        }

        if (n.status === "decaying") {
            ctx.stroke();
            ctx.setLineDash([]);
        }

        ctx.shadowBlur = 0;

        // A quiet node: the faint fill above, ringed in its own hue at a steadier alpha so it still reads as a dot.
        if (quiet && alpha < 1 && alpha > 0.05) {
            ctx.globalAlpha = Math.min(1, alpha / QUIET_FILL_ALPHA * QUIET_RING_ALPHA);
            ctx.lineWidth = 1 / transform.k;
            ctx.strokeStyle = color;
            ctx.beginPath();
            ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
            ctx.stroke();
            ctx.globalAlpha = alpha;
        }

        // (2026-10-15: hubs no longer carry a ring — 37 thick gold rings read as "rings everywhere". A hub reads by
        // its size and its fan of links, as in Obsidian.)

        // Search highlight — a bright outer ring on matched nodes so they
        // glow in place while the user types in the toolbar search.
        if (searchHighlight && searchHighlight.has(n.id)) {
            ctx.globalAlpha = 1;
            ctx.lineWidth = 2.5 / transform.k;
            ctx.strokeStyle = PALETTE.nodeStroke;
            ctx.beginPath();
            ctx.arc(n.x, n.y, r + 6 / transform.k, 0, Math.PI * 2);
            ctx.stroke();
        }

        // DS-3a R-DG9 — the open entity's node: the search ring's shape in the theme's neutral ink
        // (textPrimary's twin), never the accent — selection is brightness, not colour (DR-5, P-a).
        if (selectedNodeId !== null && n.id === selectedNodeId) {
            ctx.globalAlpha = 1;
            ctx.lineWidth = 2 / transform.k;
            ctx.strokeStyle = PALETTE.nodeStroke;
            ctx.beginPath();
            ctx.arc(n.x, n.y, r + 5 / transform.k, 0, Math.PI * 2);
            ctx.stroke();
        }

        // §2b: observer badges — a tiny filled dot per distinct observer at the
        // node's upper-right. An external:* observer is the "someone else told
        // me this" signal, visible at a glance. Only at a readable zoom so the
        // dots don't smear into the node at low scale.
        const observers = nodeObservers(n);
        if (observers.length && !isFacet && transform.k >= ZOOM_HUBS_ONLY && alpha > 0.12) {
            const bs = 2.6 / transform.k;            // badge radius
            const gap = 1.5 / transform.k;
            const startX = n.x + r * 0.72;
            const startY = n.y - r * 0.72;
            ctx.globalAlpha = alpha;
            observers.slice(0, 3).forEach((wire, i) => {
                ctx.fillStyle = observerBadgeColor(wire);
                ctx.beginPath();
                ctx.arc(startX + i * (bs * 2 + gap), startY, bs, 0, Math.PI * 2);
                ctx.fill();
            });
        }
    }

    ctx.globalAlpha = 1;

    // ---- Node labels ----
    // Hovering a node labels it and its neighbours; focus mode labels the drilled-in neighbourhood. Otherwise names
    // fade in with zoom, as in Obsidian (2026-10-15): a node's label appears as its dot grows on screen, the biggest
    // first, never overlapping and never more than LABEL_BUDGET — so the fit view stays clean (only a page as large as
    // the owner's is named there) and the word soup of ambient labels at every zoom does not come back.
    if (hoverActive || focusActive) {
        drawNodeLabels(hoverActive, neighbors, focusActive);
    } else {
        drawAmbientLabels();
    }

    // ---- Edge labels (focus neighborhood, or zoomed in past the tier) ----
    // NOT gated on hover: a high-degree node has hundreds of incident edges and
    // labeling them all floods the canvas. Hovering still brightens the edges
    // themselves; their verbs read once you zoom in or enter focus mode.
    if (focusActive || transform.k >= ZOOM_EDGE_LABELS) {
        drawEdgeLabels(focusActive);
    }

    // Hover label override — show the hovered node's name with a prominent
    // background plate so the node under the cursor always reads clearly.
    if (hoverActive) {
        drawHoverLabel(hoveredNode);
    }

    ctx.restore();
}

// Render the labels for whichever small set is in scope: the focus-mode
// neighborhood, or (on hover) the hovered node's direct neighbors. While
// neither is active, names fade in with zoom instead (`drawAmbientLabels`,
// 2026-10-15). Scope is always small here, so the work is to rank by
// importance and greedily cull screen-space collisions so nothing overlaps.
// The hovered node itself gets its prominent plate from drawHoverLabel; this
// pass labels everything ELSE in scope.
function drawNodeLabels(hoverActive, neighbors, focusActive) {
    const k = transform.k;
    // A hovered hub can have hundreds of neighbors; cap to the top handful so
    // hover stays a glance, not a wall. Focus mode is a deliberate drill-in and
    // gets a larger budget.
    const budget = focusActive ? 120 : 12;

    const candidates = [];
    for (const n of visibleNodes) {
        if (focusActive) {
            if (!focusSet.has(n.id)) continue;
        } else if (hoverActive) {
            // hovered node is drawn by drawHoverLabel; label its neighbors here
            if (n.id === hoveredNode.id || !neighbors.has(n.id)) continue;
        } else {
            continue;
        }
        candidates.push(n);
    }
    if (!candidates.length) return;

    candidates.sort((a, b) =>
        (Number(nodeIsHub(b)) - Number(nodeIsHub(a))) ||
        (nodeDegree(b) - nodeDegree(a)) ||
        ((b.confidence || 0) - (a.confidence || 0))
    );

    const fontSize = 11 / k;
    ctx.font = `${fontSize}px -apple-system, 'SF Pro Text', system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.shadowColor = PALETTE.labelShadow;
    ctx.shadowBlur = 3 / k;

    const placed = [];
    const lineH = 14;                          // screen px: 11px font + leading
    let drawn = 0;
    for (const n of candidates) {
        if (drawn >= budget) break;
        const r = nodeRadius(n);
        const w = ctx.measureText(n.name).width * k;  // world units -> screen px
        const sx = n.x * k + transform.x;
        const sy = (n.y + r + 4 / k) * k + transform.y;
        const rect = { x: sx - w / 2 - 3, y: sy - 2, w: w + 6, h: lineH + 4 };
        let collides = false;
        for (const p of placed) {
            if (rect.x < p.x + p.w && rect.x + rect.w > p.x &&
                rect.y < p.y + p.h && rect.y + rect.h > p.y) { collides = true; break; }
        }
        if (collides) continue;
        placed.push(rect);
        drawn++;

        // Everything in scope (focus set, or hovered node's neighbors) is
        // intentional — neighbor labels read slightly softer than the hovered
        // node's own plate so the focal point stays dominant.
        ctx.globalAlpha = hoverActive ? 0.8 : 0.95;
        ctx.fillStyle = PALETTE.label;
        ctx.fillText(n.name, n.x, n.y + r + (4 / k));
    }
    ctx.shadowBlur = 0;
    ctx.globalAlpha = 1;
}

// Labels that fade in with zoom: a node is named once its dot's on-screen radius passes LABEL_FADE_FROM px, fully at
// LABEL_FADE_TO px. Largest dots first; a label that would overlap a placed one is skipped. The radius read is the dot's
// size at scale 1 (`baseRadius`), not the drawn one (2026-10-15): names follow the zoom, as they did, whatever scale the
// graph's size picked for its dots — the bigger dots of a 5k-node graph name no more pages at the fit zoom.
const LABEL_FADE_FROM = 3.8;
const LABEL_FADE_TO = 6;
function labelFade(screenRadius) {
    const t = Math.max(0, Math.min(1, (screenRadius - LABEL_FADE_FROM) / (LABEL_FADE_TO - LABEL_FADE_FROM)));
    return t * t * (3 - 2 * t);
}
function drawAmbientLabels() {
    const k = transform.k;
    if (baseRadius({ confidence: 1, _neighbours: R_NEIGHBOURS_CAP }) * k < LABEL_FADE_FROM) return;
    const candidates = [];
    for (const n of visibleNodes) {
        if (n.x == null || nodeIsFacet(n)) continue;
        const r = nodeRadius(n);
        if (baseRadius(n) * k < LABEL_FADE_FROM) continue;
        const sx = n.x * k + transform.x, sy = n.y * k + transform.y;
        if (sx < -100 || sx > width + 100 || sy < -20 || sy > height + 20) continue;
        if (!nodeMatchesObservers(n)) continue;
        candidates.push([r, n]);
    }
    if (!candidates.length) return;
    candidates.sort((a, b) => b[0] - a[0]);
    const fontSize = 11 / k;
    ctx.font = `${fontSize}px -apple-system, 'SF Pro Text', system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.shadowColor = PALETTE.labelShadow;
    ctx.shadowBlur = 3 / k;
    ctx.fillStyle = PALETTE.label;
    const placed = [];
    let drawn = 0;
    for (const [r, n] of candidates) {
        if (drawn >= LABEL_BUDGET) break;
        const w = ctx.measureText(n.name).width * k;
        const sx = n.x * k + transform.x;
        const sy = (n.y + r) * k + transform.y + 3;
        const rect = { x: sx - w / 2 - 2, y: sy - 1, w: w + 4, h: 15 };
        let collides = false;
        for (const p of placed) {
            if (rect.x < p.x + p.w && rect.x + rect.w > p.x && rect.y < p.y + p.h && rect.y + rect.h > p.y) { collides = true; break; }
        }
        if (collides) continue;
        placed.push(rect);
        drawn++;
        ctx.globalAlpha = 0.85 * labelFade(baseRadius(n) * k) * Math.min(1, (STATUS_ALPHA[n.status] ?? 0.92) + 0.2);
        ctx.fillText(n.name, n.x, n.y + r + 3 / k);
    }
    ctx.shadowBlur = 0;
    ctx.globalAlpha = 1;
}

// Edge labels at link midpoints with a small background plate (reuses the
// hover-plate style). Default alpha is low; edges touching the hovered node
// or inside the focus neighborhood get full strength.
function drawEdgeLabels(focusActive) {
    const k = transform.k;
    const fontSize = 9 / k;
    ctx.font = `${fontSize}px -apple-system, 'SF Pro Text', system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    for (const l of visibleLinks) {
        const src = l.source;
        const tgt = l.target;
        if (typeof src !== "object" || typeof tgt !== "object") continue;
        if (!l.label) continue;

        const inFocus = focusActive && focusSet.has(src.id) && focusSet.has(tgt.id);
        if (focusActive && !inFocus) continue;     // focus mode: only label the scope

        const touchesHover = hoveredNode &&
            (src.id === hoveredNode.id || tgt.id === hoveredNode.id);

        let alpha = 0.3;
        if (touchesHover || inFocus) alpha = 0.85;

        const mx = (src.x + tgt.x) / 2;
        const my = (src.y + tgt.y) / 2;

        const metrics = ctx.measureText(l.label);
        const padX = 3 / k;
        const padY = 2 / k;
        const boxW = metrics.width + padX * 2;
        const boxH = fontSize + padY * 2;

        ctx.globalAlpha = alpha * 0.7;
        ctx.fillStyle = PALETTE.plate;
        ctx.fillRect(mx - boxW / 2, my - boxH / 2, boxW, boxH);

        ctx.globalAlpha = alpha;
        ctx.fillStyle = PALETTE.plateText;
        ctx.fillText(l.label, mx, my);
    }
    ctx.globalAlpha = 1;
}

function drawHoverLabel(n) {
    const r = nodeRadius(n);
    const k = transform.k;
    const fontSize = 12 / k;
    ctx.font = `${fontSize}px -apple-system, 'SF Pro Text', system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const text = n.name;
    const metrics = ctx.measureText(text);
    const padX = 6 / k;
    const padY = 4 / k;
    const boxW = metrics.width + padX * 2;
    const boxH = fontSize + padY * 2;
    const boxX = n.x - boxW / 2;
    const boxY = n.y + r + (6 / k);
    ctx.globalAlpha = 0.92;
    ctx.fillStyle = PALETTE.plateStrong;
    ctx.fillRect(boxX, boxY, boxW, boxH);
    ctx.fillStyle = PALETTE.label;
    ctx.fillText(text, n.x, boxY + boxH / 2);
    ctx.globalAlpha = 1;
}

// ---------- Mouse / interaction ----------

function onWindowBlur() {
    if (!panToggled) setPanMode(false);
    cancelInteraction();
}

// A09: one cleanup for a gesture that ends without its mouseup — blur, a lost release, a pointer cancel,
// the graph going inactive. Unpins the node and drops its throw velocity, and lowers the hold's alpha
// target to 0 without a restart: no release reheat, the simulation settles on its own.
function cancelInteraction() {
    if (draggingNode) {
        // Focus mode freezes context nodes; a cancelled drag keeps that pin, as onMouseUp does.
        const keepPinned = focusNodeId && focusSet && !focusSet.has(draggingNode.id);
        if (!keepPinned) {
            draggingNode.fx = null;
            draggingNode.fy = null;
        }
        draggingNode.vx = 0;
        draggingNode.vy = 0;
        draggingNode = null;
        if (simulation) simulation.alphaTarget(0);
    }
    dragVX = 0;
    dragVY = 0;
    lastDragSample = null;
    pressStart = null;
    if (canvas) canvas.classList.remove("dragging");
}

function wireMouseEvents() {
    // Capture phase (3rd arg = true): in WebKit, capture listeners on the
    // target fire before bubble listeners, so these run before d3-zoom's
    // bubble-phase mousedown handler — which calls stopImmediatePropagation to
    // claim pan gestures and would otherwise prevent node selection entirely.
    canvas.addEventListener("mousedown", onMouseDown, true);
    canvas.addEventListener("mousemove", onMouseMove, true);
    canvas.addEventListener("mouseup", onMouseUp, true);
    canvas.addEventListener("mouseleave", onMouseLeave);
    // G84b: mouseup on the canvas only fires when the release point is over
    // the canvas (or, for our capture-phase listener, when canvas is on the
    // event's path at all). Releasing the button after dragging the cursor
    // OUTSIDE the canvas bounds never reached that listener, so the node
    // stayed pinned (fx/fy never cleared) until the next click. A window-level
    // listener catches every release regardless of where the cursor ends up.
    // onMouseUp doesn't read `event`, and it's a no-op once draggingNode is
    // already null, so this is safe to also fire for an ordinary in-canvas
    // release (it just runs twice, second time as a no-op).
    window.addEventListener("mouseup", onMouseUp);
    canvas.addEventListener("pointercancel", cancelInteraction);
    canvas.addEventListener("lostpointercapture", cancelInteraction);
}

function screenToWorld(sx, sy) {
    // Invert the zoom transform to map a client-space (CSS pixel) point
    // back into the simulation's world coordinates.
    return [(sx - transform.x) / transform.k, (sy - transform.y) / transform.k];
}

// The canvas's d3.zoom, built in one place so the tests exercise the same wiring init() does.
function makeZoom() {
    return d3.zoom()
        .scaleExtent([MIN_ZOOM, MAX_ZOOM])
        .on("zoom", (event) => {
            transform = event.transform;
            scheduleRedraw();
        })
        .on("end.background", onZoomGestureEnd);
}

// DS-3a R-DG8 — a click on EMPTY canvas: Swift closes a floating panel, else the entity column.
// Answered from d3-zoom's own gesture end, not from onMouseUp: on empty canvas d3-zoom claims the
// press, and its `mouseup.zoom` listener (window, capture phase) calls stopImmediatePropagation, so
// neither the canvas's nor the window's mouseup listener ever sees the release (final review,
// reproduced in headless Chromium). A drag past DRAG_CLICK_THRESHOLD is a pan and closes nothing;
// pan mode's every press is a pan; a press on a node never reaches here as a click (onMouseDown
// claims it); a wheel zoom's end carries a wheel sourceEvent, not a mouseup.
function onZoomGestureEnd(e) {
    const s = e && e.sourceEvent;
    if (!s || s.type !== "mouseup" || !pressStart || pressStart.onNode || pressStart.pan) return;
    const [sx, sy] = eventScreenXY(s);
    if (Math.hypot(sx - pressStart.x, sy - pressStart.y) <= DRAG_CLICK_THRESHOLD) {
        postToSwift({ type: "backgroundClicked" });
    }
    pressStart = null;
}

function eventScreenXY(event) {
    const rect = canvas.getBoundingClientRect();
    return [event.clientX - rect.left, event.clientY - rect.top];
}

function pickNode(sx, sy) {
    if (!simulation) return null;
    const [wx, wy] = screenToWorld(sx, sy);
    // simulation.find uses a quadtree so this is cheap even at 1500 nodes.
    // The search radius is in world units; we scale it by 1/k so the
    // pick target stays roughly constant in screen space.
    const pickRadius = 24 / transform.k;
    const n = simulation.find(wx, wy, pickRadius);
    return n || null;
}

// Pure, testable on its own (Tests/graph/graph-drag-velocity.test.js): given
// the timestamp of the last recorded move sample, the current time, and the
// EMA-smoothed velocity accumulated so far, decide what velocity a release
// RIGHT NOW should actually seed. A hold that's gone stale (no move sample
// within DRAG_STALE_MS of now — including "never moved," lastSampleTime ===
// null) returns zero, no matter how large vx/vy still are: a stationary node
// must release stationary. A genuinely fresh sample passes vx/vy through
// unchanged.
function seededDragVelocity(lastSampleTime, now, vx, vy) {
    if (lastSampleTime === null || now - lastSampleTime > DRAG_STALE_MS) {
        return { vx: 0, vy: 0 };
    }
    return { vx, vy };
}

function onMouseDown(event) {
    const [sx, sy] = eventScreenXY(event);
    pressStart = { x: sx, y: sy, moved: false, onNode: false, pan: false };
    if (event.shiftKey || panToggled) {
        pressStart.pan = true;
        // Pan mode: never claim the gesture, so d3-zoom's own mousedown (bubble
        // phase, after this capture listener) starts a pan even over a node.
        setPanMode(true);
        return;
    }
    const picked = pickNode(sx, sy);
    if (picked) {
        pressStart.onNode = true;
        draggingNode = picked;
        picked.fx = picked.x;
        picked.fy = picked.y;
        // G84b: reset the throw-velocity estimate for this new drag gesture —
        // a re-grab must never inherit a prior drag's momentum.
        dragVX = 0;
        dragVY = 0;
        lastDragSample = { t: performance.now(), x: picked.x, y: picked.y };
        // G109: 0.1, not 0.3 — the hold used to heat the whole graph so every
        // node jittered under the cursor (bench: KE/node 2e3-8e3 during a
        // hold, 4e-3-5.5 at 0.1). Enough alpha for the neighbours to follow.
        // 2026-10-14: and on a settled graph only the node's own neighbours follow it — every other node is held
        // where it is for this gesture's layout (item 6's `holdSettled`, released when the layout ends). A hold on a
        // leaf of the bank-shaped synthetic used to move the rest of the graph 234 wu on average (66 after the
        // settle fix, 0 now). A layout still running is left to finish: it moves everything anyway.
        if (simulation) {
            if (simulation.alpha() < simulation.alphaMin()) holdAroundDrag(picked);
            simulation.alphaTarget(0.1).restart();
        }
        canvas.classList.add("dragging");
        // Claim this gesture: d3-zoom's own mousedown listener (registered on
        // the same canvas) calls stopImmediatePropagation to start a pan, which
        // would otherwise eat our node-drag/click. We run in the capture phase
        // (see wireMouseEvents) so we get here first; stopImmediatePropagation
        // then prevents d3-zoom from firing. On empty space we do NOT stop, so
        // d3-zoom still pans.
        event.stopImmediatePropagation();
    }
}

function onMouseMove(event) {
    // A09: a drag that sees a move with no button held lost its release somewhere outside the page.
    if (draggingNode && event.buttons === 0) cancelInteraction();
    const [sx, sy] = eventScreenXY(event);
    lastPointer = { sx, sy };
    if (!draggingNode) {
        if (event.shiftKey || panToggled) { setPanMode(true); return; }
        if (panModifierHeld) setPanMode(false);
    }

    // Apply the click-vs-drag threshold uniformly regardless of whether
    // we're currently holding a node. macOS fires mousemove events on
    // sub-pixel trembles, so flipping pressStart.moved on the very first
    // move (which the drag branch used to do unconditionally) causes
    // every click to be misread as a drag and swallows nodeClicked.
    if (pressStart) {
        const dx = sx - pressStart.x;
        const dy = sy - pressStart.y;
        if (Math.hypot(dx, dy) > DRAG_CLICK_THRESHOLD) {
            pressStart.moved = true;
        }
    }

    if (draggingNode) {
        // Only actually move the node once the user has crossed the
        // threshold. Below that we still treat the gesture as a pending
        // click, which means mouseup will dispatch nodeClicked.
        if (pressStart?.moved) {
            const [wx, wy] = screenToWorld(sx, sy);
            draggingNode.fx = wx;
            draggingNode.fy = wy;

            // G84b: sample the pointer's world-space velocity so onMouseUp
            // can seed vx/vy on release and let the node coast instead of
            // stopping dead. EMA-smoothed so a single jittery sub-frame move
            // doesn't dominate the throw. performance.now() — monotonic,
            // unlike Date.now() — and it's this SAME timestamp that
            // onMouseUp later compares against to detect a stale/parked hold
            // (see seededDragVelocity, DRAG_STALE_MS).
            const now = performance.now();
            if (lastDragSample) {
                const dt = now - lastDragSample.t;
                if (dt > 0) {
                    const instVX = ((wx - lastDragSample.x) / dt) * SIM_TICK_MS;
                    const instVY = ((wy - lastDragSample.y) / dt) * SIM_TICK_MS;
                    dragVX = dragVX + (instVX - dragVX) * DRAG_VELOCITY_SMOOTHING;
                    dragVY = dragVY + (instVY - dragVY) * DRAG_VELOCITY_SMOOTHING;
                }
            }
            lastDragSample = { t: now, x: wx, y: wy };

            scheduleRedraw();
        }
        return;
    }

    // Hover pick. Only swap hoveredNode if it actually changed so we don't
    // spam redraws on every pixel of mouse movement.
    if (hoverSuppressed) {
        if (hoveredNode) { hoveredNode = null; scheduleRedraw(); }
        return;
    }
    const picked = pickNode(sx, sy);
    if (picked !== hoveredNode) {
        hoveredNode = picked;
        canvas.style.cursor = picked ? "pointer" : "";
        scheduleRedraw();
    }
}

function onMouseUp(event) {
    if (draggingNode) {
        const wasClick = pressStart && !pressStart.moved;
        const clickedId = draggingNode.id;
        // When a focus is active, context nodes stay pinned; only release the
        // drag pin if this node isn't a frozen context node.
        const keepPinned = focusNodeId && focusSet && !focusSet.has(clickedId);
        if (!keepPinned) {
            // G84b: seed the node's velocity from the tracked pointer motion
            // BEFORE clearing fx/fy. While fx/fy are set d3 zeroes vx/vy every
            // tick, so this MUST happen first — clearing the pin first would
            // hand the node back to the simulation already at rest, same as
            // before this fix. A click (never crossed the drag threshold)
            // leaves dragVX/dragVY at their reset 0, so a plain click still
            // releases the node motionless, as before.
            //
            // Devin review (PR #23): route through seededDragVelocity instead
            // of using dragVX/dragVY directly — they used to retain the last
            // movement delta indefinitely, so grab, move, PAUSE while still
            // holding, then release used to launch the (by-then stationary)
            // node off in a now-stale direction. seededDragVelocity zeroes
            // the seed whenever the last recorded move sample is older than
            // DRAG_STALE_MS at the moment of release.
            const seeded = seededDragVelocity(
                lastDragSample ? lastDragSample.t : null,
                performance.now(),
                dragVX, dragVY
            );
            draggingNode.vx = seeded.vx;
            draggingNode.vy = seeded.vy;
            draggingNode.fx = null;
            draggingNode.fy = null;
        }
        draggingNode = null;
        dragVX = 0;
        dragVY = 0;
        lastDragSample = null;
        if (simulation) {
            // G109: NO alpha bump on release. d3 integrates `x += vx *= (1 -
            // velocityDecay)` regardless of alpha, so the seeded velocity
            // coasts on its own; alpha only needs to be above alphaMin (now
            // 0.001, and the hold's alphaTarget(0.1) already raised it) so the
            // timer keeps ticking. The old `alpha(max(alpha, 0.2))` reheated
            // every node: measured ~1,000 wu mean displacement of the OTHER
            // nodes over the next second, and the link springs at alpha 0.2
            // cancelled a 26 wu/tick throw in a single tick — the "no
            // deceleration" the user saw. Now 1-30 wu and a real coast.
            simulation.alphaTarget(0).restart();
        }
        canvas.classList.remove("dragging");

        if (wasClick) {
            handleNodeClick(clickedId);
        }
    }
    // An empty-canvas click is NOT answered here: d3-zoom owns that press and its window
    // capture-phase mouseup stops the event before this listener runs. See onZoomGestureEnd.

    pressStart = null;
}

// Single click → nodeClicked (select + detail card). A second click on the
// same node within DOUBLE_CLICK_MS → enter ego/focus mode. This repurposes
// the old double-click-to-reset; reset moved to fitGraph()/the toolbar.
function handleNodeClick(id) {
    const now = Date.now();
    const isDouble = (id === lastClickId) && (now - lastClickTime < DOUBLE_CLICK_MS);
    lastClickTime = now;
    lastClickId = id;

    if (isDouble) {
        lastClickId = null;   // consume so a third click isn't a double
        setFocus(id, 2);
        try {
            window.webkit.messageHandlers.cicada.postMessage(
                JSON.stringify({ type: "nodeFocused", id, hops: 2 })
            );
        } catch (e) { /* no handler */ }
        return;
    }

    // In hubs-only mode, clicking a hub asks Swift to push the full member
    // subgraph; otherwise it's a normal selection.
    const node = visibleNodes.find(n => n.id === id) || nodes.find(n => n.id === id);
    if (hubsOnlyMode && node && nodeIsHub(node)) {
        try {
            window.webkit.messageHandlers.cicada.postMessage(
                JSON.stringify({ type: "hubExpanded", id })
            );
        } catch (e) { /* no handler */ }
        return;
    }

    try {
        window.webkit.messageHandlers.cicada.postMessage(
            JSON.stringify({ type: "nodeClicked", id })
        );
    } catch (e) { console.log("click:", id); }
}

function onMouseLeave() {
    if (hoveredNode !== null) {
        hoveredNode = null;
        scheduleRedraw();
    }
}

// ---------- Swift-facing controls ----------

// setsEqual compares two `toSet()` outputs (Set<string> or null) by value —
// used to tell a genuinely new selection from a same-value re-send (e.g.
// GraphFilter now always sends every axis, so key presence alone can't tell
// us whether anything actually changed).
function setsEqual(a, b) {
    if (a === b) return true;          // same reference, or both null
    if (!a || !b) return false;        // exactly one is null
    if (a.size !== b.size) return false;
    for (const v of a) { if (!b.has(v)) return false; }
    return true;
}

// applyFilters is the new unified filter entry point. It accepts a JSON object
// (string or object) covering every filter dimension, sets module-level state,
// and rebuilds the visible set + reheats the simulation — but ONLY when a
// set-affecting axis (types/statuses/tags/contexts/minConfidence/minDegree)
// actually changed by value. The observers axis is dim-only (see
// nodeMatchesObservers / draw()), never drops nodes from visibleNodes, so an
// observers-only change just needs a redraw — reheating for it was the
// "graph expands on every click" bug that masked whether anything filtered.
function applyFilters(payload) {
    const f = typeof payload === "string" ? JSON.parse(payload) : payload;

    const toSet = (arr) => (Array.isArray(arr) && arr.length) ? new Set(arr) : null;

    const prevTypes = filters.types;
    const prevStatuses = filters.statuses;
    const prevTags = filters.tags;
    const prevContexts = filters.contexts;
    const prevMinConfidence = filters.minConfidence;
    const prevMinDegree = filters.minDegree;

    if ("types" in f) filters.types = toSet(f.types);
    if ("statuses" in f) filters.statuses = toSet(f.statuses);
    if ("minConfidence" in f) filters.minConfidence = Number(f.minConfidence) || 0;
    if ("tags" in f) filters.tags = toSet(f.tags);
    if ("minDegree" in f) filters.minDegree = Number(f.minDegree) || 0;
    if ("contexts" in f) filters.contexts = toSet(f.contexts);
    if ("observers" in f) filters.observers = toSet(f.observers);
    // Not set-affecting: no node enters or leaves the visible set, so this
    // must not trigger a rebuild + reheat — just a repaint.
    if ("showLogos" in f) filters.showLogos = Boolean(f.showLogos);

    if (nodes.length === 0) { scheduleRedraw(); return; }

    const setAffectingChanged =
        !setsEqual(prevTypes, filters.types) ||
        !setsEqual(prevStatuses, filters.statuses) ||
        !setsEqual(prevTags, filters.tags) ||
        !setsEqual(prevContexts, filters.contexts) ||
        prevMinConfidence !== filters.minConfidence ||
        prevMinDegree !== filters.minDegree;

    if (setAffectingChanged) {
        rebuildVisible();
        rebuildNeighborsIndex();
        startSimulation({ reheat: 0.3 });
    }
    if (focusNodeId) { computeFocusSet(); applyFocusPinning(); }
    scheduleRedraw();
}

// filterTypes is retained as a thin shim over applyFilters for one release so
// in-flight Swift builds keep working. The old Swift sends every EntityType
// rawValue when "all" is selected; we treat a list that covers all base
// entity types as "no filter" (null), matching the old "null = all"
// semantics. media/hub are not counted so a stale 8-type build still clears.
const BASE_ENTITY_TYPES = ["person","project","company","concept","tool","deadline","skill","location"];
function filterTypes(enabledTypesStr) {
    const arr = JSON.parse(enabledTypesStr);
    const set = new Set(arr);
    const allBasePresent = BASE_ENTITY_TYPES.every(t => set.has(t));
    const types = allBasePresent ? null : arr;
    applyFilters({ types });
}

function setMinDegree(k) {
    const value = Number(k) || 0;
    if (value === filters.minDegree) return;
    applyFilters({ minDegree: value });
}

// ---------- Boot ----------

document.addEventListener("DOMContentLoaded", init);
