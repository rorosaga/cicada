import Foundation
import Observation
import OSLog
import SwiftUI

private let graphLog = Logger(subsystem: "com.cicada.app", category: "graph-push")

enum ZoomAction {
    case zoomIn, out, reset, fit
}

/// Thin projection over `Store.graph` (§5.5). Nodes/edges/rosters are synced
/// from the store's snapshot rather than fetched independently — `loadGraph()`
/// just asks the Store to refresh; the actual data always comes from
/// `store.graph.value`, so a tab switch that recreates this VM's view renders
/// from whatever the Store already has in memory, instantly.
@Observable
@MainActor
final class GraphViewModel {
    private let store: Store

    /// Keyed on `store.graph.loadedAt` so a re-render doesn't re-map every
    /// node into an `Entity` stub on every access. `syncFromStore()` is the
    /// only place these are written.
    private(set) var entities: [Entity] = []
    private(set) var nodes: [GraphNode] = []
    private(set) var edges: [GraphEdge] = []
    /// Distinct observer wire-strings present in the graph (from `GET /graph`'s
    /// top-level `observers` roster). Drives the §3 observer filter bar.
    private(set) var observerRoster: [String] = []
    /// Distinct contexts present across nodes/edges. Drives the §2 context
    /// legend. Derived client-side from the loaded graph.
    private(set) var contextRoster: [String] = []
    private var lastSyncedLoadedAt: Date?

    /// True only when the graph has more than one distinct observer. A
    /// single-observer graph (e.g. everything asserted by `agent`) can't be
    /// meaningfully filtered — every segment would show the same slice — so
    /// `ObserverFilterBar` gates its visibility on this rather than just
    /// `observerRoster.isEmpty`.
    var hasObserverDiversity: Bool {
        observerRoster.count > 1
    }
    var selectedEntity: Entity?
    var isGraphReady = false
    var zoomAction: ZoomAction?
    var showFilterPopover = false
    var pendingFilterUpdate = false
    /// Flips true whenever a fresh graph snapshot lands (initial load, a
    /// Sleep cycle, an SSE-driven refresh) so `GraphView.updateNSView` knows
    /// to push `graphDataJSON` into the WKWebView. Set by `syncFromStore()`,
    /// which is called both explicitly from `loadGraph()` and reactively via
    /// an `withObservationTracking` loop registered in `init`, so a currently
    /// -mounted Graph tab picks up a store-driven refresh even if nothing
    /// local called `loadGraph()`.
    var pendingGraphUpdate = false
    /// The JSON string `GraphView.updateNSView` should hand to graph.js, built
    /// **off** the main actor by `prepareGraphPush` (§5.6). `updateNSView` only
    /// evaluates it — serialising a 1800-node graph on the main actor during a
    /// view update was the old hitch.
    var pendingPushJSON: String?
    /// Whether `pendingPushJSON` is a `updateGraphDelta` payload (`true`) or a
    /// full `updateGraph` payload (`false`).
    var pendingPushIsDelta = false
    var errorMessage: String?

    /// The snapshot the webview was last told about — the `old` side of the
    /// next diff. `nil` until the first push, which is therefore always full.
    private var lastPushedSnapshot: GraphResponse?
    /// Latest snapshot waiting to be turned into a push payload.
    private var queuedSnapshot: GraphResponse?
    private var isPreparingPush = false
    /// Set when the next push must be a full replace regardless of history
    /// (first push, bank switch / blank branch).
    private var forceFullNextPush = true

    /// `store.graph.isEmpty && store.graph.isRefreshing` — true only while
    /// there is genuinely nothing to show yet.
    var isLoading: Bool { store.graph.isEmpty && store.graph.isRefreshing }

    /// Shared filter state for the Graph and Topics tabs. Any mutation pushes
    /// `applyFilters` to graph.js on the next update pass — filtering happens
    /// in JS so node positions survive filter toggles.
    var filter = GraphFilter() {
        didSet { if filter != oldValue { pendingFilterUpdate = true } }
    }

    var filteredEntities: [Entity] {
        entities.filter { filter.matches($0) }
    }

    init(store: Store) {
        self.store = store
        syncFromStore()
        observeStore()
    }

    /// Registers a one-shot `withObservationTracking` on `store.graph.loadedAt`
    /// and re-registers itself after every fire, so this VM stays in sync with
    /// the Store for as long as it exists — not just while a view happens to
    /// call `loadGraph()`.
    private func observeStore() {
        withObservationTracking {
            _ = store.graph.loadedAt
        } onChange: { [weak self] in
            Task { @MainActor [weak self] in
                self?.syncFromStore()
                self?.observeStore()
            }
        }
    }

