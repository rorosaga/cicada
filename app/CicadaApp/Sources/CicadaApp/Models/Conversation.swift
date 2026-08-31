import Foundation

/// One conversation that wrote to memory (G48 §3) — a live MCP session or an
/// imported chat thread. Wire is camelCase (`api/models/schemas.py::ConversationSummary`,
/// a `CamelModel`), and every field but `conversationId` is optional-with-a-default
/// so an older backend decodes instead of throwing.
struct ConversationSummary: Identifiable, Codable, Hashable {
    var id: String { conversationId }

    let conversationId: String
    let kind: String          // "mcp" | "import"
    let harness: String
    let origin: String
    let title: String
    let firstSeen: String
    let lastSeen: String
    let episodeCount: Int
    let entityIds: [String]
    let entityCount: Int
    let model: String?
    let resumable: Bool

    /// How many touched entities the backend withheld from `entityIds`
    /// (capped at `session_stats.MAX_CONVERSATION_ENTITIES`).
    var hiddenEntityCount: Int { max(0, entityCount - entityIds.count) }

    /// A name for the row when the backend had no episode title to offer.
    var displayTitle: String { title.isEmpty ? "Untitled conversation" : title }

    init(
        conversationId: String,
        kind: String = "mcp",
        harness: String = "",
        origin: String = "",
        title: String = "",
        firstSeen: String = "",
        lastSeen: String = "",
        episodeCount: Int = 0,
        entityIds: [String] = [],
        entityCount: Int = 0,
        model: String? = nil,
        resumable: Bool = false
    ) {
        self.conversationId = conversationId
        self.kind = kind
        self.harness = harness
        self.origin = origin
        self.title = title
        self.firstSeen = firstSeen
        self.lastSeen = lastSeen
        self.episodeCount = episodeCount
        self.entityIds = entityIds
        self.entityCount = entityCount
        self.model = model
        self.resumable = resumable
    }

    enum CodingKeys: String, CodingKey {
        case conversationId, kind, harness, origin, title, firstSeen, lastSeen
        case episodeCount, entityIds, entityCount, model, resumable
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        conversationId = try c.decode(String.self, forKey: .conversationId)
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "mcp"
        harness = try c.decodeIfPresent(String.self, forKey: .harness) ?? ""
        origin = try c.decodeIfPresent(String.self, forKey: .origin) ?? ""
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        firstSeen = try c.decodeIfPresent(String.self, forKey: .firstSeen) ?? ""
        lastSeen = try c.decodeIfPresent(String.self, forKey: .lastSeen) ?? ""
        episodeCount = try c.decodeIfPresent(Int.self, forKey: .episodeCount) ?? 0
        let ids = try c.decodeIfPresent([String].self, forKey: .entityIds) ?? []
        entityIds = ids
        // Fall back to the ids we were sent so an older backend never produces
        // a phantom "+N more".
        entityCount = try c.decodeIfPresent(Int.self, forKey: .entityCount) ?? ids.count
        model = try c.decodeIfPresent(String.self, forKey: .model)
        resumable = try c.decodeIfPresent(Bool.self, forKey: .resumable) ?? false
    }
}

/// How to reopen a conversation (G48 §5). The backend validated everything in
/// here; `TerminalLauncher` re-gates before interpolating, as defence in depth.
struct ResumeDescriptor: Codable, Hashable {
    let mode: String
    let argv: [String]
    let cwd: String?
    let displayCommand: String

    init(mode: String = "terminal", argv: [String] = [],
         cwd: String? = nil, displayCommand: String = "") {
        self.mode = mode
        self.argv = argv
        self.cwd = cwd
        self.displayCommand = displayCommand
    }

    enum CodingKeys: String, CodingKey { case mode, argv, cwd, displayCommand }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        mode = try c.decodeIfPresent(String.self, forKey: .mode) ?? "terminal"
        argv = try c.decodeIfPresent([String].self, forKey: .argv) ?? []
        cwd = try c.decodeIfPresent(String.self, forKey: .cwd)
        displayCommand = try c.decodeIfPresent(String.self, forKey: .displayCommand) ?? ""
    }
}
