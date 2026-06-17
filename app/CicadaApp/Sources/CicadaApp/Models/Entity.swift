import Foundation

enum EntityType: String, Codable, CaseIterable, Identifiable {
    case person, project, company, concept, tool, deadline, skill, location
    case media, hub
    // Catch-all for any type the backend emits that this build doesn't know
    // yet (forward compat). Excluded from `selectableCases` so it never appears
    // as a filter checkbox, but it keeps unknown nodes on the graph instead of
    // dropping them when decoding fails.
    case unknown

    var id: String { rawValue }

    /// Types a user can filter by in the UI. `unknown` is intentionally omitted —
    /// it's an internal forward-compat bucket, not a real category.
    static var selectableCases: [EntityType] {
        allCases.filter { $0 != .unknown }
    }

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
        case .media: "photo.on.rectangle.angled"
        case .hub: "circle.hexagongrid.fill"
        case .unknown: "questionmark.circle"
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

// Added/removed lines for one entity file at one commit (backlog A1).
// NOT BUILD-VERIFIED — needs Xcode compile (M3).
struct EntityDiff: Codable, Equatable {
    let added: String
    let removed: String

    enum CodingKeys: String, CodingKey {
        case added, removed
    }
}

struct EntityHistoryEntry: Identifiable, Codable {
    var id = UUID()
    let date: String
    let changeType: HistoryChangeType
    let description: String
    // M3 (backlog A2): the agent that authored this commit — a model id
    // (e.g. "gpt-5.4-mini"), "user", or "unknown" for legacy untrailered commits.
    let author: String
    // Commit hash, used to fetch the per-commit diff on demand.
    let commitHash: String
    // Inline diff, present only when history was fetched with includeDiff=true.
    let diff: EntityDiff?

    var dateValue: Date {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: date) ?? .now
    }

    enum CodingKeys: String, CodingKey {
        case date, changeType, description, author, commitHash, diff
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        date = try c.decode(String.self, forKey: .date)
        changeType = try c.decode(HistoryChangeType.self, forKey: .changeType)
        description = try c.decode(String.self, forKey: .description)
        author = try c.decodeIfPresent(String.self, forKey: .author) ?? "unknown"
        commitHash = try c.decodeIfPresent(String.self, forKey: .commitHash) ?? ""
        diff = try c.decodeIfPresent(EntityDiff.self, forKey: .diff)
    }

    init(
        date: Date,
        changeType: HistoryChangeType,
        description: String,
        author: String = "unknown",
        commitHash: String = "",
        diff: EntityDiff? = nil
    ) {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        self.date = f.string(from: date)
        self.changeType = changeType
        self.description = description
        self.author = author
        self.commitHash = commitHash
        self.diff = diff
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(date, forKey: .date)
        try c.encode(changeType, forKey: .changeType)
        try c.encode(description, forKey: .description)
        try c.encode(author, forKey: .author)
        try c.encode(commitHash, forKey: .commitHash)
        try c.encodeIfPresent(diff, forKey: .diff)
    }
}

// Repo-wide model/user attribution (backlog A2). NOT BUILD-VERIFIED.
struct Contributor: Identifiable, Codable {
    var id: String { author }
    let author: String
    let commitCount: Int
    let fileCount: Int
    let entityCount: Int
    let files: [String]
    let lastActive: String

    enum CodingKeys: String, CodingKey {
        case author, commitCount, fileCount, entityCount, files, lastActive
    }
}

struct ContributorsResponse: Codable {
    let contributors: [Contributor]
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
    /// Verbatim file content (frontmatter + body) from the API; empty when
    /// only the placeholder graph node has loaded.
    var rawMarkdown: String = ""
    var history: [EntityHistoryEntry]

    init(
        id: String, name: String, type: EntityType, status: EntityStatus,
        confidence: Double, created: String, lastReferenced: String,
        decayRate: Double, sourceEpisodes: [String], tags: [String],
        related: [String], version: Int, markdownContent: String,
        history: [EntityHistoryEntry]
    ) {
        self.id = id
        self.name = name
        self.type = type
        self.status = status
        self.confidence = confidence
        self.created = created
        self.lastReferenced = lastReferenced
        self.decayRate = decayRate
        self.sourceEpisodes = sourceEpisodes
        self.tags = tags
        self.related = related
        self.version = version
        self.markdownContent = markdownContent
        self.history = history
    }

    enum CodingKeys: String, CodingKey {
        case id, name, type, status, confidence, created, lastReferenced
        case decayRate, sourceEpisodes, tags, related, version
        case markdownContent, rawMarkdown, history
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        // Tolerant type/status decode — a future entity type must not blank the
        // detail card or drop the entity.
        type = (try? c.decode(EntityType.self, forKey: .type)) ?? .unknown
        status = (try? c.decode(EntityStatus.self, forKey: .status)) ?? .active
        confidence = try c.decode(Double.self, forKey: .confidence)
        created = try c.decode(String.self, forKey: .created)
        lastReferenced = try c.decode(String.self, forKey: .lastReferenced)
        decayRate = try c.decode(Double.self, forKey: .decayRate)
        sourceEpisodes = try c.decodeIfPresent([String].self, forKey: .sourceEpisodes) ?? []
        tags = try c.decodeIfPresent([String].self, forKey: .tags) ?? []
        related = try c.decodeIfPresent([String].self, forKey: .related) ?? []
        version = try c.decodeIfPresent(Int.self, forKey: .version) ?? 0
        markdownContent = try c.decodeIfPresent(String.self, forKey: .markdownContent) ?? ""
        rawMarkdown = try c.decodeIfPresent(String.self, forKey: .rawMarkdown) ?? ""
        history = try c.decodeIfPresent([EntityHistoryEntry].self, forKey: .history) ?? []
    }

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
    // v2 graph fields (server is the source of truth). All optional/defaulted so
    // an old API that doesn't emit them still decodes cleanly.
    let degree: Int
    let isHub: Bool
    let hasPending: Bool
    let memberCount: Int
    let hubId: String?

    enum CodingKeys: String, CodingKey {
        case id, name, type, status, confidence, tags
        case degree, isHub, hasPending, memberCount, hubId
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        // Decode type tolerantly: a node type this build doesn't know (e.g. a
        // future entity type) must NOT drop the node off the graph. Fall back
        // to .unknown rather than throwing.
        type = (try? c.decode(EntityType.self, forKey: .type)) ?? .unknown
        status = (try? c.decode(EntityStatus.self, forKey: .status)) ?? .active
        confidence = try c.decode(Double.self, forKey: .confidence)
        // Back-compat: the backend only started emitting `tags` on GraphNode
        // recently. Decode defensively so older API builds still work.
        tags = try c.decodeIfPresent([String].self, forKey: .tags) ?? []
        degree = try c.decodeIfPresent(Int.self, forKey: .degree) ?? 0
        isHub = try c.decodeIfPresent(Bool.self, forKey: .isHub) ?? false
        hasPending = try c.decodeIfPresent(Bool.self, forKey: .hasPending) ?? false
        memberCount = try c.decodeIfPresent(Int.self, forKey: .memberCount) ?? 0
        hubId = try c.decodeIfPresent(String.self, forKey: .hubId)
    }
}