    /// Re-derive `nodes`/`edges`/rosters/`entities` from `store.graph.value`
    /// if the snapshot actually moved since the last sync. No-op on a 304 or
    /// an unrelated store refresh.
    private func syncFromStore() {
        guard store.graph.loadedAt != lastSyncedLoadedAt else { return }
        lastSyncedLoadedAt = store.graph.loadedAt
        guard let response = store.graph.value else {
            // The Store reset the graph snapshot to nil — this happens on a
            // bank switch (`Store.refresh` clears every domain before
            // re-hydrating the new bank). Without this branch the VM kept
            // rendering the *previous* bank's nodes/edges/rosters until the
            // new bank's `/graph` fetch landed, so switching banks looked
            // like nothing happened for a beat, or briefly showed a graph
            // that belongs to a different bank entirely.
            nodes = []
            edges = []
            entities = []
            observerRoster = []
            contextRoster = []
            selectedEntity = nil
            // A blank always goes over the full path: there is no meaningful
            // delta from "the previous bank's graph" to "nothing".
            forceFullNextPush = true
            lastPushedSnapshot = nil
            schedulePush(GraphResponse())
            return
        }

        nodes = response.nodes
        if !response.observers.isEmpty {
            observerRoster = response.observers
        } else {
            observerRoster = Array(Set(response.nodes.flatMap { $0.observers })).sorted()
        }
        var ctxs = Set(response.nodes.flatMap { $0.contexts })
        for n in response.nodes { if let c = n.context { ctxs.insert(c) } }
        for e in response.links { if let c = e.context { ctxs.insert(c) } }
        contextRoster = ctxs.sorted()
        entities = response.nodes.map { node in
            // Stub entity: the full markdown body is loaded lazily via
            // `selectEntity`/`store.entity(_:)`. §5.7 — seed `markdownContent`
            // from the node's server-supplied `summary` so a detail card has
            // something real to render on the very first frame instead of an
            // empty body.
            Entity(
                id: node.id,
                name: node.name,
                type: node.type,
                status: node.status,
                confidence: node.confidence,
                created: "",
                lastReferenced: "",
                decayRate: 0,
                sourceEpisodes: [],
                tags: node.tags,
                related: [],
                version: 0,
                markdownContent: node.summary ?? "",
                history: []
            )
        }
        edges = response.links
        schedulePush(response)
    }

    // MARK: - Push preparation (§5.6)

    /// Queue a snapshot for the webview. The diff + `JSONSerialization` happen
    /// in a detached task; only the resulting string comes back to the main
    /// actor, where `GraphView.updateNSView` picks it up.
    private func schedulePush(_ snapshot: GraphResponse) {
        queuedSnapshot = snapshot
        prepareGraphPush()
    }

    private func prepareGraphPush() {
        guard !isPreparingPush, let next = queuedSnapshot else { return }
        queuedSnapshot = nil
        isPreparingPush = true

        // Fall back to a full push when we can't trust the delta chain:
        // the first push, a bank switch/blank, or a still-unconsumed payload
        // (whose changes would otherwise be dropped by overwriting it with a
        // delta computed against a snapshot the webview never saw).
        let old = (forceFullNextPush || pendingPushJSON != nil) ? nil : lastPushedSnapshot
        forceFullNextPush = false
        lastPushedSnapshot = next

        Task.detached(priority: .userInitiated) { [weak self] in
            let delta = GraphDiff.diff(old: old, new: next)
            let json = GraphViewModel.encode(delta)
            let summary = delta.isFull
                ? "FULL nodes=\(delta.added.count) links=\(delta.links?.count ?? 0)"
                : "DELTA added=\(delta.added.count) updated=\(delta.updated.count) removed=\(delta.removed.count) links=\(delta.links.map { String($0.count) } ?? "unchanged")"
            // Both channels on purpose: `log show` for a bundled/launchd run,
            // stdout for the terminal-launched dev binary (the unified log is
            // not always readable from a sandboxed shell).
            graphLog.info("graph push: \(summary, privacy: .public)")
            FileHandle.standardError.write(Data("[graph-push] \(summary)\n".utf8))
            await self?.applyPreparedPush(json: json, isDelta: !delta.isFull, isEmpty: delta.isEmpty)
        }
    }

    private func applyPreparedPush(json: String, isDelta: Bool, isEmpty: Bool) {
        isPreparingPush = false
        if !isEmpty {
            pendingPushJSON = json
            pendingPushIsDelta = isDelta
            pendingGraphUpdate = true
        }
        // Drain anything that arrived while we were serialising.
        prepareGraphPush()
    }

    /// Consumed by `GraphView.updateNSView` once the payload has been handed
    /// to graph.js.
    func clearPendingPush() {
        pendingPushJSON = nil
        pendingPushIsDelta = false
        pendingGraphUpdate = false
    }

