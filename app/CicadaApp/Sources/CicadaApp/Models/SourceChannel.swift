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
    let actions: [String]

    enum CodingKeys: String, CodingKey {
        case id, label, connected, count, lastSync, detail, actions
    }

    init(id: String, label: String, connected: Bool = false, count: Int = 0,
         lastSync: String? = nil, detail: String? = nil, actions: [String] = []) {
        self.id = id; self.label = label; self.connected = connected
        self.count = count; self.lastSync = lastSync; self.detail = detail
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
