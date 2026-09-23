import XCTest
@testable import CicadaApp

/// Track Z §7.1 — `SourceOverview.owning(origin:in:)` is the inverse of
/// `ownedQueue(from:)`: a spine's "Open in Sources ›" lands on the source
/// whose queue strip shows the same episodes, or the link is hidden.
final class SourceOwningTests: XCTestCase {

    private func item(_ id: String, _ origin: String) throws -> EpisodeQueueItem {
        try JSONDecoder().decode(EpisodeQueueItem.self, from: Data(
            #"{"id":"\#(id)","timestamp":"2026-09-01T00:00:00Z","source":"x","origin":"\#(origin)","preview":"","processed":false}"#.utf8))
    }

    private let rows = [
        SourceOverview(id: "harness:claude-code", label: "Claude Code", kind: .harness, harness: "claude-code"),
        SourceOverview(id: "harness:cursor", label: "Cursor", kind: .harness, harness: "cursor"),
        SourceOverview(id: "safari-bookmarks", label: "Safari bookmarks", kind: .browser, origins: ["safari-bookmark"]),
        SourceOverview(id: "files", label: "Files & links", kind: .import, origins: ["saved-link"]),
    ]

    func test_owning_roundTripsEveryQueuedEpisodeToTheRowThatOwnsIt() throws {
        let all = try [item("1", "claude-code"), item("2", "mcp"), item("3", "cursor"),
                       item("4", "safari-bookmark"), item("5", "saved-link"), item("6", "unknown")]
        var checked = 0
        for row in rows {
            for episode in row.ownedQueue(from: all) {
                XCTAssertEqual(SourceOverview.owning(origin: episode.origin, in: rows)?.id, row.id, episode.id)
                checked += 1
            }
        }
        XCTAssertEqual(checked, 5, "every stamped episode has an owner; `unknown` has none")
    }

    func test_owning_givesTheLegacyMcpOriginToClaudeCodeOnly() {
        XCTAssertEqual(SourceOverview.owning(origin: "mcp", in: rows)?.id, "harness:claude-code")
        XCTAssertNil(SourceOverview.owning(origin: "mcp", in: Array(rows.dropFirst())), "cursor never adopts mcp")
    }

    func test_owning_isNilWhenNoRowOwnsTheOrigin_neverAGuess() {
        XCTAssertNil(SourceOverview.owning(origin: "unknown", in: rows))
        XCTAssertNil(SourceOverview.owning(origin: "telegram", in: rows))
    }
}
