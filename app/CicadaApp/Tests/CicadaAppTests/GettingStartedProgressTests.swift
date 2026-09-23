import XCTest
@testable import CicadaApp

/// Track I part b (design §4.2, R-IB18–R-IB20) — the card as pure functions.
final class GettingStartedProgressTests: XCTestCase {
    private let en = Locale(identifier: "en_US")

    private func item(_ id: FoundItemID, _ readiness: FoundItem.Readiness, group: FoundGroup = .agents) -> FoundItem {
        FoundItem(id: id, group: group, title: id.key, isPresent: true, content: .ownIntentionalAct,
                  readiness: readiness, opensAnotherApp: false)
    }

    private func inputs(_ enabled: [FoundItemID], items: [FoundItem] = [], runner: [FoundItemID: FoundRowState] = [:],
                        browserOn: Set<String> = [], settled: Set<FoundItemID> = []) -> GettingStartedInputs {
        GettingStartedInputs(record: GettingStartedRecord(enabled: enabled, settled: settled), items: items,
                             runnerRows: runner, browserOn: browserOn, wiringLoaded: true)
    }

    func testAfterARelaunchRowsComeFromTheMachineNotFromMemory() {
        let rows = GettingStartedProgress.rows(inputs(
            [.agent("claude-code"), .agent("codex"), .browser("chrome-bookmarks"), .browser("safari-bookmarks")],
            items: [item(.agent("claude-code"), .alreadyOn), item(.agent("codex"), .ready),
                    item(.browser("chrome-bookmarks"), .ready, group: .browsers),
                    item(.browser("safari-bookmarks"), .needsPermission, group: .browsers)],
            browserOn: ["chrome-bookmarks"]))
        XCTAssertEqual(rows.map(\.state), [.on, .off, .on, .needsAction(Copy.foundAllow)])
    }

    func testARunningRowOutranksWhatTheProbeLastSaid() {
        let rows = GettingStartedProgress.rows(inputs([.agent("codex")], items: [item(.agent("codex"), .alreadyOn)],
                                                      runner: [.agent("codex"): .working(Copy.foundConnecting)]))
        XCTAssertEqual(rows.first?.state, .working(Copy.foundConnecting))
    }

    func testClaudeDesktopFinishesInSettingsAndCursorOnceSettled() {
        let rows = GettingStartedProgress.rows(inputs([.agent("claude-desktop"), .agent("cursor")],
                                                      items: [item(.agent("claude-desktop"), .ready)],
                                                      settled: [.agent("cursor")]))
        XCTAssertEqual(rows[0].state, .needsAction(Copy.foundClaudeDesktopDetail))
        XCTAssertEqual(rows[0].settingsLink, .agents)
        XCTAssertEqual(rows[1].state, .on, "Cursor owns its config; the opened confirm is all Cicada can know")
    }

    func testADismissedRowIsSettledEvenOverAFailureThisSession() {
        let rows = GettingStartedProgress.rows(inputs([.agent("codex")], items: [item(.agent("codex"), .ready)],
                                                      runner: [.agent("codex"): .failed("x")],
                                                      settled: [.agent("codex")]))
        XCTAssertEqual(rows.first?.state, .on, "✕ settles any row (R-IB18)")
    }

    func testADroppedExportThisSessionIsARowAfterTheEnabledOnes() {
        let rows = GettingStartedProgress.rows(inputs([.agent("codex")], items: [item(.agent("codex"), .alreadyOn)],
                                                      runner: [.dropped("d1"): .on]))
        XCTAssertEqual(rows.map(\.id), [.agent("codex"), .dropped("d1")])
    }

    func testAlsoFoundIsWhatIsHereButNotYetOn() {
        let found = GettingStartedProgress.alsoFound(inputs([.agent("codex")],
            items: [item(.agent("codex"), .ready), item(.agent("claude-code"), .alreadyOn),
                    item(.browser("chrome-bookmarks"), .ready, group: .browsers)]))
        XCTAssertEqual(found.map(\.id), [.browser("chrome-bookmarks")])
    }

    func testDoneNeedsEveryRowOnTheFirstReadAndTheScheduleAnswer() {
        let on = [GettingStartedRow(id: .agent("codex"), title: "Codex", detail: "", state: .on)]
        let off = [GettingStartedRow(id: .agent("codex"), title: "Codex", detail: "", state: .off)]
        XCTAssertTrue(GettingStartedProgress.isDone(rows: on, hasRunBefore: true, scheduleAnswered: true))
        XCTAssertFalse(GettingStartedProgress.isDone(rows: off, hasRunBefore: true, scheduleAnswered: true))
        XCTAssertFalse(GettingStartedProgress.isDone(rows: on, hasRunBefore: false, scheduleAnswered: true))
        XCTAssertFalse(GettingStartedProgress.isDone(rows: on, hasRunBefore: true, scheduleAnswered: false))
    }

