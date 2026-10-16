import Foundation

/// G166 exploring — the run's reads and the person's writes (`api/routers/explore.py`). Not a Store domain (the video
/// queue's precedent): fetched on demand into `ExploreCache`, revalidated with the server's ETag, no `VersionVector`
/// mapping. On a protocol so the cache's tests fake it. Nothing here opens a browser or fetches a site: the person's own
/// agent explores, and Cicada only keeps what it recorded.
protocol ExploreAPI: Sendable {
    func fetchExploreState(etag: String?) async throws -> Conditional<ExploreState>
    func fetchExploreCandidates(etag: String?) async throws -> Conditional<ExploreCandidates>
    func startExplore(scope: ExploreScope, origins: [String]) async throws -> ExploreStartResponse
    func stopExplore() async throws -> ExploreStopResponse
    func fetchExplorePrompt() async throws -> ExplorePromptResponse
    /// Looks v2 — "Save its look" on one saved link (`POST /explore/look`).
    func saveLook(mediaEntityId: String, url: String) async throws -> ExploreLookResponse
}

extension APIClient: ExploreAPI {
    func fetchExploreState(etag: String?) async throws -> Conditional<ExploreState> {
        try await getConditional("/explore/state", etag: etag)
    }

    func fetchExploreCandidates(etag: String?) async throws -> Conditional<ExploreCandidates> {
        try await getConditional("/explore/candidates", etag: etag)
    }

    func startExplore(scope: ExploreScope, origins: [String]) async throws -> ExploreStartResponse {
        try await postVideo("/explore/batches", body: ["scope": scope.rawValue, "origins": origins])
    }

    func stopExplore() async throws -> ExploreStopResponse {
        try await postVideo("/explore/stop", body: [:])
    }

    func saveLook(mediaEntityId: String, url: String) async throws -> ExploreLookResponse {
        try await postVideo("/explore/look", body: ["entityId": mediaEntityId, "url": url])
    }

    func fetchExplorePrompt() async throws -> ExplorePromptResponse {
        let response: Conditional<ExplorePromptResponse> = try await getConditional("/explore/prompt", etag: nil)
        guard let value = response.value else { throw APIError.decodingError("no prompt") }
        return value
    }
}
