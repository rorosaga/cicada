import XCTest
@testable import CicadaApp

/// Track I T6 (design §4.1.5) — which engine can actually run the NEXT manual
/// read. `.needsChoice` is what makes Read now ask first.
final class EngineReadinessTests: XCTestCase {
    private func candidate(_ id: String, available: Bool = true, connected: Bool, models: [String] = ["m"]) -> SleepEngineCandidate {
        SleepEngineCandidate(id: id, label: id, available: available, connected: connected, models: models, detail: nil)
    }
    private func connection(kind: String, connected: Bool) -> ConnectionStatus {
        ConnectionStatus(id: "k", label: "k", kind: kind, available: true, connected: connected, plan: nil,
                         planLabel: nil, tier: nil, account: nil, priceUsdMonth: nil, priceNote: nil,
                         billing: "usage", engineRole: nil, detail: nil, login: nil)
    }
    private func preview(_ manual: String) -> SleepEnginePreviews {
        SleepEnginePreviews(manual: .init(engine: manual, model: "m", why: "w"),
                            scheduled: .init(engine: "litellm", model: "m", why: "w"))
    }

    func testAKeylessByokNeedsAChoiceEvenThoughItsCandidateSaysConnected() {
        let byok = candidate("byok", connected: true)
        XCTAssertEqual(EngineReadiness.resolve(candidates: [byok], connections: [], preview: preview("litellm")), .needsChoice)
        XCTAssertEqual(EngineReadiness.resolve(candidates: [byok], connections: [connection(kind: "usage", connected: true)],
                                               preview: preview("litellm")), .ready(candidate: "byok"))
    }

    func testThePlanIsReadyOnlyWhenSignedIn() {
        XCTAssertEqual(EngineReadiness.resolve(candidates: [candidate("agent", connected: true)], connections: [],
                                               preview: preview("claude-cli")), .ready(candidate: "agent"))
        XCTAssertEqual(EngineReadiness.resolve(candidates: [candidate("agent", connected: false)], connections: [],
                                               preview: preview("claude-cli")), .needsChoice)
    }

    func testOllamaNeedsAPulledModel() {
        XCTAssertEqual(EngineReadiness.resolve(candidates: [candidate("local", connected: true)], connections: [],
                                               preview: preview("ollama")), .ready(candidate: "local"))
        XCTAssertEqual(EngineReadiness.resolve(candidates: [candidate("local", connected: true, models: [])], connections: [],
                                               preview: preview("ollama")), .needsChoice)
    }

    func testNoPreviewOrAnUnknownEngineNeedsAChoice() {
        XCTAssertEqual(EngineReadiness.resolve(candidates: [], connections: [], preview: nil), .needsChoice)
        XCTAssertEqual(EngineReadiness.resolve(candidates: [], connections: [], preview: preview("mystery")), .needsChoice)
    }
    /// R-AG12 — a key run through OpenRouter belongs to the OpenRouter card everywhere a preview names a card.
    func testALiteLLMRunOnAnOpenRouterModelIsTheOpenRouterCard() {
        XCTAssertEqual(EngineReadiness.candidateId(forEngine: "litellm", model: "openrouter/~openai/gpt-mini-latest"),
                       "openrouter")
        XCTAssertEqual(EngineReadiness.candidateId(forEngine: "litellm", model: "gpt-5.4-mini"), "byok")
        XCTAssertEqual(EngineReadiness.candidateId(forEngine: "litellm"), "byok")
        XCTAssertEqual(EngineOption.candidateId(forEngine: "litellm", model: "openrouter/z-ai/glm-5.2"), "openrouter")
    }
}
