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

enum HistoryChangeType: String, Codable {
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

struct EntityHistoryEntry: Identifiable, Codable {
    var id = UUID()
    let date: String
    let changeType: HistoryChangeType
    let description: String

    var dateValue: Date {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: date) ?? .now
    }

    enum CodingKeys: String, CodingKey {
        case date, changeType, description
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        date = try c.decode(String.self, forKey: .date)
        changeType = try c.decode(HistoryChangeType.self, forKey: .changeType)
        description = try c.decode(String.self, forKey: .description)
    }

    init(date: Date, changeType: HistoryChangeType, description: String) {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        self.date = f.string(from: date)
        self.changeType = changeType
        self.description = description
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(date, forKey: .date)
        try c.encode(changeType, forKey: .changeType)
        try c.encode(description, forKey: .description)
    }
}

struct Entity: Identifiable, Codable {
    let id: String
    var name: String
    var type: EntityType
    var status: EntityStatus
    var confidence: Double
    var created: String
    var lastReferenced: String
    var decayRate: Double
    var sourceEpisodes: [String]
    var tags: [String]
    var related: [String]
    var version: Int
    var markdownContent: String
    var history: [EntityHistoryEntry]

    var createdDate: Date {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: created) ?? .now
    }

    var lastReferencedDate: Date {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: lastReferenced) ?? .now
    }
}

struct GraphEdge: Codable {
    let source: String
    let target: String
    let label: String
}

struct GraphResponse: Codable {
    let nodes: [GraphNode]
    let links: [GraphEdge]
}

struct GraphNode: Codable {
    let id: String
    let name: String
    let type: EntityType
    let status: EntityStatus
    let confidence: Double
    let tags: [String]

    enum CodingKeys: String, CodingKey {
        case id, name, type, status, confidence, tags
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        type = try c.decode(EntityType.self, forKey: .type)
        status = try c.decode(EntityStatus.self, forKey: .status)
        confidence = try c.decode(Double.self, forKey: .confidence)
        // Back-compat: the backend only started emitting `tags` on GraphNode
        // recently. Decode defensively so older API builds still work.
        tags = try c.decodeIfPresent([String].self, forKey: .tags) ?? []
    }
}
