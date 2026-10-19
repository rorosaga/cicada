import XCTest
@testable import CicadaApp

/// "Say it once" (owner 2026-10-19: "Avoid repetition … For every page in the app, if I press the button in the side
/// panel again, it should take me to the main page of that page.") — the rules each page applies, pure where they can
/// be, and the wiring that sends every rail cell's second click through the one mechanism.
@MainActor
final class SayItOnceTests: XCTestCase {
    private func source(_ relative: String) throws -> String {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp")
        return try String(contentsOf: root.appendingPathComponent(relative), encoding: .utf8)
    }

    // MARK: The sidebar's second click — every page, one mechanism

    /// Every rail page hears its own reselect through `onRailReselect` and applies it through `popToRoot`, so the ⌘
    /// key never animates (DR-60) on any of them.
    func testEveryRailPageReturnsToItsRootThroughTheSharedMechanism() throws {
        let pages: [(AppTab, String)] = [
            (.home, "Views/Home/HomeView.swift"), (.graph, "Views/Graph/GraphPage.swift"),
            (.clusters, "Views/Clusters/ClustersPage.swift"), (.skills, "Views/Skills/SkillsPage.swift"),
            (.sleep, "Views/Sleep/SleepView.swift"), (.inbox, "Views/Inbox/InboxPage.swift"),
            (.sources, "Views/Sources/SourcesPageView.swift"), (.projects, "Views/Projects/ProjectsPage.swift"),
            (.looks, "Views/Looks/LooksPage.swift"),
        ]
        XCTAssertEqual(Set(pages.map(\.0)), Set(AppTab.allCases), "every rail cell has a root to return to")
        for (tab, path) in pages {
            let text = try source(path)
            XCTAssertTrue(text.contains(".onRailReselect(.\(tab.rawValue.lowercased())"), "\(path) hears its reselect")
            XCTAssertTrue(text.contains("popToRoot(reduceMotion: reduceMotion"), "\(path) uses the shared motion rule")
            XCTAssertFalse(text.contains("router.reselections(of:"), "\(path) never reads the counter itself")
        }
    }

    func testTheRouterCountsReselectsPerPageAndRemembersTheKey() {
        let router = AppRouter()
        router.reselect(.inbox)
        XCTAssertEqual(router.reselections(of: .inbox), 1)
        XCTAssertFalse(router.lastReselectByKey)
        router.reselect(.sleep, byKey: true)
        XCTAssertEqual(router.reselections(of: .sleep), 1)
        XCTAssertTrue(router.lastReselectByKey, "⌘N is a keyboard action: popToRoot runs it in Instant.run")
        var ran = 0
        router.popToRoot(reduceMotion: false) { ran += 1 }
        XCTAssertEqual(ran, 1, "the change runs once, whichever motion")
    }

    // MARK: Sleep — the queue is the room's headline

    func testTheWaitingTabDropsItsCountWhileTheRoomSaysIt() {
        let lead = SentenceLine(lead: "23 to read — overdue.", numeral: "23", qualifier: "overdue")
        let tabs = SleepTabRow.tabs([.waiting, .saved, .pastReads], waiting: 23, saved: 7, videos: 0, roomLead: lead)
        XCTAssertEqual(tabs.map(\.count), [nil, 7, nil])
        let reading = SentenceLine(lead: "Reading 14 of 25.", numeral: "14 of 25")
        XCTAssertEqual(SleepTabRow.tabs([.waiting], waiting: 23, saved: 0, videos: 0, roomLead: reading).first?.count, 23,
                       "a run's progress is another number: the tab keeps its count")
        XCTAssertEqual(SleepTabRow.tabs([.waiting], waiting: 1_200, saved: 0, videos: 0,
                                        roomLead: SentenceLine(lead: "1,200 to read.", numeral: "1,200")).first?.count,
                       nil, "a grouped numeral is the same count")
        XCTAssertEqual(SleepTabRow.tabs([.waiting], waiting: 23, saved: 0, videos: 0).first?.count, 23,
                       "no room on screen (an item open): the tab counts")
    }