    /// Serialise a delta (or a full snapshot) into the payload graph.js wants.
    /// `nonisolated static` so it can run off the main actor.
    nonisolated static func encode(_ delta: GraphDelta) -> String {
        let fallback = "{\"nodes\":[],\"links\":[]}"
        var data: [String: Any]
        if delta.isFull {
            data = [
                "nodes": delta.added.map(nodeDict),
                "links": (delta.links ?? []).map(linkDict),
            ]
        } else {
            data = [
                "added": delta.added.map(nodeDict),
                "updated": delta.updated.map(nodeDict),
                "removed": delta.removed,
                "isFull": false,
            ]
            if let links = delta.links { data["links"] = links.map(linkDict) }
        }
        guard let jsonData = try? JSONSerialization.data(withJSONObject: data),
              let jsonString = String(data: jsonData, encoding: .utf8)
        else { return fallback }
        return jsonString
    }

    /// Single node→dict encoder shared by the full and delta payloads, so a
    /// node can never arrive at graph.js with a different shape depending on
    /// which path pushed it.
    nonisolated static func nodeDict(_ node: GraphNode) -> [String: Any] {
        var d: [String: Any] = [
            "id": node.id,
            "name": node.name,
            "type": node.type == .unknown ? "unknown" : node.type.rawValue,
            "status": node.status.rawValue,
            "confidence": node.confidence,
            "tags": node.tags,
            "degree": node.degree,
            "isHub": node.isHub,
            "hasPending": node.hasPending,
            "memberCount": node.memberCount,
        ]
        if let hubId = node.hubId { d["hubId"] = hubId }
        // Claim-layer fields (§2b/§2c): only attach when populated so the
        // payload stays lean for plain entity nodes.
        if !node.observers.isEmpty { d["observers"] = node.observers }
        if !node.contexts.isEmpty { d["contexts"] = node.contexts }
        if node.isFacet {
            d["isFacet"] = true
            if let parentId = node.parentId { d["parentId"] = parentId }
        }
        if let context = node.context { d["context"] = context }
        return d
    }

    nonisolated static func linkDict(_ edge: GraphEdge) -> [String: Any] {
        var d: [String: Any] = [
            "source": edge.source,
            "target": edge.target,
            "label": edge.label,
        ]
        if let context = edge.context { d["context"] = context }
        if let claimId = edge.claimId { d["claimId"] = claimId }
        return d
    }

    func toggleType(_ type: EntityType) {
        filter.toggleType(type)
    }

    func toggleContext(_ context: String) {
        filter.toggleContext(context)
    }

    /// Segmented observer selection (§3a). `nil` clears the filter (All); a
    /// wire-string selects exactly that observer; "external" selects every
    /// `external:*` observer in the roster. Non-matching nodes are dimmed (not
    /// deleted) by graph.js via the same focus-alpha mechanism.
    func setObserver(_ wire: String?) {
        guard let wire else { filter.observers = []; return }
        if wire == "external" {
            filter.observers = Set(observerRoster.filter { $0.hasPrefix("external:") })
        } else {
            filter.observers = [wire]
        }
    }

    /// JSON string for graph.js `applyFilters`.
    var filterJSON: String {
        guard let data = try? JSONSerialization.data(withJSONObject: filter.jsPayload),
              let json = String(data: data, encoding: .utf8)
        else { return "{}" }
        return json
    }

    /// Full unfiltered payload for graph.js `updateGraph` — includes the v2
    /// encoding fields (degree, isHub, hasPending, memberCount, hubId, tags).
    /// Kept for the Coordinator's one-shot initial push (which happens when
    /// graph.js signals `graphReady`, possibly before any prepared payload
    /// exists). Routed through the same encoders as the delta path.
    var graphDataJSON: String {
        GraphViewModel.encode(
            GraphDelta(added: nodes, updated: [], removed: [], links: edges, isFull: true)
        )
    }

    func selectEntity(id: String) {
        // Set a placeholder immediately for responsive UI
        if let existing = entities.first(where: { $0.id == id }) {
            selectedEntity = existing
        }
        // Then fetch full entity data from the Store's memoised entity cache.
        // No manual main-actor hop needed — the whole VM is already @MainActor.
        Task {
            await loadFullEntity(id: id)
        }
    }

    func clearSelection() {
        selectedEntity = nil
    }

    /// Ask the Store to refresh the graph domain. `syncFromStore()` picks up
    /// the new snapshot either here (on return) or reactively via the
    /// `observeStore()` loop if some other refresh beat this one to it.
    func loadGraph() async {
        errorMessage = nil
        await store.refresh([.graph])
        syncFromStore()
        if store.graph.value == nil {
            errorMessage = store.toast
        }
    }

    /// Fetch the full entity (through the Store's LRU cache) and swap it in
    /// over the graph-node stub, both in `entities` and — when it's the open
    /// card — in `selectedEntity`. Called by `selectEntity` and by
    /// `EntityDetailCard`'s `.task(id:)`, which renders the node `summary`
    /// immediately and upgrades to the real body when this returns.
    func loadFullEntity(id: String) async {
        guard let fullEntity = await store.entity(id) else { return }
        if let idx = entities.firstIndex(where: { $0.id == id }) {
            entities[idx] = fullEntity
        }
        if selectedEntity?.id == id {
            selectedEntity = fullEntity
        }
    }
}
