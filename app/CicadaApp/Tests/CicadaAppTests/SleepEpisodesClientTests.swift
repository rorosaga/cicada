import XCTest
@testable import CicadaApp

/// `GET /sleep/episodes?processed=false` and its ETag, end to end through `APIClient` over a fake transport.
final class SleepEpisodesClientTests: XCTestCase {
    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    private func client() -> APIClient {
        APIClient(session: MockURLProtocol.makeSession(), connection: ServerConnection(mode: .thisMac, source: .none),
                  runtime: .developer(codeRoot: URL(fileURLWithPath: "/nonexistent")))
    }

    func testAsksForTheWaitingOnlyAndMapsA304() async throws {
        var seen: [URLRequest] = []
        MockURLProtocol.handler = { request in
            seen.append(request)
            let url = request.url!
            if request.value(forHTTPHeaderField: "If-None-Match") == "\"e1\"" {
                return (HTTPURLResponse(url: url, statusCode: 304, httpVersion: nil, headerFields: ["ETag": "\"e1\""])!,
                        Data())
            }
            let body = """
            [{"id":"ep_w","timestamp":"2026-10-19T08:00:00Z","source":"mcp","origin":"claude-code","title":null,
              "preview":"hi","chars":2,"processed":false,"processedBy":null,"copyKind":"episode","copyValue":"ep_w",
              "changedAt":"2026-10-19T08:00:00Z"}]
            """
            return (HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil,
                                    headerFields: ["ETag": "\"e1\"", "X-Total-Count": "1"])!, Data(body.utf8))
        }
        let api = client()
        let first = try await api.fetchEpisodeQueue(etag: nil)
        XCTAssertEqual(first.value?.map(\.id), ["ep_w"])
        XCTAssertEqual(first.etag, "\"e1\"")
        XCTAssertFalse(first.notModified)
        let second = try await api.fetchEpisodeQueue(etag: first.etag)
        XCTAssertTrue(second.notModified)
        XCTAssertNil(second.value)

        XCTAssertEqual(seen.count, 2)
        let components = URLComponents(url: seen[0].url!, resolvingAgainstBaseURL: false)!
        XCTAssertEqual(components.path, "/sleep/episodes")
        XCTAssertEqual(components.queryItems, [URLQueryItem(name: "processed", value: "false")])
        XCTAssertNil(seen[0].value(forHTTPHeaderField: "If-None-Match"))
        XCTAssertEqual(seen[1].value(forHTTPHeaderField: "If-None-Match"), "\"e1\"")
    }
}
