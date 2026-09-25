import Foundation

/// G150 (R-B18) — the Backlog section's two reads. Not a Store domain: fetched on demand into `BacklogCache`,
/// revalidated with the ETag the server sends, no `VersionVector` mapping — the Projects reads' precedent
/// (`ProjectsAPI`). On a protocol so the cache's tests fake it.
protocol BacklogAPI: Sendable {
    func fetchBacklog(project: String, etag: String?) async throws -> Conditional<BacklogList>
    func fetchBacklogItem(project: String, item: String, etag: String?) async throws -> Conditional<BacklogItem>
}

extension APIClient: BacklogAPI {
    /// `/backlog/<project>/<item>/<tail…>`, every component encoded the way `projectPath` encodes one — an id never
    /// reshapes the URL.
    nonisolated static func backlogPath(_ project: String, _ item: String, _ tail: String...) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        return "/backlog/" + ([project, item] + tail)
            .map { $0.addingPercentEncoding(withAllowedCharacters: allowed) ?? $0 }
            .joined(separator: "/")
    }

    func fetchBacklog(project: String, etag: String?) async throws -> Conditional<BacklogList> {
        try await getConditional(Self.projectPath(project, "backlog"), etag: etag)
    }

    func fetchBacklogItem(project: String, item: String, etag: String?) async throws -> Conditional<BacklogItem> {
        try await getConditional(Self.backlogPath(project, item), etag: etag)
    }
}
