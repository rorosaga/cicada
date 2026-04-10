import Foundation
import SwiftUI

enum ZoomAction {
    case zoomIn, out, reset
}

@Observable
final class GraphViewModel {
    var entities: [Entity] = []
    var edges: [GraphEdge] = []
    var selectedEntity: Entity?
    var isGraphReady = false
    var zoomAction: ZoomAction?
    var enabledTypes: Set<EntityType> = Set(EntityType.allCases)
    var showFilterPopover = false
    var pendingFilterUpdate = false
    var pendingGraphUpdate = false
    var isLoading = false
    var errorMessage: String?

    var filteredEntities: [Entity] {
        entities.filter { enabledTypes.contains($0.type) }
    }

    func toggleType(_ type: EntityType) {
        if enabledTypes.contains(type) {
            enabledTypes.remove(type)
        } else {
            enabledTypes.insert(type)
        }
        pendingFilterUpdate = true
    }

    var graphDataJSON: String {
        let nodes = filteredEntities.map { entity -> [String: Any] in
            [
                "id": entity.id,
                "name": entity.name,
                "type": entity.type.rawValue,
                "status": entity.status.rawValue,
                "confidence": entity.confidence,
            ]
        }

        let filteredIds = Set(filteredEntities.map(\.id))
        let links = edges
            .filter { filteredIds.contains($0.source) && filteredIds.contains($0.target) }
            .map { edge -> [String: String] in
                [
                    "source": edge.source,
                    "target": edge.target,
                    "label": edge.label,
                ]
            }

        let data: [String: Any] = ["nodes": nodes, "links": links]

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
