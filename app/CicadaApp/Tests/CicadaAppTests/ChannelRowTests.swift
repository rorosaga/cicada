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
}