    // MARK: Past nights — the day once, what no row recorded once

    private func history(_ rows: [String]) throws -> [SleepHistoryEntry] {
        try JSONDecoder().decode([SleepHistoryEntry].self, from: Data(("[" + rows.joined(separator: ",") + "]").utf8))
    }

    private func row(_ hash: String, _ date: String, usage: Bool = false, ms: Int? = nil) -> String {
        var fields = [#""commitHash":"\#(hash)""#, #""date":"\#(date)""#, #""message":"Sleep cycle""#,
                      #""filesChanged":[]"#, #""kind":"sleep""#]
        if usage { fields.append(#""usageSummary":{"calls":1}"#) }
        if let ms { fields.append(#""durationMs":\#(ms)"#) }
        return "{" + fields.joined(separator: ",") + "}"
    }

    func testPastNightsSaysTheDayOnceAndWhatNoRowRecordedOnce() throws {
        let entries = try history([row("a", "2026-10-19T14:00:00+00:00"), row("b", "2026-10-19T12:00:00+00:00"),
                                   row("c", "2026-10-17T12:00:00+00:00")])
        let layout = PastNightsLayout(entries)
        XCTAssertEqual(layout.datedIds, ["a", "c"], "the day on the first row of each day")
        XCTAssertTrue(layout.usageSaidOnce)
        XCTAssertTrue(layout.durationSaidOnce)
        XCTAssertEqual(layout.title, "Past nights · usage and time not recorded")

        let mixed = PastNightsLayout(try history([row("a", "2026-10-19T22:34:00+00:00", ms: 4_000),
                                                  row("b", "2026-10-18T21:00:00+00:00")]))
        XCTAssertFalse(mixed.durationSaidOnce, "one row has a time: each row says its own")
        XCTAssertEqual(mixed.title, "Past nights · usage not recorded")
        XCTAssertEqual(PastNightsLayout(try history([row("a", "2026-10-19T22:34:00+00:00")])).title, "Past nights",
                       "one row says its own")
    }

    func testTheReadoutLeavesTheEngineToPastNightsUnlessItHasAReason() {
        let shown = readoutRows(entityCount: 74, sourceCount: 8, lastDurationMs: nil, lastEngine: "litellm",
                                engineDetail: nil, engineShownBelow: true)
        XCTAssertFalse(shown.contains { $0.id == "engine" })
        let reason = readoutRows(entityCount: 74, sourceCount: 8, lastDurationMs: nil, lastEngine: "litellm",
                                 engineDetail: "the key was missing", engineShownBelow: true)
        XCTAssertTrue(reason.contains { $0.id == "engine" }, "a reason only the readout can say keeps the row")
        XCTAssertTrue(readoutRows(entityCount: 74, sourceCount: 8, lastDurationMs: nil, lastEngine: "litellm",
                                  engineDetail: nil).contains { $0.id == "engine" })
    }

    // MARK: Inbox — the page's name once

    func testAQuestionThatNamesItsPageDoesNotPrintTheNameAgain() {
        XCTAssertTrue(InboxRowWords.repeats(name: "Beta Project", in: "Still tracking Beta Project?"))
        XCTAssertTrue(InboxRowWords.repeats(name: "grace example", in: "I'm reading something different about Grace Example"))
        XCTAssertFalse(InboxRowWords.repeats(name: "Rover Arm Project", in: "How did the gripper calibration go?"))
        XCTAssertFalse(InboxRowWords.repeats(name: "", in: "Who is Sam?"))
    }

    func testAReviewCardSaysTheDayOrItsAgeNeverBoth() {
        XCTAssertEqual(Copy.Inbox.Review.lastSaid(day: nil, age: "today"), "Last said today")
        XCTAssertEqual(Copy.People.knownSinceValue("Oct 18", days: 1), "Oct 18")
        XCTAssertEqual(Copy.People.knownSinceValue("Oct 1", days: 20), "Oct 1 · 2 weeks")
    }
}
