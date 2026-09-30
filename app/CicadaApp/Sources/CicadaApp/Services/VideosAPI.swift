import Foundation

/// G162 — the video reads and the queue's writes. Not a Store domain (the provenance and Projects reads' precedent):
/// fetched on demand into `VideoStateCache`, revalidated with the ETag the server sends, no `VersionVector` mapping.
/// On a protocol so the cache's tests fake it. Nothing here touches a video, a caption or a stream — the queue is a
/// list of the person's own requests (Track V's rail).
protocol VideosAPI: Sendable {
    func fetchVideoState(etag: String?) async throws -> Conditional<VideosStateResponse>
    func fetchVideoSummary(etag: String?) async throws -> Conditional<VideoSummary>
    func putVideoQueue(key: String, want: VideoWant) async throws -> VideoStateItem
    func deleteVideoQueue(key: String) async throws
    func retryVideo(key: String) async throws -> VideoStateItem
    func handoffVideos(items: [(key: String, want: VideoWant)], method: VideoMethod) async throws -> VideoHandoffResponse
    /// The prompt for `count` waiting videos (the preview — writes nothing), or the active batch's when both are nil.
    func fetchVideoPrompt(count: Int?, method: VideoMethod?) async throws -> VideoPromptResponse
}

extension APIClient: VideosAPI {
    /// `/videos/queue/<key>/<tail…>`, every component encoded the way `projectPath` encodes one — a key never
    /// reshapes the URL.
    nonisolated static func videoQueuePath(_ key: String, _ tail: String...) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        return "/videos/queue/" + ([key] + tail).map { $0.addingPercentEncoding(withAllowedCharacters: allowed) ?? $0 }
            .joined(separator: "/")
    }

    func fetchVideoState(etag: String?) async throws -> Conditional<VideosStateResponse> {
        try await getConditional("/videos/state", etag: etag)
    }

    func fetchVideoSummary(etag: String?) async throws -> Conditional<VideoSummary> {
        try await getConditional("/videos/summary", etag: etag)
    }

    func putVideoQueue(key: String, want: VideoWant) async throws -> VideoStateItem {
        try await putVideo(Self.videoQueuePath(key), body: ["want": want.rawValue])
    }

    func deleteVideoQueue(key: String) async throws {
        try await deleteVideo(Self.videoQueuePath(key))
    }

    func retryVideo(key: String) async throws -> VideoStateItem {
        try await postVideo(Self.videoQueuePath(key, "retry"), body: [:])
    }

    func handoffVideos(items: [(key: String, want: VideoWant)], method: VideoMethod) async throws -> VideoHandoffResponse {
        let rows = items.map { ["key": $0.key, "want": $0.want.rawValue] }
        return try await postVideo("/videos/run/handoff", body: ["items": rows, "method": method.rawValue])
    }

    func fetchVideoPrompt(count: Int?, method: VideoMethod?) async throws -> VideoPromptResponse {
        var query: [String] = []
        if let count { query.append("count=\(count)") }
        if let method { query.append("method=\(method.rawValue)") }
        let suffix = query.isEmpty ? "" : "?" + query.joined(separator: "&")
        let response: Conditional<VideoPromptResponse> = try await getConditional("/videos/run/prompt" + suffix, etag: nil)
        guard let value = response.value else { throw APIError.decodingError("no prompt") }
        return value
    }
}
