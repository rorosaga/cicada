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
// hues on the darker #0E0F14 base so all 8 pop and clear ~4.5:1+ contrast.
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
    unknown:  "#9BA1AE",
};

// Soft per-type cluster anchors. These are only used by the xType/yType
// forces at low strength, so the layout still obeys link and charge forces
// — the anchors just nudge same-type nodes toward each other. Obsidian-like
// grouping without a Louvain pass. Nodes that orbit a hub use hubGravity
// instead (see startSimulation) and ignore these anchors.
const typeClusterPositions = {
    person:   [   0, -300],
    project:  [ 280, -100],
    company:  [ 180,  240],
    concept:  [-180,  240],
    tool:     [-280, -100],
    deadline: [   0,  300],
    skill:    [ 300,  100],
    location: [-300,  100],
    media:    [ -60, -360],
    directory:[ -300, -240],
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
    agent:    "#8896FF",   // accent
    rodrigo:  "#5AA8FF",   // blue (person)
    external: "#F65BA6",   // pink (media)
};
function hashHue(str) {
    let h = 0;
    for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0;
    return Math.abs(h) % 360;
}
function contextColor(context) {
    if (!context) return "#262A33";   // = CicadaTheme.border (contextless edge)
    if (CONTEXT_COLORS[context]) return CONTEXT_COLORS[context];
    return `hsl(${hashHue(context)}, 55%, 68%)`;
}
function observerBadgeColor(wire) {
    if (!wire) return OBSERVER_BADGE_COLORS.agent;
    if (wire.startsWith("external:")) return OBSERVER_BADGE_COLORS.external;
    return OBSERVER_BADGE_COLORS[wire] || OBSERVER_BADGE_COLORS.external;
}

const MIN_ZOOM = 0.2;
const MAX_ZOOM = 6.0;
const LABEL_MIN_SCREEN_RADIUS = 6;  // only label nodes whose on-screen radius clears this
const DRAG_CLICK_THRESHOLD = 4;     // pixels of movement before a mousedown becomes a drag
const DOUBLE_CLICK_MS = 320;        // window for the second click of a double-click

// Three semantic-zoom tiers. Below HUBS_ONLY only hub labels and hub-touching
// links draw; between HUBS_ONLY and NODE_LABELS big nodes get labels; past
// NODE_LABELS everything visible gets labels; past EDGE_LABELS edge labels
// appear at link midpoints.
const ZOOM_HUBS_ONLY   = 0.45;
const ZOOM_NODE_LABELS = 1.2;
const ZOOM_EDGE_LABELS = 2.2;

const LABEL_BUDGET = 200;           // max node labels rendered per frame

const STATUS_ALPHA = { active: 0.92, decaying: 0.5, archived: 0.28, dropped: 0.0 };

const HUB_RING_FLOOR = 22;          // minimum radius for a hub node
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
    minDegree: 1,       // default drops only fully isolated nodes
    contexts: null,     // null = all contexts; otherwise Set<string> — DROPS non-matching edges/facets
    observers: null,    // null = all observers; otherwise Set<string> — DIMS non-matching nodes (kept visible)
};

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
let draggingNode = null;
let pressStart = null;          // { x, y } screen coords of mousedown for click-vs-drag
let lastClickTime = 0;          // for double-click detection
let lastClickId = null;

let hubsOnlyMode = false;       // set true when the payload is the hubs-only tier

let needsRedraw = false;
let rafHandle = null;

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
function centerOnce() {
    if (hasCentered || width <= 0 || height <= 0 || !currentZoom) return;
    hasCentered = true;
    d3.select(canvas).call(
        currentZoom.transform,
        d3.zoomIdentity.translate(width / 2, height / 2).scale(0.6),
    );
}

