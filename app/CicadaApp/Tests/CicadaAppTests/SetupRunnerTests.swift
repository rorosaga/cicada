import XCTest
@testable import CicadaApp

@MainActor
final class FakeSetupEffects: SetupEffects {
    var calls: [String] = []
    var ownerFails = false
    var engineFails = false
    var demoFails = false
    var results: [FoundItemID: FoundTurnOnResult] = [:]

    func saveOwner(_ name: String) async throws {
        calls.append("saveOwner:\(name)")
        if ownerFails { throw APIError.serverUnreachable }
    }
    func saveEngine(_ candidateId: String) async throws {
        calls.append("saveEngine:\(candidateId)")
        if engineFails { throw APIError.serverUnreachable }
    }
    func markOnboarded() { calls.append("markOnboarded") }
    func recordGettingStarted(_ ids: [FoundItemID]) { calls.append("record:" + ids.map(\.key).joined(separator: ",")) }
    func showHome() { calls.append("showHome") }
    func close() { calls.append("close") }
    func createDemoBank() async throws {
        calls.append("createDemoBank")
        if demoFails { throw APIError.serverUnreachable }
    }
    func turnOn(_ id: FoundItemID) async -> FoundTurnOnResult {
        calls.append("turnOn:\(id.key)")
        return results[id] ?? .on(nil)
    }
    func settle(_ id: FoundItemID) { calls.append("settle:\(id.key)") }
}

/// Track I part b (design §4.1.7, R-IB14) — what Start does, in order, and
/// which failures stop it.
@MainActor
final class SetupRunnerTests: XCTestCase {
    func testAFailedOwnerSaveRunsNothingAfterIt() async {
        let fx = FakeSetupEffects()
        fx.ownerFails = true
        let runner = SetupRunner()
        await runner.run(OnboardingFlow.plan(name: "Ada", pickedEngine: "agent", ticked: [.agent("codex")], mode: .firstRun),
                         effects: fx)
        XCTAssertEqual(fx.calls, ["saveOwner:Ada"], "the observer every later write carries (G117 R1)")
        guard case .failed = runner.phase else { return XCTFail("\(runner.phase)") }
        XCTAssertTrue(runner.rows.isEmpty)
    }

    func testStartRunsInOrderAndReachesHomeBeforeAnyRowRuns() async {
        let fx = FakeSetupEffects()
        let runner = SetupRunner()
        await runner.run(OnboardingFlow.plan(name: "Ada", pickedEngine: "agent",
                                             ticked: [.agent("claude-code"), .browser("chrome-bookmarks")], mode: .firstRun),
                         effects: fx)
        XCTAssertEqual(Array(fx.calls.prefix(5)),
                       ["saveOwner:Ada", "saveEngine:agent", "markOnboarded",
                        "record:agent:claude-code,browser:chrome-bookmarks", "showHome"])
        XCTAssertEqual(Set(fx.calls.dropFirst(5)), ["turnOn:agent:claude-code", "turnOn:browser:chrome-bookmarks"])
        XCTAssertEqual(runner.rows[.agent("claude-code")], .on)
        XCTAssertEqual(runner.phase, .started)
    }

    func testAFailureStaysOnItsRow() async {
        let fx = FakeSetupEffects()
        fx.results = [.agent("codex"): .failed(Copy.foundInvalidSettings), .agent("claude-code"): .refused(["claude mcp add …"])]
        let runner = SetupRunner()
        await runner.run(OnboardingFlow.plan(name: "Ada", pickedEngine: nil,
                                             ticked: [.agent("codex"), .agent("claude-code"), .browser("chrome-bookmarks")],
                                             mode: .firstRun),
                         effects: fx)
        XCTAssertEqual(runner.rows[.agent("codex")], .failed(Copy.foundInvalidSettings))
        XCTAssertNil(runner.rows[.agent("claude-code")])
        XCTAssertEqual(runner.refused[.agent("claude-code")], ["claude mcp add …"])
        XCTAssertEqual(runner.rows[.browser("chrome-bookmarks")], .on)
        XCTAssertEqual(runner.phase, .started, "a row's failure is never global (§4.1.7 item 6)")
    }

    func testAnEngineSaveFailureIsSaidOnHomeNotOnTheWelcome() async {
        let fx = FakeSetupEffects()
        fx.engineFails = true
        let runner = SetupRunner()
        await runner.run(OnboardingFlow.plan(name: "Ada", pickedEngine: "local", ticked: [], mode: .firstRun), effects: fx)
        XCTAssertTrue(fx.calls.contains("showHome"))
        XCTAssertEqual(runner.engineError, Copy.gsEngineFailed)
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
}
