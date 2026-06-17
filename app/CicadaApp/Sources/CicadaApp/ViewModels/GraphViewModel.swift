import Foundation
import SwiftUI

enum ZoomAction {
    case zoomIn, out, reset, fit
}

@Observable
final class GraphViewModel {
    var entities: [Entity] = []
    var nodes: [GraphNode] = []
    var edges: [GraphEdge] = []
    /// Distinct observer wire-strings present in the graph (from `GET /graph`'s
    /// top-level `observers` roster). Drives the §3 observer filter bar.
    var observerRoster: [String] = []
    /// Distinct contexts present across nodes/edges. Drives the §2 context
    /// legend. Derived client-side from the loaded graph.
    var contextRoster: [String] = []
    var selectedEntity: Entity?
    var isGraphReady = false
    var zoomAction: ZoomAction?
    var showFilterPopover = false
    var pendingFilterUpdate = false
    var pendingGraphUpdate = false
    var isLoading = false
    var errorMessage: String?

    /// Shared filter state for the Graph and Topics tabs. Any mutation pushes
    /// `applyFilters` to graph.js on the next update pass — filtering happens
    /// in JS so node positions survive filter toggles.
    var filter = GraphFilter() {
        didSet { if filter != oldValue { pendingFilterUpdate = true } }
    }

    var filteredEntities: [Entity] {
        entities.filter { filter.matches($0) }
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
        // Then fetch full entity data from API. Pin the follow-up to the
        // main actor — @Observable writes from a background thread don't
        // reliably trigger SwiftUI re-renders, which is why the detail
        // card was stuck showing the placeholder with empty markdown.
        Task { @MainActor in
            await loadFullEntity(id: id)
        }
    }

    func clearSelection() {
        selectedEntity = nil
    }

    func loadGraph() async {
        isLoading = true
        errorMessage = nil
        do {
            let response = try await APIClient.shared.fetchGraph()
            nodes = response.nodes
            // Observer roster: prefer the server-supplied top-level list; fall
            // back to the distinct observers across nodes if absent.
            if !response.observers.isEmpty {
                observerRoster = response.observers
            } else {
                observerRoster = Array(Set(response.nodes.flatMap { $0.observers })).sorted()
            }
            // Context roster: distinct contexts across node facets + edges.
            var ctxs = Set(response.nodes.flatMap { $0.contexts })
            for n in response.nodes { if let c = n.context { ctxs.insert(c) } }
            for e in response.links { if let c = e.context { ctxs.insert(c) } }
            contextRoster = ctxs.sorted()
            entities = response.nodes.map { node in
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
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    @MainActor
    private func loadFullEntity(id: String) async {
        do {
            let fullEntity = try await APIClient.shared.fetchEntity(id: id)
            if let idx = entities.firstIndex(where: { $0.id == id }) {
                entities[idx] = fullEntity
            }
            if selectedEntity?.id == id {
                selectedEntity = fullEntity
            }
        } catch {
            print("Failed to load entity \(id): \(error)")
        }
    }
}
