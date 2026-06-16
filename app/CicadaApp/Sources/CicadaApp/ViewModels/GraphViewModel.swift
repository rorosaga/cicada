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
            return d
        }

        let links = edges.map { edge -> [String: String] in
            [
                "source": edge.source,
                "target": edge.target,
                "label": edge.label,
            ]
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