function init() {
    canvas = document.getElementById("graph");
    ctx = canvas.getContext("2d");

    resizeCanvas();
    window.addEventListener("resize", () => {
        resizeCanvas();
        // The WKWebView is created with a zero frame and only gets its real
        // size from the SwiftUI layout pass AFTER this script ran — without
        // this re-center the origin stays at the top-left corner and the
        // whole graph renders off-canvas (the "blank graph" bug).
        centerOnce();
        scheduleRedraw();
    });

    // Zoom/pan. We drive d3.zoom on the canvas element and store the result
    // in a local transform object; draw() applies that transform manually
    // in world space via ctx.translate/scale. We do NOT set a DOM transform
    // attribute anymore — there is no DOM tree under the canvas to move.
    currentZoom = d3.zoom()
        .scaleExtent([MIN_ZOOM, MAX_ZOOM])
        .on("zoom", (event) => {
            transform = event.transform;
            scheduleRedraw();
        });
    d3.select(canvas).call(currentZoom);

    // Initial centering transform — put origin in the middle of the canvas
    // at a slightly-zoomed-out starting scale so the whole graph is visible.
    // No-op while the canvas is still 0x0; the resize listener retries.
    centerOnce();

    // Suppress d3's default double-click zoom; double-click is our focus
    // gesture now (handled in onMouseUp, not here).
    d3.select(canvas).on("dblclick.zoom", null);

    // ESC clears focus mode. Swift's detail-card ESC handling is independent;
    // when no focus is active this is a no-op so the two don't collide.
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && focusNodeId) {
            e.preventDefault();
            clearFocus();
        }
    });

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

