import Foundation

/// The kinds `api/services/source_overview.KIND_ORDER` declares, plus a
/// fallback so an unknown kind from a newer backend never drops the grid.
enum SourceKind: String, Codable, CaseIterable {
    case harness, browser, social, feed, messaging, `import`, unknown

    /// Grid order = the backend's `KIND_ORDER`; `unknown` sorts last.
    static let order: [SourceKind] = [.harness, .browser, .social, .feed, .messaging, .import, .unknown]
}

/// Mirror of `api/models/schemas.py::SourceOverview` (G124). Every field but
/// `id` is optional-with-a-default so an older backend — or a row with no
/// state at all — still yields a usable card.
struct SourceOverview: Codable, Identifiable, Hashable {
    let id: String
    let label: String
    let kind: SourceKind
    let mark: String
    let conversations: Int
    let episodes: Int
    let entities: Int
    let items: Int
    let lastActivityAt: String?
    let connected: Bool
    let lastError: String?
    let actions: [String]
    let channelId: String?
    let origins: [String]
    let harness: String?

    init(id: String, label: String, kind: SourceKind, mark: String = "", conversations: Int = 0,
         episodes: Int = 0, entities: Int = 0, items: Int = 0, lastActivityAt: String? = nil,
         connected: Bool = false, lastError: String? = nil, actions: [String] = [],
         channelId: String? = nil, origins: [String] = [], harness: String? = nil) {
        self.id = id; self.label = label; self.kind = kind; self.mark = mark
        self.conversations = conversations; self.episodes = episodes; self.entities = entities
        self.items = items; self.lastActivityAt = lastActivityAt; self.connected = connected
        self.lastError = lastError; self.actions = actions; self.channelId = channelId
        self.origins = origins; self.harness = harness
    }

    enum CodingKeys: String, CodingKey {
        case id, label, kind, mark, conversations, episodes, entities, items, lastActivityAt
        case connected, lastError, actions, channelId, origins, harness
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? id
        kind = SourceKind(rawValue: (try c.decodeIfPresent(String.self, forKey: .kind)) ?? "") ?? .unknown
        mark = try c.decodeIfPresent(String.self, forKey: .mark) ?? id
        conversations = try c.decodeIfPresent(Int.self, forKey: .conversations) ?? 0
        episodes = try c.decodeIfPresent(Int.self, forKey: .episodes) ?? 0
        entities = try c.decodeIfPresent(Int.self, forKey: .entities) ?? 0
        items = try c.decodeIfPresent(Int.self, forKey: .items) ?? 0
        lastActivityAt = try c.decodeIfPresent(String.self, forKey: .lastActivityAt)
        connected = try c.decodeIfPresent(Bool.self, forKey: .connected) ?? false
        lastError = try c.decodeIfPresent(String.self, forKey: .lastError)
        actions = try c.decodeIfPresent([String].self, forKey: .actions) ?? []
        channelId = try c.decodeIfPresent(String.self, forKey: .channelId)
        origins = try c.decodeIfPresent([String].self, forKey: .origins) ?? []
        harness = try c.decodeIfPresent(String.self, forKey: .harness)
    }

    /// `lastActivityAt` parsed for sorting — the same three shapes
    /// `SourceChannel.lastSyncDate` accepts (fractional-seconds ISO8601,
    /// plain ISO8601, bare `yyyy-MM-dd` anchored to 00:00 UTC).
    var lastActivityDate: Date? {
        guard let lastActivityAt, !lastActivityAt.isEmpty else { return nil }
        let withFraction = ISO8601DateFormatter()
        withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = withFraction.date(from: lastActivityAt) { return d }
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        if let d = plain.date(from: lastActivityAt) { return d }
        let dayOnly = DateFormatter()
        dayOnly.dateFormat = "yyyy-MM-dd"
        dayOnly.timeZone = TimeZone(identifier: "UTC")
        return dayOnly.date(from: lastActivityAt)
    }

