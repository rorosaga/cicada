import XCTest
@testable import CicadaApp

/// G126 — Settings → Integrations. `IntegrationCategory.of(channelId:)` is
/// the pure map every channel id in `api/services/channel_registry.py::
/// CHANNEL_IDS` must land under; `IntegrationHarnessRows` pulls the
/// informational "captured by the Stop hook / MCP" rows out of the same
/// `Store.sourcesOverview` domain the Sources grid already reads;
/// `IntegrationRowState.line` (R8) is the one-sentence state formatter that
/// replaces `SourceChannel.detail`'s per-kind shapes with one visual
/// language for this page.
final class IntegrationsViewTests: XCTestCase {

    private func iso(_ date: Date) -> String {
        let fmt = ISO8601DateFormatter()
        fmt.formatOptions = [.withInternetDateTime]
        return fmt.string(from: date)
    }

    /// Mirrors `api/services/channel_registry.py::CHANNEL_IDS` verbatim
    /// (2312887) — a 14th id added later needs this list AND the switch
    /// updated together.
    func testEveryChannelIdHasACategory() {
        let ids: [(String, IntegrationCategory)] = [
            ("chat-export:claude", .chatAndAgents), ("chat-export:chatgpt", .chatAndAgents),
            ("chrome-bookmarks", .browsers), ("safari-bookmarks", .browsers), ("safari-tabs", .browsers),
            ("notes", .filesAndImports),
            ("rss", .feedsAndCalendars), ("calendar", .feedsAndCalendars),
            ("pinterest", .socialAndSaved), ("reddit", .socialAndSaved), ("x", .socialAndSaved),
            ("telegram", .messaging), ("files", .filesAndImports),
        ]
        for (id, expected) in ids {
            XCTAssertEqual(IntegrationCategory.of(channelId: id), expected, id)
        }
    }

    func testHarnessRowsComeFromSourcesOverview() {
        let overview = [SourceOverview(id: "claude-code", label: "Claude Code", kind: .harness),
                         SourceOverview(id: "chrome-bookmarks", label: "Chrome", kind: .browser)]
        XCTAssertEqual(IntegrationHarnessRows.rows(from: overview).map(\.id), ["claude-code"])
    }

    func testRowStateLine() {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let connected = SourceChannel(id: "chrome-bookmarks", label: "Chrome bookmarks", connected: true,
                                       count: 12, lastSync: iso(now.addingTimeInterval(-3600)))
        XCTAssertTrue(IntegrationRowState.line(connected, now: now).contains("12 items"))
        let disconnected = SourceChannel(id: "x", label: "X", connected: false)
        XCTAssertEqual(IntegrationRowState.line(disconnected, now: now), "Not connected")
        let errored = SourceChannel(id: "rss", label: "RSS", connected: true, lastError: "401 Unauthorized")
        XCTAssertTrue(IntegrationRowState.line(errored, now: now).contains("401 Unauthorized"))
    }
}
