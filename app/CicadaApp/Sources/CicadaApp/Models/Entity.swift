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
    // True when the backend clipped the diff at DIFF_MAX_LINES (a truncation
    // marker line is appended to the affected side). decodeIfPresent so an older
    // backend that doesn't send this field still decodes (defaults to false).
    let truncated: Bool

    enum CodingKeys: String, CodingKey {
        case added, removed, truncated
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        added = try c.decodeIfPresent(String.self, forKey: .added) ?? ""
        removed = try c.decodeIfPresent(String.self, forKey: .removed) ?? ""
        truncated = try c.decodeIfPresent(Bool.self, forKey: .truncated) ?? false
    }

    init(added: String, removed: String, truncated: Bool = false) {
        self.added = added
        self.removed = removed
        self.truncated = truncated
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

// Repo-wide model/user attribution (backlog A2 + G15 visual identity).
struct Contributor: Identifiable, Codable {
    var id: String { author }
    let author: String
    let commitCount: Int
    let fileCount: Int
    let entityCount: Int
    let files: [String]
    let lastActive: String
    // G15 — all optional + decodeIfPresent, so this still decodes against an
    // older backend that doesn't send them. `kind` is "user" | "model" |
    // "unknown"; `provider` is "openai"|"anthropic"|"google"|"other"|nil;
    // `avatarUrl` is the user's GitHub profile picture (user-kind only).
    let kind: String?
    let provider: String?
    let avatarUrl: String?

    enum CodingKeys: String, CodingKey {
        case author, commitCount, fileCount, entityCount, files, lastActive
        case kind, provider, avatarUrl
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        author = try c.decode(String.self, forKey: .author)
        commitCount = try c.decodeIfPresent(Int.self, forKey: .commitCount) ?? 0
        fileCount = try c.decodeIfPresent(Int.self, forKey: .fileCount) ?? 0
        entityCount = try c.decodeIfPresent(Int.self, forKey: .entityCount) ?? 0
        files = try c.decodeIfPresent([String].self, forKey: .files) ?? []
        lastActive = try c.decodeIfPresent(String.self, forKey: .lastActive) ?? ""
        kind = try c.decodeIfPresent(String.self, forKey: .kind)
        provider = try c.decodeIfPresent(String.self, forKey: .provider)
        avatarUrl = try c.decodeIfPresent(String.self, forKey: .avatarUrl)
    }
}

struct ContributorsResponse: Codable {
    let contributors: [Contributor]
}

// MARK: - Location listing (issue #7)

/// One immediate child of a location entity's declared directory path. The
/// backend returns names + is-dir + size ONLY — never file contents.
struct LocationEntry: Codable, Identifiable, Hashable {
    let name: String
    let isDir: Bool
    let size: Int

    var id: String { name }

    enum CodingKeys: String, CodingKey { case name, isDir, size }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        isDir = (try? c.decode(Bool.self, forKey: .isDir)) ?? false
        size = (try? c.decode(Int.self, forKey: .size)) ?? 0
    }
}

/// `GET /entities/{id}/location` — the directory a location entity references,
/// plus a bounded listing of its immediate children. `exists`/`accessible`
/// degrade gracefully (path missing or permission denied → empty entries).
struct LocationListing: Codable {
    let path: String?
    let exists: Bool
    let accessible: Bool
    let truncated: Bool
    let entries: [LocationEntry]

    enum CodingKeys: String, CodingKey {
        case path, exists, accessible, truncated, entries
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        path = try c.decodeIfPresent(String.self, forKey: .path)
        exists = (try? c.decode(Bool.self, forKey: .exists)) ?? false
        accessible = (try? c.decode(Bool.self, forKey: .accessible)) ?? false
        truncated = (try? c.decode(Bool.self, forKey: .truncated)) ?? false
        entries = (try? c.decode([LocationEntry].self, forKey: .entries)) ?? []
    }
}

