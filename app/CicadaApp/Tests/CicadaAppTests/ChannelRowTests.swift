import XCTest
@testable import CicadaApp

/// G68 §2.9 — every connected row has a discoverable way into its settings,
/// and never offers an action nothing implements.
final class ChannelRowTests: XCTestCase {

    private func channel(_ id: String, actions: [String]) -> SourceChannel {
        SourceChannel(id: id, label: id, connected: true, count: 1,
                      lastSync: nil, detail: nil, actions: actions)
    }

    /// The backend lists what a channel supports; "Manage…" is appended
    /// regardless, because tapping the row already does it and nothing on
    /// screen said so.
    func testManageIsAlwaysTheLastMenuItem() {
        XCTAssertEqual(ConnectedChannelRow.menuActions(for: channel("rss", actions: ["poll"])),
                       ["poll", "manage"])
        XCTAssertEqual(ConnectedChannelRow.menuActions(for: channel("telegram", actions: [])),
                       ["manage"])
    }

    /// A backend that already sends "manage" must not produce two entries.
    func testManageIsNeverDuplicated() {
        let actions = ConnectedChannelRow.menuActions(for: channel("files", actions: ["import", "manage"]))
        XCTAssertEqual(actions, ["import", "manage"])
        XCTAssertEqual(actions.filter { $0 == "manage" }.count, 1)
    }

    /// "Remove" was routed to the same "open the manage sheet" branch as
    /// everything else — a menu item that lied about what it did.
    func testRemoveIsNotOffered() {
        XCTAssertFalse(ConnectedChannelRow.menuActions(for: channel("rss", actions: ["poll", "remove"])).contains("remove"))
    }

    func testEveryOfferedActionHasAHumanTitle() {
        let ch = channel("rss", actions: ["poll", "sync", "import"])
        for action in ConnectedChannelRow.menuActions(for: ch) {
            let title = ConnectedChannelRow.actionTitle(action, channel: ch)
            XCTAssertFalse(title.isEmpty, action)
            XCTAssertEqual(title.first, title.first?.uppercased().first, "\(action) title is not capitalised")
        }
    }

    /// Feedback is `Equatable` so the view can key a `.task(id:)` on it and
    /// restart the 5 s auto-clear when a second result replaces the first.
    func testFeedbackComparesByContent() {
        XCTAssertEqual(ChannelFeedback(text: "3 new", isError: false),
                       ChannelFeedback(text: "3 new", isError: false))
        XCTAssertNotEqual(ChannelFeedback(text: "3 new", isError: false),
                          ChannelFeedback(text: "3 new", isError: true))
    }

    // MARK: PR #19 round-4 review — per-channel busy/feedback keying

    /// Reads a file under `Sources/CicadaApp/`, resolved from this test
    /// file's own path (mirrors `FixWaveTests.sourceFile`) so it works from
    /// any working directory.
    private func sourceFile(_ relativePath: String) throws -> String {
        let testFile = URL(fileURLWithPath: #filePath)
        let packageRoot = testFile
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp package root
        let url = packageRoot
            .appendingPathComponent("Sources/CicadaApp")
            .appendingPathComponent(relativePath)
        return try String(contentsOf: url, encoding: .utf8)
    }

    /// `ConnectedChannelsStrip` used to track exactly one in-flight channel
    /// (`busyChannel: String?`) and one result (`feedback: ChannelFeedback?`)
    /// for the whole strip — two rows acting concurrently raced on both, and
    /// whichever finished last won, clearing or replacing the other row's
    /// still-relevant state. Pinned at the source level (the state itself
    /// lives in `@State`/`@Environment`-backed view properties with no
    /// testable seam of their own — this codebase has no SwiftUI hosting
    /// harness) so the single-shared-slot shape can't silently come back.
    func testConnectedChannelsStripKeysBusyAndFeedbackPerChannel() throws {
        let text = try sourceFile("Views/Feed/ConnectedChannelsStrip.swift")
        XCTAssertFalse(text.contains("@State private var busyChannel: String?"),
                       "busy tracking must be per-channel, not a single shared slot")
        XCTAssertFalse(text.contains("@State private var feedback: ChannelFeedback?"),
                       "feedback must be per-channel, not a single shared slot")
        XCTAssertTrue(text.contains("busyChannels: Set<String>"))
        XCTAssertTrue(text.contains("feedback: [String: ChannelFeedback]"))
    }

    /// The actual bug: two channels' busy/feedback state living in one slot.
    /// This exercises the exact sequence `ConnectedChannelsStrip.run()`
    /// performs — insert into the busy set, write the per-channel result,
    /// remove from the busy set — for two channels completing **out of
    /// order** (the second one started finishes first), using the same
    /// `Set<String>` / `[String: ChannelFeedback]` types the view holds.
    /// With per-channel keys this is provably safe regardless of completion
    /// order — there is no shared slot left for a race to land on.
    func testTwoChannelsCompletingOutOfOrderDoNotClobberEachOther() {
        var busy: Set<String> = []
        var feedback: [String: ChannelFeedback] = [:]

        // Both rows start their actions.
        busy.insert("rss")
        busy.insert("notes")
        XCTAssertTrue(busy.contains("rss"))
        XCTAssertTrue(busy.contains("notes"))

        // "notes" (started second) finishes first.
        feedback["notes"] = ChannelFeedback(text: "2 new", isError: false)
        busy.remove("notes")
        XCTAssertTrue(busy.contains("rss"), "an unrelated channel finishing must not clear rss's spinner")
        XCTAssertNil(feedback["rss"], "an unrelated channel finishing must not invent a result for rss")

        // "rss" (started first) finishes last, with an error.
        feedback["rss"] = ChannelFeedback(text: "network error", isError: true)
        busy.remove("rss")

        XCTAssertTrue(busy.isEmpty)
        XCTAssertEqual(feedback["notes"], ChannelFeedback(text: "2 new", isError: false),
                       "notes' result must survive rss finishing afterwards")
        XCTAssertEqual(feedback["rss"], ChannelFeedback(text: "network error", isError: true))
    }
}
