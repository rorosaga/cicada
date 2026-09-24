import XCTest
@testable import CicadaApp

/// R-OB4 — one projection: the Import rows, the topbar's "k still coming in", F-07 and Home read these.
@MainActor
final class SetupProgressTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_790_000_000)

    private func channel(_ id: String, synced: Date?) -> SourceChannel {
        SourceChannel(id: id, label: id, connected: true,
                      lastSync: synced.map { ISO8601DateFormatter().string(from: $0) }, actions: ["sync"])
    }

    /// F-02's moment: Chrome reading (with ×), Safari done, Calendar done, Notes reading, Wispr reading, a Claude
    /// export importing — "4 still coming in".
    func testF02sStoryIsFourStillComingIn() {
        let rows: [GettingStartedRow] = [
            .init(id: .browser("chrome-bookmarks"), title: "Chrome", detail: "", state: .working("…")),
            .init(id: .browser("safari-bookmarks"), title: "Safari", detail: "", state: .on),
            .init(id: .app("calendar-local"), title: "Calendar", detail: "", state: .on),
            .init(id: .app("notes"), title: "Apple Notes", detail: "", state: .working(Copy.gsBringingIn)),
            .init(id: .app("wispr-flow"), title: "Wispr Flow", detail: "", state: .working(Copy.gsBringingIn)),
            .init(id: .dropped("d1"), title: "Claude history", detail: "", state: .working(Copy.gsBringingIn)),
        ]
        var facts = SetupFacts()
        facts.channels = [channel("safari-bookmarks", synced: now), channel("calendar-local", synced: now)]
        facts.runs = ["chrome-bookmarks": .init(detail: "Reading 1,204 of 2,104 bookmarks", fraction: 0.57, cancellable: true),
                      IntakeRouter.runKey("d1"): .init(detail: "Reading 9 of 17 conversations", fraction: 0.53, cancellable: false)]
        facts.watches = ["wispr-flow": .syncing]
        facts.origins = [.dropped("d1"): "claude-export"]
        let snapshots = SetupProgress.snapshots(rows, facts: facts)
        XCTAssertEqual(SetupProgress.stillComingIn(snapshots), 4)
        XCTAssertTrue(snapshots[0].cancellable, "a browser's run can stop (R-OB10)")
        XCTAssertFalse(snapshots[5].cancellable, "an import never offers ×")
        XCTAssertEqual(SourceRowText.secondLine(snapshots[5].model), "Reading 9 of 17 conversations")
        XCTAssertEqual(snapshots[1].model.status, .synced(now))
        XCTAssertEqual(snapshots[5].model.origin, "claude-export", "a drop wears its vendor's mark")
    }

    func testAPhaseIsWhatTheRowIsDoing() {
        XCTAssertEqual(SetupProgress.phase(.on, status: .syncing(detail: nil, fraction: nil, cancellable: false)), .comingIn,
                       "a later read of a done source is still coming in")
        XCTAssertEqual(SetupProgress.phase(.failed("x"), status: .problem("x")), .needsYou)
        XCTAssertEqual(SetupProgress.phase(.needsAction("Allow…"), status: .idle), .needsYou, "waiting on the person")
        XCTAssertEqual(SetupProgress.phase(.off, status: .idle), .off)
    }

    /// F-07 — what still runs, what keeps up on its own and its newest sync.
    func testTheSummaryCountsOnlySourcesThatKeepUp() {
        let rows: [GettingStartedRow] = [
            .init(id: .browser("chrome-bookmarks"), title: "Chrome", detail: "", state: .on),
            .init(id: .app("notes"), title: "Apple Notes", detail: "", state: .on),
            .init(id: .dropped("d1"), title: "Claude history", detail: "", state: .working(Copy.gsBringingIn)),
        ]
        var facts = SetupFacts()
        facts.channels = [channel("chrome-bookmarks", synced: now.addingTimeInterval(-120)), channel("notes", synced: now)]
        facts.runs = [IntakeRouter.runKey("d1"): .init(detail: "14 of 17", fraction: 0.8, cancellable: false)]
        let summary = SetupProgress.summary(SetupProgress.snapshots(rows, facts: facts),
                                            keepsUp: { if case .app("notes") = $0 { return false }; return true })
        XCTAssertEqual(summary.comingIn.map(\.id), [.dropped("d1")])
        XCTAssertEqual(summary.keepingUp.map(\.id), [.browser("chrome-bookmarks")], "a one-time read does not keep up")
        XCTAssertEqual(summary.newestSync, now.addingTimeInterval(-120))
    }

    /// F-04 … F-06 open with the newest row that finished after the page appeared.
    func testArrivalIsTheNewestRowThatFinishedSinceThePageAppeared() {
        let rows: [GettingStartedRow] = [
            .init(id: .browser("chrome-bookmarks"), title: "Chrome", detail: "", state: .on),
            .init(id: .app("notes"), title: "Apple Notes", detail: "", state: .on),
        ]
        let snapshots = SetupProgress.snapshots(rows, facts: SetupFacts())
        let finished: [FoundItemID: Date] = [.browser("chrome-bookmarks"): now, .app("notes"): now.addingTimeInterval(-600)]
        XCTAssertEqual(SetupProgress.arrival(snapshots, finishedAt: finished, since: now.addingTimeInterval(-60))?.id,
                       .browser("chrome-bookmarks"))
        XCTAssertNil(SetupProgress.arrival(snapshots, finishedAt: finished, since: now.addingTimeInterval(1)))
    }

    func testWhatKeepsUpIsTheSourcesOwnAnswer() {
        let apps = ["notes": AppSourceDriver(start: { nil }, stop: {}, isOn: { true }, keepsUp: false)]
        XCTAssertTrue(SetupProgress.keepsUp(.browser("chrome-bookmarks"), apps: apps))
        XCTAssertFalse(SetupProgress.keepsUp(.app("notes"), apps: apps))
        XCTAssertFalse(SetupProgress.keepsUp(.dropped("d1"), apps: apps))
    }
}
