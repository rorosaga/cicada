import Foundation
import XCTest
@testable import CicadaApp

/// G162 — the video wires the app is tested against: the demo bank's real `/videos/state` and `/videos/summary`
/// (`videos-state-demo.json`) and the approved boards' 23-video fixture at its two moments
/// (`videos-state-boards.json`), both pinned by `api/tests/test_videos_app_fixture.py`, plus the two shared fixtures
/// the Python side reads too (`video_state.json`, `video_kind.json`). Synthetic only.
enum VideoFixtures {
    struct Demo: Decodable {
        let state: VideosStateResponse
        let summary: VideoSummary
    }

    struct Moment: Decodable {
        let moment: String
        let state: VideosStateResponse
        let summary: VideoSummary
        let feed: [MediaFeedItem]
    }

    struct Boards: Decodable { let moments: [String: Moment] }

    /// …/Tests/CicadaAppTests/VideoFixtures.swift → …/Tests/fixtures/<name>.
    private static let appFixtures = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .appendingPathComponent("fixtures")

    /// The repo's `api/tests/fixtures/<name>`.
    static let apiFixtures = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()   // CicadaAppTests
        .deletingLastPathComponent()   // Tests
        .deletingLastPathComponent()   // CicadaApp
        .deletingLastPathComponent()   // app
        .deletingLastPathComponent()   // repo root
        .appendingPathComponent("api/tests/fixtures")

    static func demo() throws -> Demo {
        try JSONDecoder().decode(Demo.self, from: Data(contentsOf: appFixtures.appendingPathComponent("videos-state-demo.json")))
    }

    static func moment(_ name: String) throws -> Moment {
        let boards = try JSONDecoder().decode(Boards.self,
                                              from: Data(contentsOf: appFixtures.appendingPathComponent("videos-state-boards.json")))
        return try XCTUnwrap(boards.moments[name])
    }

    static func rows(_ moment: Moment) -> [VideoRow] {
        VideoRunModel.rows(items: moment.feed, states: moment.state.items)
    }

    static func item(_ json: String) -> MediaFeedItem {
        try! JSONDecoder().decode(MediaFeedItem.self, from: Data(json.utf8))
    }

    static func feedItem(id: String = "media-a", url: String = "https://www.youtube.com/watch?v=abcdefghijk",
                         channel: String? = "bob-example", durationS: Int? = nil) -> MediaFeedItem {
        var object: [String: Any] = ["mediaEntityId": id, "url": url, "title": "A video", "mediaType": "youtube",
                                     "site": "youtube.com", "savedAt": "2026-09-13T10:00:00Z", "tags": []]
        if let channel { object["channel"] = channel }
        if let durationS { object["durationS"] = durationS }
        let data = try! JSONSerialization.data(withJSONObject: object)
        return try! JSONDecoder().decode(MediaFeedItem.self, from: data)
    }
}

/// A `VideosAPI` that answers from queues and records what each call asked for.
@MainActor
final class FakeVideosAPI: VideosAPI {
    var stateReplies: [Result<Conditional<VideosStateResponse>, any Error>] = []
    var summaryReplies: [Result<Conditional<VideoSummary>, any Error>] = []
    var putError: (any Error)?
    private(set) var stateETags: [String?] = []
    private(set) var puts: [(String, VideoWant)] = []
    private(set) var deletes: [String] = []
    private(set) var handoffs: [[(key: String, want: VideoWant)]] = []
    private(set) var promptAsks: [(Int?, VideoMethod?)] = []

    func fetchVideoState(etag: String?) async throws -> Conditional<VideosStateResponse> {
        stateETags.append(etag)
        guard !stateReplies.isEmpty else { throw APIError.serverUnreachable }
        return try stateReplies.removeFirst().get()
    }

    func fetchVideoSummary(etag: String?) async throws -> Conditional<VideoSummary> {
        guard !summaryReplies.isEmpty else { throw APIError.serverUnreachable }
        return try summaryReplies.removeFirst().get()
    }

    func putVideoQueue(key: String, want: VideoWant) async throws -> VideoStateItem {
        puts.append((key, want))
        if let putError { throw putError }
        return VideoStateItem(key: key, mediaEntityId: "", url: "", queueState: .queued)
    }

    func deleteVideoQueue(key: String) async throws { deletes.append(key) }

    func retryVideo(key: String) async throws -> VideoStateItem {
        VideoStateItem(key: key, mediaEntityId: "", url: "", queueState: .queued)
    }

    func handoffVideos(items: [(key: String, want: VideoWant)], method: VideoMethod) async throws -> VideoHandoffResponse {
        handoffs.append(items)
        return VideoHandoffResponse(batch: VideoBatch(id: "b_1", total: items.count, keys: items.map(\.key)),
                                    prompt: "Cicada has \(items.count) videos waiting for you to read or watch.")
    }

    func fetchVideoPrompt(count: Int?, method: VideoMethod?) async throws -> VideoPromptResponse {
        promptAsks.append((count, method))
        return VideoPromptResponse(prompt: "preview \(count ?? -1)")
    }

    static func fresh(_ value: VideosStateResponse, _ etag: String) -> Result<Conditional<VideosStateResponse>, any Error> {
        .success(Conditional(value: value, etag: etag, notModified: false))
    }

    static func notModified(_ etag: String) -> Result<Conditional<VideosStateResponse>, any Error> {
        .success(Conditional(value: nil, etag: etag, notModified: true))
    }
}
