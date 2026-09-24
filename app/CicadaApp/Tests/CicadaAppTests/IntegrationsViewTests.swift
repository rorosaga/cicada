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
            ("chat-export:gemini", .chatAndAgents),
            ("chrome-bookmarks", .browsers), ("safari-bookmarks", .browsers), ("safari-tabs", .browsers),
            // Round 4 (C9): the Chromium family.
            ("brave-bookmarks", .browsers), ("vivaldi-bookmarks", .browsers), ("comet-bookmarks", .browsers),
            ("dia-bookmarks", .browsers),
            // Round 4 (G160): Chrome's open tab groups sit under Chrome.
            ("chrome-tab-groups", .browsers),
            // R-LS25: Apple Notes sits beside the watched folders now.
            ("notes", .notesAndFiles),
            ("rss", .feedsAndCalendars), ("calendar", .feedsAndCalendars),
            // Round-4 D2 (C6, R-FA13): the Calendar app read on this Mac, rendered by `CalendarRow`.
            ("calendar-local", .feedsAndCalendars),
            // Round 4 (G154): the Mac's address book, rendered by `ContactsRow` beside the Calendar app.
            ("contacts-local", .feedsAndCalendars),
            ("pinterest", .socialAndSaved), ("reddit", .socialAndSaved), ("x", .socialAndSaved),
            ("telegram", .messaging), ("files", .filesAndImports),
        ]
        for (id, expected) in ids {
            XCTAssertEqual(IntegrationCategory.of(channelId: id), expected, id)
        }
    }

    /// Test gap 1 — the OLD fixture defaulted `channelId` to nil, which is
    /// the one shape that hides the bug. `api/services/source_overview.py:50`
    /// gives `chat-export:claude` BOTH `kind = "harness"` AND a channel id, so
    /// the page rendered "Claude export" as an informational harness row and
    /// "Claude chat export" as a real channel row — and the harness copy said
    /// "Captured automatically — no setup needed", which is false for a
    /// one-shot file drop.
    func testHarnessRowsDropAnythingThatIsAlsoAChannel() {
        let overview = [
            SourceOverview(id: "claude-code", label: "Claude Code", kind: .harness),
            SourceOverview(id: "chat-export:claude", label: "Claude export", kind: .harness,
                           channelId: "chat-export:claude"),
            SourceOverview(id: "chrome-bookmarks", label: "Chrome", kind: .browser),
        ]
        XCTAssertEqual(IntegrationHarnessRows.rows(from: overview).map(\.id), ["claude-code"])
    }

    /// recent-work #12 — Integrations is also onboarding STEP 3, so the worst
    /// case is a brand-new install on the step whose whole purpose is "connect
    /// one channel", staring at a PageHeader over blank space while the
    /// backend is still starting. Same three-state shape
    /// `ConnectedChannelsStrip.loadState` already uses.
    func testLoadStateDistinguishesLoadingFromFailedFromEmpty() {
        XCTAssertEqual(IntegrationsView.loadState(channels: nil, overview: nil, isLoading: true, error: nil), .loading)
        XCTAssertEqual(IntegrationsView.loadState(channels: nil, overview: nil, isLoading: false, error: nil), .loading,
                       "no snapshot, not refreshing, no error = the fetch has not started")
        XCTAssertEqual(IntegrationsView.loadState(channels: nil, overview: nil, isLoading: false, error: "Connection refused"),
                       .failed("Connection refused"))
        XCTAssertEqual(IntegrationsView.loadState(channels: [], overview: [], isLoading: false, error: nil), .empty)
        // A latched error never hides rows the app already has.
        XCTAssertEqual(
            IntegrationsView.loadState(channels: [SourceChannel(id: "rss", label: "RSS", connected: true)],
                                       overview: [], isLoading: false, error: "Connection refused"),
            .loaded
        )
        // Final review F2 — the shape that was rendering one error row over a
        // roster the Store already had: `GET /sources/channels` landed,
        // `GET /sources/overview` did not. `overview` feeds only the three
        // informational harness rows, so it must never gate the page.
        XCTAssertEqual(
            IntegrationsView.loadState(channels: [SourceChannel(id: "rss", label: "RSS", connected: true)],
                                       overview: nil, isLoading: false, error: "Connection refused"),
            .loaded,
            "a failed overview must not hide channel rows the Store is holding"
        )
        // …and the mirror image, since either domain alone is evidence.
        XCTAssertEqual(
            IntegrationsView.loadState(channels: nil, overview: [SourceOverview(id: "claude-code", label: "Claude Code", kind: .harness)],
                                       isLoading: false, error: "Connection refused"),
            .loaded
        )
        // One domain confirmed-empty while the other has NOT answered is not
        // "confirmed nothing here" — the failure still shows.
        XCTAssertEqual(
            IntegrationsView.loadState(channels: [], overview: nil, isLoading: false, error: "Connection refused"),
            .failed("Connection refused"),
            "half an answer never resolves to .empty"
        )
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

    /// DR-52, R-HS18 — a harness row wears its app's real mark; "Other agents" has no vendor and
    /// wears a neutral glyph, never a "?" and never a chat bubble in a tinted circle.
    func testHarnessRowsWearTheirRealMarks() {
        func row(_ harness: String) -> SourceOverview {
            SourceOverview(id: "harness:\(harness)", label: harness, kind: .harness, mark: harness, harness: harness)
        }
        XCTAssertEqual(IntegrationHarnessRows.markOrigin(for: row("claude-code")), "claude-code")
        XCTAssertEqual(IntegrationHarnessRows.markOrigin(for: row("codex")), "codex")
        XCTAssertEqual(IntegrationHarnessRows.markOrigin(for: row("cursor")), "cursor")
        XCTAssertNil(IntegrationHarnessRows.markOrigin(for: row("unknown")))
        XCTAssertNotEqual(IntegrationHarnessRows.otherAgentsSymbol, "questionmark.circle")
        XCTAssertNotEqual(IntegrationHarnessRows.otherAgentsSymbol, "bubble.left.and.bubble.right")
    }
}
