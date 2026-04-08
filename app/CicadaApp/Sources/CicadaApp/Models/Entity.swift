import Foundation

enum EntityType: String, Codable, CaseIterable, Identifiable {
    case person, project, company, concept, tool, deadline, skill, location

    var id: String { rawValue }

    var label: String {
        rawValue.capitalized
    }

    var icon: String {
        switch self {
        case .person: "person.fill"
        case .project: "folder.fill"
        case .company: "building.2.fill"
        case .concept: "lightbulb.fill"
        case .tool: "wrench.and.screwdriver.fill"
        case .deadline: "calendar.badge.clock"
        case .skill: "star.fill"
        case .location: "mappin.circle.fill"
        }
    }
}

enum EntityStatus: String, Codable, CaseIterable {
    case active, decaying, archived, dropped

    var label: String {
        rawValue.capitalized
    }
}

struct EntityHistoryEntry: Identifiable {
    let id = UUID()
    let date: Date
    let changeType: HistoryChangeType
    let description: String
}

enum HistoryChangeType {
    case created, updated, statusChange, confidenceChange, relationAdded

    var color: String {
        switch self {
        case .created: "22C55E"
        case .updated, .relationAdded: "4A9EFF"
        case .statusChange, .confidenceChange: "F59E0B"
        }
    }

    var icon: String {
        switch self {
        case .created: "plus.circle.fill"
        case .updated: "pencil.circle.fill"
        case .statusChange: "arrow.triangle.2.circlepath"
        case .confidenceChange: "chart.line.uptrend.xyaxis"
        case .relationAdded: "link"
        }
    }
}

struct Entity: Identifiable {
    let id: String
    var name: String
    var type: EntityType
    var status: EntityStatus
    var confidence: Double
    var created: Date
    var lastReferenced: Date
    var decayRate: Double
    var sourceEpisodes: [String]
    var tags: [String]
    var related: [String]
    var version: Int
    var markdownContent: String
    var history: [EntityHistoryEntry]
}
