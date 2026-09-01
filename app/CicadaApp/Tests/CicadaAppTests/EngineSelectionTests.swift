import XCTest
@testable import CicadaApp

/// G74(a) — the Claude card can be made the Sleep engine, and the Sleep page
/// names whichever engine actually ran.
@MainActor
final class EngineSelectionTests: XCTestCase {

    func testConnectionDecodesUseForSleep() throws {
        let json = #"{"id":"claude-plan","label":"Claude plan","kind":"subscription","useForSleep":true}"#
        let c = try JSONDecoder().decode(ConnectionStatus.self, from: Data(json.utf8))
        XCTAssertTrue(c.useForSleep)
    }

    /// An older backend omits the field; the card must still decode and simply
    /// read as "not the engine".
    func testConnectionDecodesWithoutUseForSleep() throws {
        let json = #"{"id":"claude-plan","label":"Claude plan","kind":"subscription"}"#
        let c = try JSONDecoder().decode(ConnectionStatus.self, from: Data(json.utf8))
        XCTAssertFalse(c.useForSleep)
    }

    /// Only a connected Claude plan can be the Sleep engine — the rung does
    /// not exist for anything else.
    func testOnlyAConnectedClaudePlanOffersTheToggle() {
        func make(_ id: String, connected: Bool) -> ConnectionStatus {
            ConnectionStatus(id: id, label: id, kind: "subscription", available: true,
                             connected: connected, plan: "max", planLabel: nil, tier: nil,
                             account: nil, priceUsdMonth: nil, priceNote: nil,
                             billing: "subscription", engineRole: nil, detail: nil,
                             how: nil, powers: [], useForSleep: false, login: nil)
        }
        XCTAssertTrue(make("claude-plan", connected: true).showsSleepEngineToggle)
        XCTAssertFalse(make("claude-plan", connected: false).showsSleepEngineToggle)
        XCTAssertFalse(make("chatgpt-plan", connected: true).showsSleepEngineToggle)
        XCTAssertFalse(make("byok-openai", connected: true).showsSleepEngineToggle)
    }

    /// The copy has to say all three honest things: what it costs, who starts
    /// it, and what a throttle does.
    func testTheEngineExplainerIsHonestAboutCostTriggerAndThrottle() {
        let text = Copy.sleepEngineExplainer.lowercased()
        XCTAssertTrue(text.contains("plan"), "must say it spends plan quota")
        XCTAssertFalse(text.contains("free"), "plan quota is not 'free'")
        XCTAssertTrue(text.contains("you start") || text.contains("you run"),
                      "must say it is user-triggered")
        XCTAssertTrue(text.contains("throttl"), "must say what happens on a throttle")
    }

    func testEngineLabelsAreHumanReadable() {
        XCTAssertEqual(Copy.engineLabel("claude-cli"), "Claude Code (your plan)")
        XCTAssertEqual(Copy.engineLabel("ollama"), "Ollama (on this Mac)")
        XCTAssertEqual(Copy.engineLabel("litellm"), "API key")
        XCTAssertEqual(Copy.engineLabel("something-new"), "something-new")
    }

    func testSleepStatusDecodesTheEngine() throws {
        let json = #"{"status":"idle","lastEngine":"claude-cli","engineDetail":"Signed in."}"#
        let s = try JSONDecoder().decode(SleepStatusResponse.self, from: Data(json.utf8))
        XCTAssertEqual(s.lastEngine, "claude-cli")
        XCTAssertEqual(s.engineDetail, "Signed in.")
    }

    func testSleepStatusDecodesWithoutTheEngine() throws {
        let s = try JSONDecoder().decode(SleepStatusResponse.self,
                                         from: Data(#"{"status":"idle"}"#.utf8))
        XCTAssertNil(s.lastEngine)
    }

    func testTheMutationCallsTheRightEndpoint() async {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: api)
        _ = await store.perform(SetUseForSleep(id: "claude-plan", on: true))
        XCTAssertEqual(api.writes, ["setUseForSleep:claude-plan:true"])
    }
}
