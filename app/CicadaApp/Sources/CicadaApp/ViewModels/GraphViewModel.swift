import Foundation
import Observation
import SwiftUI

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
    var errorMessage: String?

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
            pendingGraphUpdate = true
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
            // Stub entity: full markdown body is loaded lazily via
            // `selectEntity`/`store.entity(_:)`. §5.7 (next task) will seed
            // this from a `node.summary` placeholder field the backend
            // doesn't emit yet.
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
                markdownContent: "",
                history: []
            )
        }
        edges = response.links
        pendingGraphUpdate = true
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
    var graphDataJSON: String {
        let nodeDicts = nodes.map { node -> [String: Any] in
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

        let links = edges.map { edge -> [String: Any] in
            var d: [String: Any] = [
                "source": edge.source,
                "target": edge.target,
                "label": edge.label,
            ]
            if let context = edge.context { d["context"] = context }
            if let claimId = edge.claimId { d["claimId"] = claimId }
            return d
        }

        let data: [String: Any] = ["nodes": nodeDicts, "links": links]

        guard let jsonData = try? JSONSerialization.data(withJSONObject: data),
              let jsonString = String(data: jsonData, encoding: .utf8)
        else {
            return "{\"nodes\":[],\"links\":[]}"
        }
        return jsonString
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

    private func loadFullEntity(id: String) async {
        guard let fullEntity = await store.entity(id) else { return }
        if let idx = entities.firstIndex(where: { $0.id == id }) {
            entities[idx] = fullEntity
        }
        if selectedEntity?.id == id {
            selectedEntity = fullEntity
        }
    }
}
