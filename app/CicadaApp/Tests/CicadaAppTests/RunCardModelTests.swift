import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// The run card (owner 2026-10-26: "this consolidation ran at this time and it included this thing, with a dropdown
/// … exactly how much of your plan it used, what model it used"). Every word is pure (`RunCardModel`,
/// `RunItemGroups`, `Copy.RunCard`), and the two new wires decode the server's own fixtures
/// (`test_sleep_v5_app_fixtures.py` writes them from the real backend).
final class RunCardModelTests: XCTestCase {
    private static let fixtures = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("fixtures")
    private let us = Locale(identifier: "en_US")
    private let utc = TimeZone(identifier: "UTC")!

    private func fixture<T: Decodable>(_ type: T.Type, _ name: String) throws -> T {
        try JSONDecoder().decode(T.self, from: Data(contentsOf: Self.fixtures.appendingPathComponent(name)))
    }

    private func entry(_ json: String) throws -> SleepHistoryEntry {
        try JSONDecoder().decode(SleepHistoryEntry.self, from: Data(json.utf8))
    }

    private func plainCycle(commit: String = "abc1234", kind: String = "sleep") throws -> SleepHistoryEntry {
        try entry("""
        {"commitHash": "\(commit)", "date": "2026-10-26T13:18:27+00:00", "message": "Sleep cycle 2026-10-26",
         "filesChanged": [], "engine": "claude-cli", "kind": "\(kind)", "entitiesCreated": 1, "entitiesUpdated": 2,
         "episodes": 3, "sessions": 3, "authors": ["claude-haiku-5-5"], "durationMs": 23903,
         "usageSummary": {"basis": "list", "connection": "claude-plan", "costUsd": null, "engine": "claude-cli",
                          "equivCostUsd": 0.0038, "plan": null, "planShare": []}}
        """)
    }

    // MARK: The wires

    func testTheRunRefCarriesTheWholeRunsFigures() throws {
        let e = try fixture(SleepHistoryEntry.self, "sleep-history-run.json")
        let run = try XCTUnwrap(e.run)
        XCTAssertEqual(run.created, 9)
        XCTAssertEqual(run.updated, 0)
        XCTAssertEqual(run.questionsRaised, 0)
        XCTAssertEqual(run.models, ["model-a", "model-b"])
        XCTAssertEqual(run.usageSummary?.engine, "claude-cli")
    }

