import Foundation

struct Snapshot<T: Codable> {
    var value: T?
    var etag: String?
    var loadedAt: Date?
    var isRefreshing = false
    var isEmpty: Bool { value == nil }
}

enum SyncDomain: String, CaseIterable, Codable {
    case graph, inbox, banks, sources, feeds, calendars, contributors, origins, connections, status
}