function fitGraph() {
    if (!visibleNodes.length) { zoomReset(); return; }
    const t = transformForNodes(visibleNodes, 60);
    if (!t) { zoomReset(); return; }
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
    const hadPrev = prevPositions.size > 0;

    nodes = data.nodes || [];
    links = data.links || [];
    hubsOnlyMode = Boolean(data.hubsOnly ?? data.hubs_only);

    computeDegree();
    buildHubIndex();

    // 2. seed positions: reuse previous for known nodes; place genuinely-new
    // nodes near their hub or type anchor.
    for (const n of nodes) {
        const p = prevPositions.get(n.id);
        if (p) {
            n.x = p.x; n.y = p.y; n.vx = p.vx || 0; n.vy = p.vy || 0;
        } else {
            const s = seedPositionFor(n);
            n.x = s.x; n.y = s.y; n.vx = 0; n.vy = 0;
        }
    }

    rebuildVisible();
    rebuildNeighborsIndex();
    startSimulation({ reheat: hadPrev ? 0.3 : 1.0 });

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
    links.forEach(l => {
        const sid = typeof l.source === "object" ? l.source.id : l.source;
        const tid = typeof l.target === "object" ? l.target.id : l.target;
        degreeMap.set(sid, (degreeMap.get(sid) || 0) + 1);
        degreeMap.set(tid, (degreeMap.get(tid) || 0) + 1);
    });
    nodes.forEach(n => {
        const computed = degreeMap.get(n.id) || 0;
        // Local degree drives min-degree visibility; keep it on _localDegree.
        n._localDegree = computed;
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

function seedPositionFor(n) {
    const jitter = () => (Math.random() - 0.5) * 60;
    // If the node belongs to a hub and that hub already has a position, seed
    // near it so new members land in the right cluster.
    const hid = memberToHub.get(n.id);
    if (hid) {
        const hub = nodes.find(x => x.id === hid);
        if (hub && hub.x != null) return { x: hub.x + jitter(), y: hub.y + jitter() };
        const anchor = hubAnchors.get(hid);
        if (anchor) return { x: anchor[0] + jitter(), y: anchor[1] + jitter() };
    }
    if (nodeIsHub(n)) {
        const anchor = hubAnchors.get(n.id);
        if (anchor) return { x: anchor[0] + jitter(), y: anchor[1] + jitter() };
    }
    const type = typeClusterPositions[n.type];
    if (type) return { x: type[0] + jitter(), y: type[1] + jitter() };
    return { x: jitter(), y: jitter() };
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
function hubGravityForce(strength) {
    let force;
    function tick() {
        if (!memberToHub.size) return;
        const byId = new Map(visibleNodes.map(n => [n.id, n]));
        for (const n of visibleNodes) {
            const hid = memberToHub.get(n.id);
            if (!hid) continue;
            const hub = byId.get(hid);
            if (!hub) continue;
            n.vx += (hub.x - n.x) * strength;
            n.vy += (hub.y - n.y) * strength;
        }
    }
    force = tick;
    return force;
}

function startSimulation({ reheat = 1.0 } = {}) {
    if (simulation) simulation.stop();

    simulation = d3.forceSimulation(visibleNodes)
        // Alpha/velocity tuning for dense graphs. Defaults are fine for a
        // hundred nodes; at 1500 they keep the sim bouncing indefinitely.
        .alphaDecay(0.05)
        .velocityDecay(0.55)
        .alphaMin(0.05)
        .force("link", d3.forceLink(visibleLinks)
            .id(d => d.id)
            .distance(60)
            .strength(0.5))
        .force("charge", d3.forceManyBody()
            .strength(-40)
            .distanceMax(400)
            .theta(0.9))
        .force("center", d3.forceCenter(0, 0).strength(0.05))
        .force("collision", d3.forceCollide()
            .radius(d => nodeRadius(d) + 2)
            .strength(0.8))
        // Hubs are pulled toward their ring anchor; members toward their hub.
        // Nodes with no hub fall back to the soft per-type anchor below.
        .force("xType", d3.forceX(d => xAnchor(d)).strength(d => anchorStrength(d, "x")))
        .force("yType", d3.forceY(d => yAnchor(d)).strength(d => anchorStrength(d, "y")))
        .force("hubGravity", hubGravityForce(0.05))
        .on("tick", scheduleRedraw)
        .on("end", () => { simulation.stop(); });

    simulation.alpha(reheat).restart();
}

function xAnchor(d) {
    if (nodeIsHub(d) && hubAnchors.has(d.id)) return hubAnchors.get(d.id)[0];
    return typeClusterPositions[d.type]?.[0] ?? 0;
}

function yAnchor(d) {
    if (nodeIsHub(d) && hubAnchors.has(d.id)) return hubAnchors.get(d.id)[1];
    return typeClusterPositions[d.type]?.[1] ?? 0;
}

function anchorStrength(d) {
    if (nodeIsHub(d) && hubAnchors.has(d.id)) return 0.08;  // hubs anchor strongly
    if (memberToHub.has(d.id)) return 0;                    // hubGravity handles members
    return 0.04;                                            // soft type clustering
}

function nodeRadius(d) {
    // Confidence is the primary size channel so "bigger = more confident" is
    // preattentive and not dominated by hub degree. Degree is a secondary
    // bump. Hubs get a size floor + multiplier so they read as the top tier.
    // §2c: facet satellites are deliberately small — they orbit their parent
    // and read as context tags, not first-class subjects.
    if (nodeIsFacet(d)) return 3 + (d.confidence || 0) * 4;
    const base = 4;
    const confTerm = (d.confidence || 0) * 8;       // primary: 0–8 px
    const degreeTerm = Math.sqrt(nodeDegree(d)) * 1.5;  // secondary
    let r = base + confTerm + degreeTerm;
    if (nodeIsHub(d)) r = Math.max(r * 1.6, HUB_RING_FLOOR);
    return r;
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
        } else if (!draggingNode || draggingNode.id !== n.id) {
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
    if (needsRedraw) return;
    needsRedraw = true;
    rafHandle = requestAnimationFrame(() => {
        needsRedraw = false;
        if (anyPending) pulsePhase += 0.016;
        draw();
        // Keep redrawing while the sim is still producing movement. Once
        // alpha drops below alphaMin the sim stops on its own. We also keep
        // scheduling frames when any visible node has a pending item so the
        // pulse ring animates — gated on anyPending so idle graphs with no
        // pending items still drop to zero CPU.
        const simActive = simulation && simulation.alpha() > simulation.alphaMin();
        if (simActive || anyPending) {
            scheduleRedraw();
        }
    });
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
    const lowZoom = transform.k < ZOOM_HUBS_ONLY;

    // ---- Links ----
    // Single stroke path per link. We don't batch paths because each link
    // can have its own alpha depending on hover/focus state, and
    // beginPath/stroke per link is cheap at 1500-edge scale. At low zoom we
    // cull leaf-to-leaf links (only links touching a hub draw) since
    // individual leaf edges are invisible anyway and this halves the draw
    // cost on dense graphs.
    for (const l of visibleLinks) {
        const src = l.source;
        const tgt = l.target;
        if (typeof src !== "object" || typeof tgt !== "object") continue;

        if (lowZoom && !nodeIsHub(src) && !nodeIsHub(tgt)) continue;

        let alpha = 0.35;
        if (focusActive) {
            const bothIn = focusSet.has(src.id) && focusSet.has(tgt.id);
            alpha = bothIn ? 0.5 : 0.04;
        }
        if (hoverActive) {
            const touchesHover =
                src.id === hoveredNode.id ||
                tgt.id === hoveredNode.id;
            if (!touchesHover) alpha = Math.min(alpha, 0.08);
            else alpha = 0.8;
        }

        ctx.globalAlpha = alpha;
        // §2a: context-colored edges. An edge with a context paints in its
        // context hue; a contextless (legacy) edge keeps the flat gray.
        ctx.strokeStyle = l.context ? contextColor(l.context) : "#262A33";
        ctx.lineWidth = 1 / transform.k;
        ctx.beginPath();
        ctx.moveTo(src.x, src.y);
        ctx.lineTo(tgt.x, tgt.y);
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
        const isHub = nodeIsHub(n);

        // Status drives base opacity. Focus dimming and hover dimming stack on
        // top: a node outside the focus neighborhood fades to context.
        let alpha = STATUS_ALPHA[n.status] ?? 0.92;
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
        // fill so the node sits on top.
        if (nodeHasPending(n) && alpha > 0.1) {
            const t = pulsePhase % 1;
            const pr = r + (6 + t * 10) / transform.k;
            ctx.globalAlpha = (1 - t) * 0.6 * alpha;
            ctx.lineWidth = 2 / transform.k;
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

        if (n.status === "decaying") {
            ctx.stroke();
            ctx.setLineDash([]);
        }

        ctx.shadowBlur = 0;

        // Hub ring — a second concentric stroke marking the top visual tier.
        if (isHub) {
            ctx.globalAlpha = alpha;
            ctx.lineWidth = 2 / transform.k;
            ctx.strokeStyle = color;
            ctx.beginPath();
            ctx.arc(n.x, n.y, r + 4 / transform.k, 0, Math.PI * 2);
            ctx.stroke();
        }

        // Search highlight — a bright outer ring on matched nodes so they
        // glow in place while the user types in the toolbar search.
        if (searchHighlight && searchHighlight.has(n.id)) {
            ctx.globalAlpha = 1;
            ctx.lineWidth = 2.5 / transform.k;
            ctx.strokeStyle = "#FFFFFF";
            ctx.beginPath();
            ctx.arc(n.x, n.y, r + 6 / transform.k, 0, Math.PI * 2);
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
    // Labels are off by default — a dense graph with ambient labels is
    // unreadable (see the word-soup screenshots). They appear only when the
    // user expresses intent: hovering a node (label it + its neighbors) or
    // entering focus mode (label the drilled-in neighborhood).
    if (hoverActive || focusActive) {
        drawNodeLabels(hoverActive, neighbors, focusActive);
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
// neighborhood, or (on hover) the hovered node's direct neighbors. There are
// no ambient labels — scope is always small here, so the work is to rank by
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
    ctx.shadowColor = "rgba(0,0,0,0.85)";
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
        ctx.fillStyle = "#ECEDF2";   // = CicadaTheme.textPrimary
        ctx.fillText(n.name, n.x, n.y + r + (4 / k));
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
        ctx.fillStyle = "rgba(14, 15, 20, 0.85)";   // = CicadaTheme.background
        ctx.fillRect(mx - boxW / 2, my - boxH / 2, boxW, boxH);

        ctx.globalAlpha = alpha;
        ctx.fillStyle = "#C7CBD6";
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
    ctx.fillStyle = "rgba(14, 15, 20, 0.92)";   // = CicadaTheme.background
    ctx.fillRect(boxX, boxY, boxW, boxH);
    ctx.fillStyle = "#ECEDF2";   // = CicadaTheme.textPrimary
    ctx.fillText(text, n.x, boxY + boxH / 2);
    ctx.globalAlpha = 1;
}

// ---------- Mouse / interaction ----------

function wireMouseEvents() {
    // Capture phase (3rd arg = true): in WebKit, capture listeners on the
    // target fire before bubble listeners, so these run before d3-zoom's
    // bubble-phase mousedown handler — which calls stopImmediatePropagation to
    // claim pan gestures and would otherwise prevent node selection entirely.
    canvas.addEventListener("mousedown", onMouseDown, true);
    canvas.addEventListener("mousemove", onMouseMove, true);
    canvas.addEventListener("mouseup", onMouseUp, true);
    canvas.addEventListener("mouseleave", onMouseLeave);
}

function screenToWorld(sx, sy) {
    // Invert the zoom transform to map a client-space (CSS pixel) point
    // back into the simulation's world coordinates.
    return [(sx - transform.x) / transform.k, (sy - transform.y) / transform.k];
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

function onMouseDown(event) {
    const [sx, sy] = eventScreenXY(event);
    pressStart = { x: sx, y: sy, moved: false };
    const picked = pickNode(sx, sy);
    if (picked) {
        draggingNode = picked;
        picked.fx = picked.x;
        picked.fy = picked.y;
        if (simulation) simulation.alphaTarget(0.3).restart();
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
    const [sx, sy] = eventScreenXY(event);

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
            scheduleRedraw();
        }
        return;
    }

    // Hover pick. Only swap hoveredNode if it actually changed so we don't
    // spam redraws on every pixel of mouse movement.
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
            draggingNode.fx = null;
            draggingNode.fy = null;
        }
        draggingNode = null;
        if (simulation) simulation.alphaTarget(0);
        canvas.classList.remove("dragging");

        if (wasClick) {
            handleNodeClick(clickedId);
        }
    }

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

// applyFilters is the new unified filter entry point. It accepts a JSON object
// (string or object) covering every filter dimension, sets module-level state,
// rebuilds the visible set, and does a soft reheat instead of a full restart.
function applyFilters(payload) {
    const f = typeof payload === "string" ? JSON.parse(payload) : payload;

    const toSet = (arr) => (Array.isArray(arr) && arr.length) ? new Set(arr) : null;

    if ("types" in f) filters.types = toSet(f.types);
    if ("statuses" in f) filters.statuses = toSet(f.statuses);
    if ("minConfidence" in f) filters.minConfidence = Number(f.minConfidence) || 0;
    if ("tags" in f) filters.tags = toSet(f.tags);
    if ("minDegree" in f) filters.minDegree = Number(f.minDegree) || 0;
    if ("contexts" in f) filters.contexts = toSet(f.contexts);
    if ("observers" in f) filters.observers = toSet(f.observers);

    if (nodes.length === 0) { scheduleRedraw(); return; }

    rebuildVisible();
    rebuildNeighborsIndex();
    startSimulation({ reheat: 0.3 });
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