/// The nested `media:` block on a `media`-type entity (G11). Authoritative
/// shape: `api/services/media_ingestor.py::write_media_entity`. Every field is
/// optional/decode-tolerant — the backend may not surface this block yet (it
/// gets reconstructed from `rawMarkdown` frontmatter as a fallback, see
/// `Entity.init`), and individual keys (thumbnail/channel/site) are frequently
/// null (Instagram is login-walled, generic URLs may lack og:image).
struct MediaBlock: Codable, Equatable {
    /// The original saved URL. The ONLY url ever loaded in a `WebView` — never
    /// arbitrary request input (G11 security rule).
    var url: String
    /// `bookmark | youtube | instagram | url`. Drives `MediaPreview` dispatch.
    var mediaType: String
    var site: String?
    var channel: String?
    var thumbnail: String?
    var savedAt: String?
    var urlHash: String?

    enum CodingKeys: String, CodingKey {
        case url, mediaType, site, channel, thumbnail, savedAt, urlHash
    }

    init(
        url: String, mediaType: String, site: String? = nil,
        channel: String? = nil, thumbnail: String? = nil,
        savedAt: String? = nil, urlHash: String? = nil
    ) {
        self.url = url
        self.mediaType = mediaType
        self.site = site
        self.channel = channel
        self.thumbnail = thumbnail
        self.savedAt = savedAt
        self.urlHash = urlHash
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        url = try c.decodeIfPresent(String.self, forKey: .url) ?? ""
        mediaType = try c.decodeIfPresent(String.self, forKey: .mediaType) ?? "url"
        site = try c.decodeIfPresent(String.self, forKey: .site)
        channel = try c.decodeIfPresent(String.self, forKey: .channel)
        thumbnail = try c.decodeIfPresent(String.self, forKey: .thumbnail)
        savedAt = try c.decodeIfPresent(String.self, forKey: .savedAt)
        urlHash = try c.decodeIfPresent(String.self, forKey: .urlHash)
    }

