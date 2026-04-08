import Foundation
import SwiftUI

enum ZoomAction {
    case zoomIn, out, reset
}

@Observable
final class GraphViewModel {
    var entities: [Entity] = MockData.entities
    var selectedEntity: Entity?
    var isGraphReady = false
    var zoomAction: ZoomAction?
    var enabledTypes: Set<EntityType> = Set(EntityType.allCases)
    var showTopicsList = false
    var showFilterPopover = false
    var pendingFilterUpdate = false

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
        let nodes = entities.map { entity -> [String: Any] in
            [
                "id": entity.id,
                "name": entity.name,
                "type": entity.type.rawValue,
                "status": entity.status.rawValue,
                "confidence": entity.confidence,
            ]
        }

        let links = MockData.edges.map { edge -> [String: String] in
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
        selectedEntity = entities.first { $0.id == id }
    }

    func clearSelection() {
        selectedEntity = nil
    }
}
