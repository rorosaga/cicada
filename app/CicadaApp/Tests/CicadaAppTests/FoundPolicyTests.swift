import XCTest
@testable import CicadaApp

/// Track I T6 (design §4.1.4, D-2) — the visible checklist is the consent:
/// pre-ticked only when it is the person's own intentional act, needs no new
/// permission and opens no other app.
final class FoundPolicyTests: XCTestCase {
    private let en = Locale(identifier: "en_US")
    private func item(_ id: FoundItemID, _ group: FoundGroup, title: String = "X", present: Bool = true,
                      content: FoundItem.Content = .ownIntentionalAct, readiness: FoundItem.Readiness = .ready,
                      opens: Bool = false, count: Int? = nil, noun: String? = nil) -> FoundItem {
        FoundItem(id: id, group: group, title: title, isPresent: present, content: content, readiness: readiness,
                  opensAnotherApp: opens, count: count, countNoun: noun)
    }

    func testOnlyAReadyOwnActThatOpensNothingIsPreTicked() {
        XCTAssertTrue(FoundPolicy.defaultOn(item(.agent("claude-code"), .agents)))
        XCTAssertFalse(FoundPolicy.defaultOn(item(.agent("cursor"), .agents, opens: true)))
        XCTAssertFalse(FoundPolicy.defaultOn(item(.app("wispr"), .notesAndVoice, content: .includesOthers)))
        XCTAssertFalse(FoundPolicy.defaultOn(item(.browser("safari-bookmarks"), .browsers, readiness: .needsPermission)))
        XCTAssertFalse(FoundPolicy.defaultOn(item(.agent("codex"), .agents, readiness: .alreadyOn)))
        XCTAssertFalse(FoundPolicy.defaultOn(item(.agent("codex"), .agents, present: false)))
    }

    func testOrderIsGroupThenTickedThenTitleAndAbsentRowsVanish() {
        let ordered = FoundPolicy.order([
            item(.browser("chrome-bookmarks"), .browsers, title: "Chrome"),
            item(.agent("cursor"), .agents, title: "Cursor", opens: true),
            item(.agent("codex"), .agents, title: "Codex"),
            item(.agent("claude-code"), .agents, title: "Claude Code"),
            item(.agent("gone"), .agents, title: "Gone", present: false),
        ])
        XCTAssertEqual(ordered.map(\.title), ["Claude Code", "Codex", "Cursor", "Chrome"])
    }

    func testTheStartSummaryIsWhatStartDoes() {
        XCTAssertEqual(FoundPolicy.startSummary([], locale: en), Copy.foundStartNothing)
        XCTAssertEqual(FoundPolicy.startSummary([item(.agent("a"), .agents), item(.agent("b"), .agents)], locale: en),
                       "Connects 2 apps.")
        XCTAssertEqual(FoundPolicy.startSummary([item(.agent("a"), .agents),
                                                 item(.browser("chrome-bookmarks"), .browsers, count: 2104, noun: "bookmark")],
                                                locale: en),
                       "Connects 1 app and brings in 2,104 bookmarks.")
        XCTAssertEqual(FoundPolicy.startSummary([item(.browser("safari-bookmarks"), .browsers)], locale: en),
                       "Brings in your bookmarks.")
        XCTAssertEqual(FoundPolicy.startSummary([item(.dropped("export.zip"), .chatHistory, count: 412, noun: "conversation"),
                                                 item(.browser("chrome-bookmarks"), .browsers, count: 1, noun: "bookmark")],
                                                locale: en),
                       "Brings in 1 bookmark and 412 conversations.")
    }
}