    /// True when there's a real url to preview. A media entity whose frontmatter
    /// couldn't be parsed (empty url) shouldn't render a broken preview.
    var hasURL: Bool { !url.isEmpty }
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
    /// Directory path declared in a location entity's frontmatter (issue #7).
    /// Optional — only present once the backend surfaces `path:` on the
    /// EntityResponse; nil for non-location entities and for locations that
    /// don't (yet) carry a path.
    var path: String? = nil
    /// G11 — the nested `media:` block, surfaced by the backend on `media`-type
    /// entities. Decode-tolerant: nil for non-media entities and for an older
    /// backend that doesn't surface it (in which case it's reconstructed from
    /// `rawMarkdown` frontmatter, see `init`).
    var media: MediaBlock? = nil
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
        case markdownContent, rawMarkdown, path, media, history
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
        path = try c.decodeIfPresent(String.self, forKey: .path)
        // Prefer the backend-surfaced `media` block; if absent (older backend
        // that drops the nested block), reconstruct it from the `media:` YAML
        // in `rawMarkdown` so previews still work. Skip for non-media entities.
        if let decoded = try c.decodeIfPresent(MediaBlock.self, forKey: .media), decoded.hasURL {
            media = decoded
        } else if type == .media {
            media = Entity.parseMediaFrontmatter(rawMarkdown)
        } else {
            media = nil
        }
        history = try c.decodeIfPresent([EntityHistoryEntry].self, forKey: .history) ?? []
    }

    /// Fallback parser for the nested `media:` block when the backend hasn't
    /// surfaced it on the response. Reads the indented `media:` sub-keys out of
    /// the YAML frontmatter at the top of `rawMarkdown`. Tolerant and minimal:
    /// it only needs `url`/`media_type` to drive a preview; anything missing
    /// stays nil. Returns nil when there's no usable url.
    static func parseMediaFrontmatter(_ raw: String) -> MediaBlock? {
        guard !raw.isEmpty else { return nil }
        // Isolate the leading `--- ... ---` frontmatter block.
        let lines = raw.components(separatedBy: "\n")
        guard let firstFence = lines.firstIndex(where: { $0.trimmingCharacters(in: .whitespaces) == "---" })
        else { return nil }
        var fmLines: [String] = []
        var inBlock = false
        for line in lines {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed == "---" {
                if inBlock { break }   // closing fence
                inBlock = true
                continue
            }
            if inBlock { fmLines.append(line) }
        }
        _ = firstFence
        guard !fmLines.isEmpty else { return nil }
        // Find the `media:` key, then read its indented child lines.
        guard let mediaIdx = fmLines.firstIndex(where: {
            $0.trimmingCharacters(in: .whitespaces).hasPrefix("media:")
        }) else { return nil }
        var fields: [String: String] = [:]
        for line in fmLines[(mediaIdx + 1)...] {
            // Child lines are indented; a non-indented line ends the block.
            guard line.first == " " || line.first == "\t" else { break }
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard let colon = trimmed.firstIndex(of: ":") else { continue }
            let key = String(trimmed[..<colon]).trimmingCharacters(in: .whitespaces)
            var value = String(trimmed[trimmed.index(after: colon)...]).trimmingCharacters(in: .whitespaces)
            // Strip surrounding quotes if present.
            if value.count >= 2, value.first == "\"", value.last == "\"" {
                value = String(value.dropFirst().dropLast())
            }
            if value == "null" || value == "~" { value = "" }
            if !value.isEmpty { fields[key] = value }
        }
        let url = fields["url"] ?? ""
        guard !url.isEmpty else { return nil }
        return MediaBlock(
            url: url,
            mediaType: fields["media_type"] ?? "url",
            site: fields["site"],
            channel: fields["channel"],
            thumbnail: fields["thumbnail"],
            savedAt: fields["saved_at"],
            urlHash: fields["url_hash"]
        )
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
    // Claim-layer fields (§2a). Optional/decode-tolerant so the existing flat
    // graph payload still decodes; `context` colors the edge stroke and
    // `claimId` ties the edge back to the claim that asserts it.
    let context: String?
    let claimId: String?

    enum CodingKeys: String, CodingKey {
        case source, target, label, context, claimId
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        source = try c.decode(String.self, forKey: .source)
        target = try c.decode(String.self, forKey: .target)
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? ""
        context = try c.decodeIfPresent(String.self, forKey: .context)
        claimId = try c.decodeIfPresent(String.self, forKey: .claimId)
    }

    init(source: String, target: String, label: String,
         context: String? = nil, claimId: String? = nil) {
        self.source = source
        self.target = target
        self.label = label
        self.context = context
        self.claimId = claimId
    }
}

struct GraphResponse: Codable {
    let nodes: [GraphNode]
    let links: [GraphEdge]
    // §3: distinct-observer roster so the observer filter bar can populate its
    // segments without a separate call. Optional/decode-tolerant.
    let observers: [String]

    enum CodingKeys: String, CodingKey { case nodes, links, observers }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        nodes = try c.decodeIfPresent([GraphNode].self, forKey: .nodes) ?? []
        links = try c.decodeIfPresent([GraphEdge].self, forKey: .links) ?? []
        observers = try c.decodeIfPresent([String].self, forKey: .observers) ?? []
    }
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
    // Claim-layer fields (§2b/§2c). All optional/decode-tolerant so the
    // existing graph payload still decodes. `observers`/`contexts` drive the
    // node badges + filtering; `isFacet`/`parentId`/`context` describe a facet
    // satellite node (`id: "rodrigo#engineering"`).
    let observers: [String]
    let contexts: [String]
    let isFacet: Bool
    let parentId: String?
    let context: String?

    enum CodingKeys: String, CodingKey {
        case id, name, type, status, confidence, tags
        case degree, isHub, hasPending, memberCount, hubId
        case observers, contexts, isFacet, parentId, context
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
        observers = try c.decodeIfPresent([String].self, forKey: .observers) ?? []
        contexts = try c.decodeIfPresent([String].self, forKey: .contexts) ?? []
        isFacet = try c.decodeIfPresent(Bool.self, forKey: .isFacet) ?? false
        parentId = try c.decodeIfPresent(String.self, forKey: .parentId)
        context = try c.decodeIfPresent(String.self, forKey: .context)
    }
}