    func testAnOlderRunRefReadsAsNotRecordedNeverZero() throws {
        let ref = try JSONDecoder().decode(SleepRunRef.self, from: Data(#"{"id": "r1", "filed": 4}"#.utf8))
        XCTAssertNil(ref.created)
        XCTAssertNil(ref.updated)
        XCTAssertNil(ref.questionsRaised)
        XCTAssertNil(ref.usageSummary)
        XCTAssertEqual(ref.models, [])
    }

    func testTheItemsDecodeTheServersWire() throws {
        let items = try fixture(SleepConsolidated.self, "sleep-run-items.json")
        XCTAssertEqual(items.conversations.count, 4)
        XCTAssertEqual(items.conversations.first?.title, "Conversation 1")
        XCTAssertEqual(items.created.count, 3)
        XCTAssertEqual(items.updated.count, 3)
        XCTAssertEqual(items.archived.count, 3)
        XCTAssertEqual(items.removed.count, 2)
        XCTAssertEqual(items.counts["conversations"], 4)
        XCTAssertEqual(items.counts["archived"], 3, "the counts' snake_case keys are read by name")
        XCTAssertEqual(items.counts["removed"], 2)
        XCTAssertFalse(items.truncated)
        XCTAssertEqual(try JSONDecoder().decode(SleepConsolidated.self, from: Data("{}".utf8)), SleepConsolidated(),
                       "a missing list is empty, never a failed decode")
    }

    func testTheKeysPaths() {
        XCTAssertEqual(SleepConsolidatedKey.run("sleep_2026-10-26_131803").path, "/sleep/runs/sleep_2026-10-26_131803/items")
        XCTAssertEqual(SleepConsolidatedKey.commit("abc1234").path, "/sleep/history/abc1234/items")
    }

    // MARK: The card

    func testARunIsOneCardWithItsOwnNumbers() throws {
        let e = try fixture(SleepHistoryEntry.self, "sleep-history-run.json")
        let cards = RunCardModel.cards([e], locale: us, timeZone: utc)
        XCTAssertEqual(cards.count, 1)
        let card = cards[0]
        XCTAssertEqual(card.key, .run("sleep_leg1"))
        XCTAssertEqual(card.summary, "9 conversations · 9 new pages")
        XCTAssertEqual(card.starter, "You started it")
        XCTAssertEqual(card.engineWords, "Claude Code (your plan) · model-a, model-b")
        XCTAssertEqual(card.durationText, "2 h 14 m")
        XCTAssertEqual(card.outcome, .finished)
        XCTAssertEqual(card.ranAt, "2026-09-30T10:14:00+00:00")
        XCTAssertEqual(card.timeText(timeZone: utc), "10:14 AM")
        XCTAssertNotNil(card.usageLine(locale: us), "ruling 12: the run's usage, with its basis")
    }

    func testAPlainCycleIsOneCardAndDecayOrInboxAreNone() throws {
        let cards = RunCardModel.cards([try plainCycle(), try plainCycle(commit: "def5678", kind: "decay"),
                                        try plainCycle(commit: "0123abc", kind: "inbox")], locale: us)
        XCTAssertEqual(cards.map(\.id), ["abc1234"])
        let card = cards[0]
        XCTAssertEqual(card.key, .commit("abc1234"))
        XCTAssertEqual(card.summary, "3 conversations · 1 new page · 2 updated")
        XCTAssertNil(card.starter, "a plain cycle never recorded who started it")
        XCTAssertEqual(card.engineWords, "Claude Code (your plan) · claude-haiku-5-5")
        XCTAssertEqual(card.durationText, "23 s")
    }

    /// Owner 2026-11-24 ("showing less unnecessary information"): what it read, then one part for each thing that
    /// happened to the pages, a zero part dropped; questions are the opened card's own line.
    func testTheSummaryIsWhatItReadThenWhatItDidToThePages() {
        XCTAssertEqual(Copy.RunCard.summary(conversations: 12, created: 4, updated: 9, archived: 1, locale: us),
                       "12 conversations · 4 new pages · 9 updated · 1 archived")
        XCTAssertEqual(Copy.RunCard.summary(conversations: 12, created: 3, updated: 18, locale: us),
                       "12 conversations · 3 new pages · 18 updated")
        XCTAssertEqual(Copy.RunCard.summary(conversations: 12, created: 0, updated: 4, locale: us),
                       "12 conversations · 4 pages updated", "the first page part spells its noun")
        XCTAssertEqual(Copy.RunCard.summary(conversations: 3, created: 0, updated: 0, archived: 2, removed: 1, locale: us),
                       "3 conversations · 2 pages archived · 1 removed")
        XCTAssertEqual(Copy.RunCard.summary(conversations: 1, created: 0, updated: 0, locale: us),
                       "1 conversation · nothing new")
        XCTAssertEqual(Copy.RunCard.summary(conversations: 0, created: 0, updated: 1, archived: 2, locale: us),
                       "1 page updated · 2 archived", "a zero part is dropped: no \"0 conversations\"")
        XCTAssertEqual(Copy.RunCard.summary(conversations: 0, created: 0, updated: 0, locale: us), "Nothing new")
        XCTAssertEqual(Copy.RunCard.summary(conversations: 2, created: nil, updated: nil, locale: us),
                       "2 conversations", "unknown is never said as zero")
        XCTAssertEqual(Copy.RunCard.summary(conversations: nil, created: nil, updated: nil, locale: us),
                       Copy.RunCard.nothingRecorded)
        XCTAssertEqual(Copy.RunCard.summary(conversations: nil, created: 1, updated: 2, locale: us),
                       "1 new page · 2 updated")
        XCTAssertEqual(Copy.RunCard.summary(conversations: 1_200, created: 1, updated: nil, locale: us),
                       "1,200 conversations · 1 new page")
    }

    func testTheQuestionsLineIsOneQuietLine() {
        XCTAssertEqual(Copy.RunCard.questionsLine(raised: 3, settled: 2, us), "3 questions raised · 2 settled")
        XCTAssertEqual(Copy.RunCard.questionsLine(raised: 1, settled: 0, us), "1 question raised")
        XCTAssertEqual(Copy.RunCard.questionsLine(raised: 0, settled: 2, us), "2 questions settled")
        XCTAssertNil(Copy.RunCard.questionsLine(raised: 0, settled: 0, us), "nothing to say draws no line")
    }

    /// The head's first words: the day in words when it is today or yesterday (owner 2026-11-24: "Today, 2:10 AM").
    func testTheHeadSaysTodayAndYesterdayInWords() throws {
        let card = try XCTUnwrap(RunCardModel.cards([try plainCycle()], locale: us, timeZone: utc).first)
        func at(_ iso: String) -> Date { ISO8601DateFormatter().date(from: iso)! }
        XCTAssertEqual(card.whenText(now: at("2026-10-26T20:00:00+00:00"), timeZone: utc), "Today, 1:18 PM")
        XCTAssertEqual(card.whenText(now: at("2026-10-27T01:00:00+00:00"), timeZone: utc), "Yesterday, 1:18 PM")
        XCTAssertEqual(card.whenText(now: at("2026-11-02T20:00:00+00:00"), timeZone: utc), "Oct 26, 1:18 PM")
        XCTAssertTrue(card.isSameDay(as: "2026-10-26T01:00:00+00:00", timeZone: utc))
        XCTAssertFalse(card.isSameDay(as: "2026-10-25T23:00:00+00:00", timeZone: utc))
        XCTAssertEqual(card.metaLine, "Read for 23 s", "a plain cycle never recorded who started it")
    }

    func testHowARunEnded() {
        func ref(_ state: String?) -> SleepRunRef { SleepRunRef(id: "r", state: state) }
        func detail(_ reason: String) throws -> SleepRunDetail {
            try JSONDecoder().decode(SleepRunDetail.self, from: Data("""
            {"id": "r", "pauses": [{"startedAt": "2026-10-26T10:00:00+00:00", "reason": "\(reason)"}]}
            """.utf8))
        }
        XCTAssertEqual(RunCardModel.outcome(ref("finished"), detail: nil), .finished)
        XCTAssertEqual(RunCardModel.outcome(ref(nil), detail: nil), .finished)
        XCTAssertEqual(RunCardModel.outcome(ref("running"), detail: nil), .reading)
        XCTAssertEqual(RunCardModel.outcome(ref("ended"), detail: nil), .stopped)
        XCTAssertEqual(RunCardModel.outcome(ref("failed"), detail: nil), .failed)
        XCTAssertEqual(RunCardModel.outcome(ref("paused"), detail: nil), .paused)
        XCTAssertEqual(RunCardModel.outcome(ref("paused"), detail: try detail("plan_window")), .pausedPlanLimit)
        XCTAssertEqual(RunCardModel.outcome(ref("paused"), detail: try detail("reserve")), .pausedReserve)
        XCTAssertEqual(RunCardModel.Outcome.pausedPlanLimit.words, "Paused at your plan's limit")
        XCTAssertTrue(RunCardModel.Outcome.failed.needsYou)
        XCTAssertFalse(RunCardModel.Outcome.finished.needsYou)
        XCTAssertLessThan(Copy.SleepV5.spendHelp.count, 100, "one line (owner: no explanatory paragraphs)")
    }

    func testAScheduledRunSaysSo() throws {
        let ref = SleepRunRef(id: "s1", filed: 2, readMs: 1000, startedAt: "2026-10-26T03:00:00+00:00",
                              state: "finished", startedBy: "schedule", created: 0, updated: 1)
        let e = try entry("""
        {"commitHash": "a1b2c3d", "date": "2026-10-26T03:01:00+00:00", "message": "m", "filesChanged": [],
         "engine": "claude-cli", "kind": "sleep", "entitiesCreated": 0, "entitiesUpdated": 1, "episodes": 2,
         "sessions": 2, "authors": [], "drainId": "s1"}
        """)
        var withRun = e
        withRun.run = ref
        let card = try XCTUnwrap(RunCardModel.cards([withRun], locale: us).first)
        XCTAssertEqual(card.starter, "On schedule")
        XCTAssertEqual(card.summary, "2 conversations · 1 page updated")
    }

    // MARK: The dropdown

    func testTheLabelsAreTheNamesTheBankHas() {
        let items = SleepConsolidated(
            conversations: [.init(id: "ep1", title: "  "), .init(id: "ep2", title: "Plans")],
            created: [.init(id: "alpha-project", name: "Alpha Project")])
        XCTAssertEqual(RunItemGroups.conversationLabel(items.conversations[0]), "Untitled conversation")
        XCTAssertEqual(RunItemGroups.conversationLabel(items.conversations[1]), "Plans")
        XCTAssertEqual(RunItemGroups.pageLabel(items.created[0], names: .empty), "Alpha Project")
        XCTAssertEqual(RunItemGroups.pageLabel(.init(id: "beta-thing"), names: .empty), "beta-thing",
                       "no name: the id verbatim, never humanised")
    }

    /// DR-60: a key opens the dropdown in one frame; the pointer eases; Reduce Motion never animates.
    @MainActor
    func testTheDropdownAnimatesOnlyFromThePointer() {
        XCTAssertNil(RunCardMotion.animation(eventType: .keyDown, reduceMotion: false))
        XCTAssertNil(RunCardMotion.animation(eventType: nil, reduceMotion: false), "no event of its own: one frame")
        XCTAssertNil(RunCardMotion.animation(eventType: .leftMouseUp, reduceMotion: true))
        XCTAssertNotNil(RunCardMotion.animation(eventType: .leftMouseUp, reduceMotion: false))
        var inside: Animation? = CicadaMotion.groupExpand(reduceMotion: false)
        RunCardMotion.assistive { inside = RunCardMotion.current(reduceMotion: false) }
        XCTAssertNil(inside, "an assistive press opens in one frame whatever event came last")
    }

    /// Owner 2026-11-23 ("cards with logos"): a card's marks are the sources it read, most-read first, each once.
    func testTheCardsMarksAreTheSourcesItReadMostFirst() {
        let items = SleepConsolidated(conversations: [.init(id: "1", origin: "chatgpt"), .init(id: "2", origin: "claude-code"),
                                                      .init(id: "3", origin: "claude-code"), .init(id: "4", origin: "telegram")])
        XCTAssertEqual(RunItemsModel.origins(items), ["claude-code", "chatgpt", "telegram"], "ties keep the read's order")
        XCTAssertEqual(RunItemsModel.origins(nil), [], "nothing until the items load")
    }

    /// The pages a closed card names: new first, then updated, archived and removed; "+N" counts from the server's whole counts.
    func testTheCardsPagesAreInReadingOrderWithTheWholeCount() {
        let items = SleepConsolidated(created: [.init(id: "alpha")], updated: [.init(id: "beta"), .init(id: "gamma")],
                                      archived: [.init(id: "delta")], removed: [.init(id: "eps", gone: true)],
                                      counts: ["created": 1, "updated": 40, "archived": 1, "removed": 1], truncated: true)
        let preview = RunItemsModel.preview(items)
        XCTAssertEqual(preview.pages.map(\.id), ["alpha", "beta", "gamma", "delta", "eps"])
        XCTAssertEqual(preview.pages.map(\.change), [.created, .updated, .updated, .archived, .removed],
                       "a page without its own change takes its list's")
        XCTAssertEqual(preview.total, 43)
        XCTAssertEqual(RunItemsModel.preview(nil).total, 0)
    }

    /// items-3: a page carries the read's commits that changed it; an older backend's page decodes with none.
    func testAPageDecodesItsCommitsAndAnOlderPageHasNone() throws {
        let new = try JSONDecoder().decode(SleepConsolidated.Page.self,
                                           from: Data(#"{"id":"alpha","commits":["aaa1111","bbb2222"]}"#.utf8))
        XCTAssertEqual(new.commits, ["aaa1111", "bbb2222"])
        let old = try JSONDecoder().decode(SleepConsolidated.Page.self, from: Data(#"{"id":"alpha"}"#.utf8))
        XCTAssertEqual(old.commits, [])
        XCTAssertNil(old.change, "an older backend's page says no change of its own")
        XCTAssertEqual(old.episodes, [])
    }

    // MARK: The view model

    private struct Offline: Error {}

    /// A view model that never reaches a backend: every read it makes besides the items is refused.
    @MainActor
    private func makeVM(_ fetch: @escaping (SleepConsolidatedKey, String?) async throws -> Conditional<SleepConsolidated>)
        -> SleepViewModel {
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        return SleepViewModel(store: store, fetchSleepStatus: { throw Offline() }, requestCancel: { throw Offline() },
                              fetchHistory: { throw Offline() }, fetchDetail: { _ in throw Offline() },
                              fetchEngine: { throw Offline() }, putSchedule: { _ in throw Offline() },
                              requestEnd: { throw Offline() }, requestRetry: { _ in throw Offline() },
                              fetchRunOptions: { throw Offline() }, putRunOptions: { _ in throw Offline() },
                              fetchQueue: { throw Offline() }, fetchRun: { _ in throw Offline() },
                              fetchEpisodes: { _ in throw Offline() }, fetchSchedule: { throw Offline() },
                              fetchMachines: { throw Offline() }, fetchConsolidated: fetch)
    }

    @MainActor
    func testItemsAreCachedRevalidatedAndDroppedOnABankSwitch() async throws {
        var calls: [(SleepConsolidatedKey, String?)] = []
        var answers: [Conditional<SleepConsolidated>] = [
            Conditional(value: SleepConsolidated(conversations: [.init(id: "ep1")]), etag: "\"t1\"", notModified: false),
            Conditional(value: nil, etag: "\"t1\"", notModified: true),
        ]
        let vm = makeVM({ key, etag in
            calls.append((key, etag))
            return answers.removeFirst()
        })
        await vm.loadConsolidated(.run("r1"))
        XCTAssertEqual(vm.consolidated[.run("r1")]?.conversations.count, 1)
        await vm.loadConsolidated(.run("r1"))
        XCTAssertEqual(calls.map(\.1), [nil, "\"t1\""], "the second open sends the tag it holds")
        XCTAssertEqual(vm.consolidated[.run("r1")]?.conversations.count, 1, "a 304 keeps the copy")
        await vm.bankChanged()
        XCTAssertTrue(vm.consolidated.isEmpty)
    }

    @MainActor
    func testAFailedFirstReadIsSaidAndAFailedRevalidationKeepsTheCopy() async {
        struct Down: Error {}
        var fail = true
        let vm = makeVM({ _, _ in
            if fail { throw Down() }
            return Conditional(value: SleepConsolidated(), etag: nil, notModified: false)
        })
        await vm.loadConsolidated(.commit("abc1234"))
        XCTAssertTrue(vm.consolidatedFailed.contains(.commit("abc1234")))
        fail = false
        await vm.loadConsolidated(.commit("abc1234"))
        XCTAssertFalse(vm.consolidatedFailed.contains(.commit("abc1234")))
        fail = true
        await vm.loadConsolidated(.commit("abc1234"))
        XCTAssertFalse(vm.consolidatedFailed.contains(.commit("abc1234")), "a copy to show is never replaced by an error")
    }
}
