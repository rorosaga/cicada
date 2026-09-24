import Foundation

/// G141 PJ-5 — the two Projects reads. Not a Store domain (R-PJ7, R-PP3): fetched on demand into `ProjectsCache`,
/// revalidated with the ETag the server sends, and no `VersionVector` mapping — the provenance reads' precedent
/// (`ProvenanceAPI`). On a protocol so the cache's tests can fake it.
protocol ProjectsAPI: Sendable {
    func fetchProjects(etag: String?) async throws -> Conditional<ProjectsResponse>
    func fetchProjectTimeline(id: String, etag: String?) async throws -> Conditional<ProjectTimeline>
}

extension APIClient: ProjectsAPI {
    func fetchProjects(etag: String?) async throws -> Conditional<ProjectsResponse> {
        try await getConditional("/projects", etag: etag)
    }

    /// A project id lands in a PATH, so it is encoded the way every id-in-a-path is (`provenancePath`): a `/`, `?` or
    /// `#` never reshapes the URL.
    func fetchProjectTimeline(id: String, etag: String?) async throws -> Conditional<ProjectTimeline> {
        try await getConditional(Self.provenancePath("/projects", id, "/timeline"), etag: etag)
    }
}
