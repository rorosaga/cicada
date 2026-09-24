import XCTest
@testable import CicadaApp

/// Track I part b (R-IB17) — the Getting started record, per bank, in defaults.
final class GettingStartedStateTests: XCTestCase {
    private var defaults: UserDefaults!
    override func setUp() { defaults = UserDefaults(suiteName: "gs-\(UUID().uuidString)") }

    func testFoundItemIDsRoundTripThroughTheirKey() {
        for id in [FoundItemID.agent("claude-code"), .browser("chrome-bookmarks"), .app("md.obsidian"), .dropped("a:b")] {
            XCTAssertEqual(FoundItemID(key: id.key), id)
        }
        XCTAssertNil(FoundItemID(key: "nonsense"))
        XCTAssertNil(FoundItemID(key: "agent:"))
    }

    func testABankTheWelcomeNeverRanOnHasNoChecklist() {
        XCTAssertNil(GettingStartedState.load(bank: "default", defaults: defaults),
                     "an install onboarded before this track never sees the card")
    }

    func testRecordUnionsKeepsOrderAndNeverPersistsADroppedFile() {
        GettingStartedState.record(bank: "default", enabled: [.agent("claude-code"), .dropped("x")], defaults: defaults)
        GettingStartedState.record(bank: "default", enabled: [.browser("chrome-bookmarks"), .agent("claude-code")], defaults: defaults)
        XCTAssertEqual(GettingStartedState.load(bank: "default", defaults: defaults)?.enabled,
                       [.agent("claude-code"), .browser("chrome-bookmarks")])
        GettingStartedState.settle(.dropped("x"), bank: "default", defaults: defaults)
        XCTAssertEqual(GettingStartedState.load(bank: "default", defaults: defaults)?.settled, [],
                       "a dismissed drop is forgotten by the runner, never written down")
    }

    func testRecordingAgainReShowsAHiddenCard() {
        GettingStartedState.record(bank: "b", enabled: [], defaults: defaults)
        GettingStartedState.setHidden(true, bank: "b", defaults: defaults)
        XCTAssertEqual(GettingStartedState.load(bank: "b", defaults: defaults)?.hidden, true)
        GettingStartedState.record(bank: "b", enabled: [.agent("codex")], defaults: defaults)
        XCTAssertEqual(GettingStartedState.load(bank: "b", defaults: defaults)?.hidden, false)
    }

    func testStateIsPerBank() {
        GettingStartedState.record(bank: "a", enabled: [.agent("codex")], defaults: defaults)
        GettingStartedState.settle(.agent("cursor"), bank: "a", defaults: defaults)
        GettingStartedState.setScheduleAsked(bank: "a", defaults: defaults)
        XCTAssertNil(GettingStartedState.load(bank: "b", defaults: defaults))
        let a = GettingStartedState.load(bank: "a", defaults: defaults)
        XCTAssertEqual(a?.settled, [.agent("cursor")])
        XCTAssertEqual(a?.scheduleAsked, true)
    }

    func testRemoveDropsOneRowAndNeverCreatesARecord() throws {
        let d = try XCTUnwrap(UserDefaults(suiteName: "cicada.test.gs.remove.\(UUID().uuidString)"))
        GettingStartedState.remove(.browser("chrome-bookmarks"), bank: "b", defaults: d)
        XCTAssertNil(GettingStartedState.load(bank: "b", defaults: d), "no card for a bank the flow never ran on")
        GettingStartedState.record(bank: "b", enabled: [.browser("chrome-bookmarks"), .app("notes")], defaults: d)
        GettingStartedState.remove(.browser("chrome-bookmarks"), bank: "b", defaults: d)
        XCTAssertEqual(GettingStartedState.load(bank: "b", defaults: d)?.enabled, [.app("notes")])
    }
}
