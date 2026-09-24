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

    // MARK: - R-AG12 — the OpenRouter card is `byok`, told apart by `selected`

    func testOpenRouterWritesByokWithItsModelAndIsSelectedByItsCard() throws {
        let card = SleepEngineCandidate(id: "openrouter", label: "OpenRouter", available: true, connected: true,
                                        models: ["openrouter/~openai/gpt-mini-latest"], detail: nil, mode: "byok")
        XCTAssertEqual(EngineWrite.choosing(card, current: "byok"),
                       EngineWrite(mode: "byok", model: "openrouter/~openai/gpt-mini-latest"))
        XCTAssertNil(EngineWrite.choosing(card, current: "openrouter"), "tapping the chosen card writes nothing")
        let signedOut = SleepEngineCandidate(id: "openrouter", label: "OpenRouter", available: true, connected: false,
                                             models: [], detail: nil, mode: "byok")
        XCTAssertFalse(EngineOption.isSelectable(signedOut, selectedMode: "byok"))
        XCTAssertEqual(EngineWrite.mode(of: card), "byok")
        XCTAssertEqual(EngineWrite.mode(of: SleepEngineCandidate(id: "local", label: "Ollama", available: true,
                                                                  connected: true, models: [], detail: nil)), "local")
    }

    /// Every sleep-engine write outside `EngineWrite` would PUT the card id; the two that used to are pinned here.
    func testNoWriteSiteSendsACardIdAsTheMode() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp")
        for file in ["Views/Settings/EngineCard.swift", "Support/LiveSetupEffects.swift"] {
            let text = try String(contentsOf: root.appendingPathComponent(file), encoding: .utf8)
            XCTAssertFalse(text.contains("mode: candidate.id") || text.contains("mode: candidateId,"), file)
        }
    }

    func testAnOlderPayloadWithoutTheNewFieldsDecodes() throws {
        let json = #"{"mode":"byok","model":"gpt-5.4-mini","disambiguationModel":"gpt-5.4-nano","source":"default","candidates":[{"id":"byok","label":"API key","available":true,"connected":true,"models":[],"detail":null}]}"#
        let r = try JSONDecoder().decode(SleepEngineResponse.self, from: Data(json.utf8))
        XCTAssertEqual(r.selected, "byok")
        XCTAssertEqual(r.providers, [])
        XCTAssertNil(r.candidates[0].mode)
    }

    /// R-AG11: the new fields decode, and one malformed provider row empties the list rather than
    /// failing the card.
    func testTheNewFieldsDecodeAndAMalformedProviderListIsDropped() throws {
        let json = #"{"mode":"byok","model":"openrouter/~openai/gpt-mini-latest","disambiguationModel":"x","source":"prefs","selected":"openrouter","provider":"openrouter","providers":[{"id":"groq","label":"Groq","connectionId":"byok-groq","hasKey":true,"defaultModel":"groq/openai/gpt-oss-120b","keyUrl":"https://console.groq.com/keys"}],"candidates":[{"id":"openrouter","label":"OpenRouter","available":true,"connected":true,"models":["openrouter/~openai/gpt-mini-latest"],"detail":null,"mode":"byok"}]}"#
        let r = try JSONDecoder().decode(SleepEngineResponse.self, from: Data(json.utf8))
        XCTAssertEqual(r.selected, "openrouter")
        XCTAssertEqual(r.provider, "openrouter")
        XCTAssertEqual(r.providers.map(\.id), ["groq"])
        XCTAssertTrue(r.providers[0].hasKey)
        XCTAssertEqual(r.candidates[0].mode, "byok")
        let bad = json.replacingOccurrences(of: #""keyUrl":"https://console.groq.com/keys""#, with: #""keyUrl":7"#)
        let r2 = try JSONDecoder().decode(SleepEngineResponse.self, from: Data(bad.utf8))
        XCTAssertEqual(r2.providers, [])
        XCTAssertEqual(r2.selected, "openrouter")
    }

    /// The Sleep page's quick menu highlights the selected CARD, so choosing OpenRouter never lights
    /// the API-key row (both are `byok`).
    func testTheQuickMenuMarksTheSelectedCardNotTheMode() {
        let response = SleepEngineResponse(
            mode: "byok", model: "openrouter/~openai/gpt-mini-latest", disambiguationModel: "x", source: "prefs",
            candidates: [
                SleepEngineCandidate(id: "openrouter", label: "OpenRouter", available: true, connected: true,
                                     models: ["openrouter/~openai/gpt-mini-latest"], detail: nil, mode: "byok"),
                SleepEngineCandidate(id: "byok", label: "API key", available: true, connected: true,
                                     models: ["anthropic/claude-haiku-4-5"], detail: nil),
            ],
            preview: nil, selected: "openrouter")
        let rows = EngineQuickMenuModel.from(response).rows
        XCTAssertEqual(rows.filter(\.isSelected).map(\.id), ["openrouter"])
        XCTAssertEqual(SleepEngineResponse(mode: "local", model: "m", disambiguationModel: "m", source: "prefs",
                                           candidates: [], preview: nil).selected, "local")
    }
}
