import Foundation

/// Mirror of api/models/schemas.py::SourceChannel (G62). One capture channel
/// and whether it is actually connected — derived server-side from persisted
/// state, so the Capture page is correct on a cold, offline launch.
///
/// Tolerant decoding: every field but `id` is optional so an older backend
/// (or a channel with no state at all) still yields a usable row.
struct SourceChannel: Codable, Identifiable, Hashable {
    let id: String
    let label: String
    let connected: Bool
    let count: Int
    let lastSync: String?
    let detail: String?
    /// G71 — the last poll's failure, when there was one. Present so a tile can
    /// say "needs attention" instead of showing a stale success.
    let lastError: String?
    /// R-S5 — the SINGULAR noun `count` counts ("bookmark", "saved item"), or
    /// nil when this channel's state has nothing to count. The server used to
    /// bake `f"{n:,} bookmarks"` into `detail`; that printed the SERVER's
    /// `en_US` grouping to a reader whose system says "1.035" (critique B1),
    /// so the number and its unit now cross the wire apart and
    /// `ChannelDetailLine.text` composes them in the reader's locale.
    /// Pluralised with `+ "s"` — every noun the registry ships is regular, and
    /// `test_channel_detail_numbers.py` is what keeps that true.
    let countNoun: String?
    /// True only for a connector's "items pulled THIS run", which is not a
    /// channel total — rendered "+N nouns this sync".
    let countIsDelta: Bool
    let actions: [String]

    enum CodingKeys: String, CodingKey {
        case id, label, connected, count, lastSync, detail, lastError
        case countNoun, countIsDelta, actions
    }

    init(id: String, label: String, connected: Bool = false, count: Int = 0,
         lastSync: String? = nil, detail: String? = nil, lastError: String? = nil,
         countNoun: String? = nil, countIsDelta: Bool = false,
         actions: [String] = []) {
        self.id = id; self.label = label; self.connected = connected
        self.count = count; self.lastSync = lastSync; self.detail = detail
        self.lastError = lastError
        self.countNoun = countNoun; self.countIsDelta = countIsDelta
        self.actions = actions
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? id
        connected = try c.decodeIfPresent(Bool.self, forKey: .connected) ?? false
        count = try c.decodeIfPresent(Int.self, forKey: .count) ?? 0
        lastSync = try c.decodeIfPresent(String.self, forKey: .lastSync)
        detail = try c.decodeIfPresent(String.self, forKey: .detail)
        lastError = try c.decodeIfPresent(String.self, forKey: .lastError)
        // Optional-with-default: an older backend omits both, and its
        // already-formatted `detail` then renders unchanged.
        countNoun = try c.decodeIfPresent(String.self, forKey: .countNoun)
        countIsDelta = try c.decodeIfPresent(Bool.self, forKey: .countIsDelta) ?? false
        actions = try c.decodeIfPresent([String].self, forKey: .actions) ?? []
    }

    /// `lastSync` parsed for sorting. Accepts both the fractional- and
    /// plain-second ISO8601 forms the backend emits, and a bare `2026-08-29`.
    var lastSyncDate: Date? {
        guard let lastSync, !lastSync.isEmpty else { return nil }
        let withFraction = ISO8601DateFormatter()
        withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = withFraction.date(from: lastSync) { return d }
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        if let d = plain.date(from: lastSync) { return d }
        let dayOnly = DateFormatter()
        dayOnly.dateFormat = "yyyy-MM-dd"
        dayOnly.timeZone = TimeZone(identifier: "UTC")
        return dayOnly.date(from: lastSync)
    }

    /// The Capture page's "Connected" list: connected rows only, most recently
    /// synced first. A channel with no timestamp (Telegram, Files & links)
    /// sorts after the timestamped ones; ties break on label for stability.
    static func sortedConnected(_ channels: [SourceChannel]) -> [SourceChannel] {
        channels.filter(\.connected).sorted { a, b in
            switch (a.lastSyncDate, b.lastSyncDate) {
            case let (l?, r?): return l == r ? a.label < b.label : l > r
            case (_?, nil): return true
            case (nil, _?): return false
            case (nil, nil): return a.label < b.label
            }
        }
    }
}

struct SourceChannelsResponse: Codable {
    let channels: [SourceChannel]
}
