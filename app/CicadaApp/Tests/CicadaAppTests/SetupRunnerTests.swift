import XCTest
@testable import CicadaApp

@MainActor
final class FakeSetupEffects: SetupEffects {
    var calls: [String] = []
    var ownerFails = false
    var demoFails = false
    var results: [FoundItemID: FoundTurnOnResult] = [:]

    func saveOwner(_ name: String) async throws {
        calls.append("saveOwner:\(name)")
        if ownerFails { throw APIError.serverUnreachable }
    }
    func markOnboarded() { calls.append("markOnboarded") }
    func recordGettingStarted(_ ids: [FoundItemID]) { calls.append("record:" + ids.map(\.key).joined(separator: ",")) }
    func armAppearanceTip() { calls.append("armTip") }
    func showHome() { calls.append("showHome") }
    func close() { calls.append("close") }
    func createDemoBank() async throws {
        calls.append("createDemoBank")
        if demoFails { throw APIError.serverUnreachable }
    }
    func turnOn(_ id: FoundItemID) async -> FoundTurnOnResult {
        calls.append("turnOn:\(id.key)")
        if let gate { await gate() }
        return results[id] ?? .on(nil)
    }
    func settle(_ id: FoundItemID) { calls.append("settle:\(id.key)") }
    /// Awaited inside `turnOn` when set, so a test can hold a run open (the untick race below).
    var gate: (() async -> Void)?
    func turnOff(_ id: FoundItemID) async { calls.append("turnOff:\(id.key)") }
    func forgetRecord(_ id: FoundItemID) { calls.append("forget:\(id.key)") }
    func requestTour() { calls.append("offerTour") }
}

/// Track I part b (design §4.1.7, R-IB14) — what Start does, in order, and
/// which failures stop it.
@MainActor
final class SetupRunnerTests: XCTestCase {
    func testAFailedOwnerSaveRunsNothingAfterIt() async {
        let fx = FakeSetupEffects()
        fx.ownerFails = true
        let runner = SetupRunner()
        await runner.run(OnboardingFlow.beginSteps(name: "Ada") + OnboardingFlow.finishSteps(recorded: [.agent("codex")]),
                         effects: fx)
        XCTAssertEqual(fx.calls, ["saveOwner:Ada"], "the observer every later write carries (G117 R1)")
        guard case .failed = runner.phase else { return XCTFail("\(runner.phase)") }
        XCTAssertTrue(runner.rows.isEmpty)
    }

    func testAFailureStaysOnItsRow() async {
        let fx = FakeSetupEffects()
        fx.results = [.agent("codex"): .failed(Copy.foundInvalidSettings), .agent("claude-code"): .refused(["claude mcp add …"])]
        let runner = SetupRunner()
        for id in [FoundItemID.agent("codex"), .agent("claude-code"), .browser("chrome-bookmarks")] {
            await runner.start(id, effects: fx)
        }
        XCTAssertEqual(runner.rows[.agent("codex")], .failed(Copy.foundInvalidSettings))
        XCTAssertNil(runner.rows[.agent("claude-code")])
        XCTAssertEqual(runner.refused[.agent("claude-code")], ["claude mcp add …"])
        XCTAssertEqual(runner.rows[.browser("chrome-bookmarks")], .on, "a row's failure is never global (§4.1.7 item 6)")
    }

    func testTheDemoMarksOnlyAfterTheBankExists() async {
        let failing = FakeSetupEffects()
        failing.demoFails = true
        await SetupRunner().run(SetupRunner.demoPlan, effects: failing)
        XCTAssertEqual(failing.calls, ["createDemoBank"])
        let ok = FakeSetupEffects()
        await SetupRunner().run(SetupRunner.demoPlan, effects: ok)
        XCTAssertEqual(ok.calls, ["createDemoBank", "markOnboarded", "showHome"])
    }

