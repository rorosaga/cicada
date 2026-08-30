import Foundation

struct VersionVector: Codable, Equatable {
    let version: String
    let components: [String: String]

    static let mapping: [String: Set<SyncDomain>] = [
        "entities": [.graph, .contributors, .origins], "edges": [.graph, .contributors, .origins], "hubs": [.graph, .contributors, .origins],
        "inbox": [.inbox, .graph, .status], "episodes": [.status, .origins, .sources],
        // The `sources` component folds in `feeds.yaml` and `calendars.yaml`
        // (see `sync_service.components`), so all three domains ride it.
        "sources": [.sources, .feeds, .calendars], "git_head": [.contributors], "sleep": [.status],
    ]

    func changedDomains(since old: VersionVector?) -> Set<SyncDomain> {
        guard let old else { return Set(SyncDomain.allCases) }
        if old.version == version { return [] }
        if components["bank"] != old.components["bank"] { return Set(SyncDomain.allCases) }
        var out = Set<SyncDomain>()
        for (key, domains) in Self.mapping where components[key] != old.components[key] { out.formUnion(domains) }
        return out
    }
}
