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
        XCTAssertNil(AppRouter.rootMotion(byKey: true, reduceMotion: false), "the ⌘ key never animates (DR-60)")
        XCTAssertNotNil(AppRouter.rootMotion(byKey: false, reduceMotion: false), "a click rides the columns' curve")
        XCTAssertNil(AppRouter.rootMotion(byKey: false, reduceMotion: true), "Reduce Motion: no motion either")
    }

    /// A half-typed answer keeps its question: the page's root is not worth a person's words (review of #363).
    func testADraftKeepsTheOpenQuestionOnAReselect() throws {
        let vm = InboxViewModel(store: Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI()))
        XCTAssertFalse(vm.hasDraft)
        vm.noteDraft("inbox-001", "she moved to")
        XCTAssertTrue(vm.hasDraft)
        vm.noteDraft("inbox-001", "   ")
        XCTAssertFalse(vm.hasDraft, "whitespace is no draft")
        let page = try source("Views/Inbox/InboxPage.swift")
        XCTAssertTrue(page.contains("guard !viewModel.hasDraft else { return }"), "the reselect leaves a draft's question open")
        for path in ["Views/Inbox/InboxFocusCard.swift", "Views/Inbox/FocusCardVariants.swift",
                     "Views/Inbox/InboxReviewView.swift"] {
            XCTAssertTrue(try source(path).contains("noteDraft("), "\(path) reports its field's draft")
        }
    }

    // MARK: Sleep — the pinned Waiting tab keeps the total

    func testTheWaitingTabAlwaysCountsAndTheEyebrowDoesNot() {
        let tabs = SleepTabRow.tabs([.waiting, .saved, .pastReads], waiting: 23, saved: 7, videos: 0)
        XCTAssertEqual(tabs.map(\.count), [23, 7, nil], "pinned under the titlebar, the tab is where the total stays")
        XCTAssertEqual(SleepEyebrow.text(waiting: 23, lastSleepAt: nil, now: .now), "Sleep")
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

    /// A run's batch with usage beside bare cycles: the label never claims "not recorded", and the batch keeps its line
    /// (ruling 12; review of #363).
    func testARunsBatchUsageIsNeverHiddenUnderTheLabel() throws {
        let batch = #"{"commitHash":"r1b1","date":"2026-10-19T14:00:00+00:00","message":"Sleep cycle","filesChanged":[],"#
            + #""kind":"sleep","drainId":"run-1","batch":1,"batches":1,"usageSummary":{"costUsd":0.02},"#
            + #""run":{"id":"run-1","batches":1,"startedAt":"2026-10-19T14:00:00+00:00","startedBy":"user"}}"#
        let entries = try history([batch, row("b", "2026-10-18T12:00:00+00:00"), row("c", "2026-10-17T12:00:00+00:00")])
        let layout = PastNightsLayout(entries)
        XCTAssertTrue(layout.items.contains { if case .run = $0 { return true } else { return false } })
        XCTAssertFalse(layout.usageSaidOnce, "one batch recorded usage: every row says its own")
        XCTAssertEqual(layout.title, "Past nights · time not recorded")
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
        XCTAssertTrue(InboxRowWords.repeats(name: "Grace Example", in: "I'm reading something different about Grace EXAMPLE"),
                      "case-insensitive after the first letter")
        XCTAssertTrue(InboxRowWords.repeats(name: "Tool Example A (CLI)", in: "Tool Example A (CLI)"), "literal characters")
        XCTAssertTrue(InboxRowWords.repeats(name: "Jose Example", in: "Where does José Example work now?"), "diacritics")
        XCTAssertFalse(InboxRowWords.repeats(name: "Rover Arm Project", in: "How did the gripper calibration go?"))
        XCTAssertFalse(InboxRowWords.repeats(name: "", in: "Who is Sam?"))
    }

    /// Whole words only, and never part of a longer name (review of #363).
    func testAPartOfAWordOrOfALongerNameIsNotTheName() {
        XCTAssertFalse(InboxRowWords.repeats(name: "Al", in: "What does Alpha Project use now?"))
        XCTAssertFalse(InboxRowWords.repeats(name: "Go", in: "How did it go?"))
        XCTAssertFalse(InboxRowWords.repeats(name: "Rust", in: "Do you still trust the old cluster?"))
        XCTAssertFalse(InboxRowWords.repeats(name: "Claude", in: "Which plan does Claude Code use?"))
        XCTAssertFalse(InboxRowWords.repeats(name: "Code", in: "Which plan does Claude Code use?"))
        XCTAssertFalse(InboxRowWords.repeats(name: "Tool Example A", in: "Tool Example A (CLI)"))
        XCTAssertFalse(InboxRowWords.repeats(name: "Beta", in: "Still tracking beta-testers?"))
        XCTAssertFalse(InboxRowWords.repeats(name: "C++", in: "Is C+ enough?"), "the name's characters are literal")
    }

    private func decayItem(lastSaid: String) throws -> InboxItem {
        var item = try JSONDecoder().decode(InboxItem.self, from: Data(#"{"id":"inbox-d","kind":"decay","requiredInput":"choice","title":"Still tracking Beta Project?","priority":0.5,"createdDate":"2026-09-01","entityId":"beta-project"}"#.utf8))
        item.subject = InboxSubject(conversations: 2, lastSaid: lastSaid)
        return item
    }

    func testAReviewCardSaysTheDayOrItsAgeNeverBoth() throws {
        let en = Locale(identifier: "en_US"), utc = TimeZone(identifier: "UTC")!
        let now = try XCTUnwrap(InboxAge.date("2026-10-19"))
        let recent = ReviewContext.lines(try decayItem(lastSaid: "2026-10-17"), now: now, locale: en, timeZone: utc)
        XCTAssertEqual(recent.first, "Last said 2 days ago", "this week: the age alone, never the day beside it")
        let older = ReviewContext.lines(try decayItem(lastSaid: "2026-03-02"), now: now, locale: en, timeZone: utc)
        XCTAssertEqual(older.first?.hasPrefix("Last said "), true)
        XCTAssertFalse(older.first?.contains("ago") ?? true, "older: the day alone")
        XCTAssertEqual(Copy.Inbox.Review.lastSaid(day: nil, age: "today"), "Last said today")
        XCTAssertEqual(Copy.People.knownSinceValue("Oct 18", days: 1), "Oct 18")
        XCTAssertEqual(Copy.People.knownSinceValue("Oct 1", days: 20), "Oct 1 · 2 weeks")
    }
}
