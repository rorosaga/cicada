import AppKit
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
        XCTAssertEqual(items.conversations.count, 9)
        XCTAssertEqual(items.conversations.first?.title, "Conversation 1")
        XCTAssertEqual(items.created.count, 9)
        XCTAssertEqual(items.counts["conversations"], 9)
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
        XCTAssertEqual(card.summary, "3 conversations · 1 new page · 2 updates")
        XCTAssertNil(card.starter, "a plain cycle never recorded who started it")
        XCTAssertEqual(card.engineWords, "Claude Code (your plan) · claude-haiku-5-5")
        XCTAssertEqual(card.durationText, "23 s")
    }

    func testTheSummaryDropsWhatItHasNothingToSay() {
        XCTAssertEqual(Copy.RunCard.summary(conversations: 12, created: 3, updated: 18, questions: 2, locale: us),
                       "12 conversations · 3 new pages · 18 updates · 2 questions")
        XCTAssertEqual(Copy.RunCard.summary(conversations: 1, created: 0, updated: 0, questions: 0, locale: us),
                       "1 conversation · nothing new")
        XCTAssertEqual(Copy.RunCard.summary(conversations: 2, created: nil, updated: nil, questions: nil, locale: us),
                       "2 conversations", "unknown is never said as zero")
        XCTAssertEqual(Copy.RunCard.summary(conversations: nil, created: nil, updated: nil, questions: nil, locale: us),
                       Copy.RunCard.nothingRecorded)
        XCTAssertEqual(Copy.RunCard.summary(conversations: 1_200, created: 1, updated: nil, questions: nil, locale: us),
                       "1,200 conversations · 1 new page")
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
        XCTAssertEqual(card.summary, "2 conversations · 1 update")
    }

    // MARK: The dropdown

    func testTheGroupsHoldOnlyWhatTheRunDid() throws {
        let items = SleepConsolidated(
            conversations: [.init(id: "ep1", title: "  "), .init(id: "ep2", title: "Plans")],
            created: [.init(id: "alpha-project", name: "Alpha Project")],
            questionsSettled: [.init(id: "inbox-1", title: "Which alpha?")],
            counts: ["conversations": 2, "created": 1, "updated": 0, "questions_raised": 0, "questions_settled": 1])
        XCTAssertEqual(RunItemGroups.groups(items).map(\.title), ["Conversations read", "New pages", "Questions settled"])
        XCTAssertEqual(RunItemGroups.conversationLabel(items.conversations[0]), "Untitled conversation")
        XCTAssertEqual(RunItemGroups.conversationLabel(items.conversations[1]), "Plans")
        XCTAssertEqual(RunItemGroups.pageLabel(items.created[0], names: .empty), "Alpha Project")
        XCTAssertEqual(RunItemGroups.pageLabel(.init(id: "beta-thing"), names: .empty), "beta-thing",
                       "no name: the id verbatim, never humanised")
    }

    func testTheGroupCountIsTheServersWholeCount() {
        let items = SleepConsolidated(conversations: [.init(id: "ep1")], counts: ["conversations": 450], truncated: true)
        XCTAssertEqual(RunItemGroups.groups(items).first?.count, 450)
    }

    /// DR-60: a key opens the dropdown in one frame; the pointer eases; Reduce Motion never animates.
    func testTheDropdownAnimatesOnlyFromThePointer() {
        XCTAssertNil(RunCardMotion.animation(eventType: .keyDown, reduceMotion: false))
        XCTAssertNil(RunCardMotion.animation(eventType: .leftMouseUp, reduceMotion: true))
        XCTAssertNotNil(RunCardMotion.animation(eventType: .leftMouseUp, reduceMotion: false))
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