    func testTheCardShowsOnlyForARecordedUnhiddenBank() {
        XCTAssertFalse(GettingStartedProgress.visible(record: nil))
        XCTAssertTrue(GettingStartedProgress.visible(record: GettingStartedRecord()))
        XCTAssertFalse(GettingStartedProgress.visible(record: GettingStartedRecord(hidden: true)))
    }

    // MARK: The first read (design §4.2's table)

    private func read(_ edit: (inout FirstReadInputs) -> Void) -> FirstReadStep {
        var i = FirstReadInputs()
        edit(&i)
        return FirstReadStep.of(i)
    }

    func testTheFirstReadTable() {
        XCTAssertEqual(read { $0.unprocessed = 0 }, .nothingYet)
        XCTAssertEqual(read { $0.unprocessed = nil }, .nothingYet, "unknown is never a number")
        XCTAssertEqual(read { $0.unprocessed = 61 }, .waiting(61))
        XCTAssertEqual(read { $0.running = true; $0.stage = 0; $0.read = 12; $0.total = 61 },
                       .running(read: 12, total: 61, stage: 1), "R-Z14: the wire counts completed stages")
        XCTAssertEqual(read { $0.hasRunBefore = true; $0.pages = 146; $0.unprocessed = 0 }, .finished(pages: 146))
        XCTAssertEqual(read { $0.hasRunBefore = true; $0.episodesTotal = 50; $0.episodesQueued = 379; $0.unprocessed = 329 },
                       .capped(read: 50, left: 329))
        XCTAssertEqual(read { $0.error = "No engine could run. Add a key." }, .failed("No engine could run."))
    }

    func testEveryStepHasItsTextTwinAndNeverAGuess() {
        XCTAssertEqual(FirstReadStep.running(read: 0, total: 0, stage: 2).line(locale: en), Copy.gsReading,
                       "past Stage 1 there is no per-item count — never 'Read 0 of 0'")
        XCTAssertEqual(FirstReadStep.running(read: 12, total: 1_061, stage: 1).line(locale: en), "Reading · Read 12 of 1,061")
        XCTAssertEqual(FirstReadStep.waiting(61).line(locale: en), "61 waiting to be read.")
        XCTAssertEqual(FirstReadStep.finished(pages: 146).line(locale: en), "Your memory has 146 pages now.")
        XCTAssertEqual(FirstReadStep.finished(pages: nil).line(locale: en), Copy.gsFinishedNoCount)
        XCTAssertEqual(FirstReadStep.capped(read: 50, left: 329).line(locale: en), "Read 50 this round. 329 still waiting.")
    }

    func testTheWormAndTheOneActionFollowTheStep() {
        XCTAssertEqual(FirstReadStep.waiting(3).worm, .reading)
        XCTAssertEqual(FirstReadStep.running(read: 1, total: 3, stage: 2).worm, .sleeping(stage: 2))
        XCTAssertEqual(FirstReadStep.failed("x").worm, .error)
        XCTAssertEqual(FirstReadStep.waiting(3).action, .readNow)
        XCTAssertEqual(FirstReadStep.running(read: 1, total: 3, stage: 1).action, .watchSleep)
        XCTAssertEqual(FirstReadStep.finished(pages: 2).action, .openGraph)
        XCTAssertEqual(FirstReadStep.capped(read: 50, left: 9).action, .readNext(50))
        XCTAssertNil(FirstReadStep.nothingYet.action)
    }

    // MARK: The schedule question (R-IB20)

    func testOnlyAPersonStillOnManualIsAsked() {
        XCTAssertTrue(ScheduleChoice.asks(ScheduleConfig(mode: "manual", hour: 3, minute: 0)))
        for mode in ["daily", "interval", "after_import"] {
            XCTAssertFalse(ScheduleChoice.asks(ScheduleConfig(mode: mode, hour: 3, minute: 0)),
                           "\(mode) was set in Settings — an answer, never downgraded (Track P R4)")
        }
    }

    func testEachAnswerWritesOnlyWhatItSays() {
        let current = ScheduleConfig(mode: "manual", hour: 9, minute: 15, intervalHours: 4)
        let nightly = ScheduleChoice.config(for: .daily, current: current)
        XCTAssertEqual([nightly.mode, "\(nightly.hour):\(nightly.minute)"], ["daily", "3:0"])
        XCTAssertEqual(ScheduleChoice.config(for: .afterImport, current: current).mode, "after_import")
        XCTAssertEqual(ScheduleChoice.config(for: .manual, current: current), current)
    }
}