    /// The grid's order, pure and unit-tested: kind (the backend's
    /// `KIND_ORDER`), newest activity first, id for stability. Re-applied on
    /// the client because a cached snapshot from an older backend may not be
    /// sorted.
    static func gridOrder(_ rows: [SourceOverview]) -> [SourceOverview] {
        rows.sorted { a, b in
            let ka = SourceKind.order.firstIndex(of: a.kind) ?? .max
            let kb = SourceKind.order.firstIndex(of: b.kind) ?? .max
            if ka != kb { return ka < kb }
            switch (a.lastActivityDate, b.lastActivityDate) {
            case let (l?, r?) where l != r: return l > r
            case (_?, nil): return true
            case (nil, _?): return false
            default: return a.id < b.id
            }
        }
    }

    /// What a card counts, by kind: a harness counts conversations, a browser
    /// or social source counts items, a feed counts captures — or, when its
    /// episodes carry no origin yet (RSS, R1), the subscriptions the channel
    /// reports (`items` IS the subscription count for `rss`/`calendar`, see
    /// `channel_registry._subscription_channel`) — everything else counts
    /// captures; every kind shows the entities it credited. "Nothing yet" when
    /// all are zero — a row of zeroes reads as a broken card.
    var countLines: [String] {
        var lines: [String] = []
        switch kind {
        case .harness where conversations > 0:
            lines.append(Self.plural(conversations, "conversation"))
        case .browser, .social:
            if items > 0 { lines.append(Self.plural(items, "item")) }
        case .feed:
            if episodes > 0 { lines.append(Self.plural(episodes, "capture")) }
            else if items > 0 { lines.append(Self.plural(items, "subscription")) }
        default:
            if episodes > 0 { lines.append(Self.plural(episodes, "capture")) }
        }
        if entities > 0 { lines.append(Self.plural(entities, "entity", "entities")) }
        return lines.isEmpty ? ["Nothing yet"] : lines
    }

    private static func plural(_ n: Int, _ one: String, _ many: String? = nil) -> String {
        "\(UsageFormat.count(n)) \(n == 1 ? one : (many ?? one + "s"))"
    }
}

/// `GET /sources/overview`. A missing or malformed `sources` key decodes as an
/// empty grid rather than a failed refresh, so a half-upgraded backend never
/// leaves the page stuck on its last cached snapshot.
struct SourceOverviewResponse: Codable {
    let sources: [SourceOverview]
    init(from decoder: Decoder) throws {
        let c = try? decoder.container(keyedBy: CodingKeys.self)
        sources = (try? c?.decodeIfPresent([SourceOverview].self, forKey: .sources)) ?? []
    }
    enum CodingKeys: String, CodingKey { case sources }
}

/// Title filter for a harness's conversation list — the owner's words:
/// "search is secondary; the view of the conversations that exist is the
/// point", so this is a substring match over `displayTitle`, nothing more.
enum ConversationFilter {
    static func apply(_ rows: [ConversationSummary], query: String) -> [ConversationSummary] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !q.isEmpty else { return rows }
        return rows.filter { $0.displayTitle.lowercased().contains(q) }
    }
}

/// Folder / board / device counts for a channel source's items (G124): the
/// media page's `folder:` is a bookmark folder path, a Pinterest board, a
/// TikTok section or an iCloud device name depending on the importer.
enum SourceItemsGrouping {
    static let noFolder = "No folder"
    static func folders(_ items: [MediaFeedItem]) -> [(folder: String, count: Int)] {
        var counts: [String: Int] = [:]
        for item in items {
            let key = (item.folder?.trimmingCharacters(in: .whitespaces)).flatMap { $0.isEmpty ? nil : $0 } ?? noFolder
            counts[key, default: 0] += 1
        }
        return counts.map { (folder: $0.key, count: $0.value) }
            .sorted { $0.count != $1.count ? $0.count > $1.count : $0.folder < $1.folder }
    }
}