    func testCursorIsSettledOnceItsOwnConfirmIsOpen() async {
        let fx = FakeSetupEffects()
        fx.results = [.agent("cursor"): .openedApp]
        let runner = SetupRunner()
        await runner.turnOn(.agent("cursor"), effects: fx)
        XCTAssertEqual(runner.rows[.agent("cursor")], .on)
        XCTAssertEqual(fx.calls, ["turnOn:agent:cursor", "settle:agent:cursor"])
    }

    /// The owner: "start syncing as soon as connected, even in onboarding. do not wait for continue."
    func testATickRecordsItsRowAndRunsItAtOnce() async {
        let fx = FakeSetupEffects()
        fx.results = [.app("calendar-local"): .on("312 events")]
        let runner = SetupRunner()
        await runner.start(.app("calendar-local"), effects: fx)
        XCTAssertEqual(fx.calls, ["record:app:calendar-local", "turnOn:app:calendar-local"])
        XCTAssertEqual(runner.rows[.app("calendar-local")], .on)
        XCTAssertEqual(runner.detail[.app("calendar-local")], "312 events")
        XCTAssertNotNil(runner.finishedAt[.app("calendar-local")])
        XCTAssertFalse(fx.calls.contains("armTip"), "only a finished setup arms Make it yours (R-HO15)")
    }

    func testADroppedExportRunsWithItsTitleAndMarkButIsNeverRecorded() async {
        let fx = FakeSetupEffects()
        let runner = SetupRunner()
        await runner.start(.dropped("d1"), title: "ChatGPT history", origin: "chatgpt-export", effects: fx)
        XCTAssertEqual(runner.titles[.dropped("d1")], "ChatGPT history")
        XCTAssertEqual(runner.origins[.dropped("d1")], "chatgpt-export")
        XCTAssertEqual(fx.calls, ["record:dropped:d1", "turnOn:dropped:d1"],
                       "the record call is made; `GettingStartedState.record` itself skips drops (R-IB17)")
    }

    func testAnUntickTurnsOffForgetsTheRowAndDropsItFromTheRecord() async {
        let fx = FakeSetupEffects()
        let runner = SetupRunner()
        await runner.start(.browser("chrome-bookmarks"), effects: fx)
        await runner.stop(.browser("chrome-bookmarks"), effects: fx)
        XCTAssertNil(runner.rows[.browser("chrome-bookmarks")])
        XCTAssertEqual(Array(fx.calls.suffix(2)), ["turnOff:browser:chrome-bookmarks", "forget:browser:chrome-bookmarks"])
    }

    /// R-OB8 — an untick while the read is in flight cancels it (`BrowserWatcher.disable` → `cancel`), and the
    /// cancelled run then answers `.on(Copy.syncStopped)`. That late answer must not re-tick the row the person just
    /// unticked: a row's run carries a generation, and `stop` retires it.
    func testAnUntickDuringARunIsNotUndoneByTheRunsLateAnswer() async {
        let fx = FakeSetupEffects()
        var release: CheckedContinuation<Void, Never>?
        fx.gate = { await withCheckedContinuation { release = $0 } }
        fx.results = [.browser("chrome-bookmarks"): .on(Copy.syncStopped)]
        let runner = SetupRunner()
        let run = Task { await runner.start(.browser("chrome-bookmarks"), effects: fx) }
        while release == nil { await Task.yield() }
        XCTAssertEqual(runner.rows[.browser("chrome-bookmarks")], .working(Copy.foundSavingBookmarks))
        await runner.stop(.browser("chrome-bookmarks"), effects: fx)
        release?.resume()
        await run.value
        XCTAssertNil(runner.rows[.browser("chrome-bookmarks")], "the stopped run's answer lands nowhere")
        XCTAssertNil(runner.finishedAt[.browser("chrome-bookmarks")])
    }

    func testFinishingOffersTheTourOnceAndLandsOnHome() async {
        let fx = FakeSetupEffects()
        await SetupRunner().run(OnboardingFlow.finishSteps(recorded: [.agent("codex")]), effects: fx)
        XCTAssertEqual(fx.calls, ["markOnboarded", "record:agent:codex", "armTip", "offerTour", "showHome"])
    }
}
