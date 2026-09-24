import XCTest
@testable import CicadaApp

/// C8 / R-AG2 / R-AG3 / R-AG19 — what each agent's numbered steps say and offer, as a pure table.
final class AgentStepsTests: XCTestCase {
    private let now = ISO8601DateFormatter().date(from: "2026-09-24T12:00:00Z")!
    private let en = Locale(identifier: "en_US")

    private func prompt(_ harness: String, text: String = "Please connect Cicada…") throws -> AgentSetupPrompt {
        try JSONDecoder().decode(AgentSetupPrompt.self, from: Data("""
        {"harness":"\(harness)","kind":"prompt","title":"t","prompt":"\(text)","argv":[],"display":[]}
        """.utf8))
    }

    private func remote(_ harness: String) throws -> AgentSetupPrompt {
        try JSONDecoder().decode(AgentSetupPrompt.self, from: Data("""
        {"harness":"\(harness)","kind":"remote","title":"t","display":["Reach it.","Create a link."],"note":"n"}
        """.utf8))
    }

    private func steps(_ id: String, setups: [String: AgentSetupPrompt] = [:], wiring: AgentWiring? = nil,
                       live: AgentLiveRow? = nil, remoteReady: Bool = false) -> [AgentStep] {
        AgentSteps.steps(for: AgentCatalog.entry(for: id)!, setups: setups, wiring: wiring, live: live,
                         remoteReady: remoteReady, now: now, locale: en)
    }

    func testAPromptAgentIsCopyThenConfirm() throws {
        let s = steps("opencode", setups: ["opencode": try prompt("opencode")])
        XCTAssertEqual(s.map(\.title), ["Copy and send this to OpenCode", "Confirm"])
        XCTAssertEqual(s[0].detail, "OpenCode adds Cicada to its own settings and changes nothing else.")
        XCTAssertEqual(s[0].actions, [.copy("Please connect Cicada…")])
        XCTAssertEqual(s[0].snippet, "Please connect Cicada…")
        XCTAssertEqual(s[1].trailing, "Waiting for OpenCode…")
        XCTAssertFalse(s[1].done)
    }

    func testClaudeCodeOffersConnectForMeWhenTheWiringDoes() throws {
        let step = AgentWiringStep(step: "mcp", display: "claude mcp add …", argv: ["/x/claude", "mcp"], touches: [])
        let wiring = AgentWiring(id: "claude-code", installed: true, binary: "/x/claude", recall: "off",
                                 autosave: "off", connect: [step], detail: nil)
        let s = steps("claude-code", setups: ["claude-code": try prompt("claude-code")], wiring: wiring)
        XCTAssertEqual(s[0].detail, "Claude Code runs the setup itself and asks you to approve its commands.")
        XCTAssertEqual(s[0].actions, [.connectForMe([step]), .copy("Please connect Cicada…")])
    }

    func testBeforeTheSetupArrivesTheStepSaysSoAndOffersNothing() {
        let s = steps("hermes")
        XCTAssertEqual(s[0].detail, Copy.agentStepPreparing)
        XCTAssertEqual(s[0].actions, [])
    }

    func testCursorIsOneClickThenConfirm() {
        XCTAssertEqual(steps("cursor").map(\.title), ["Open in Cursor", "Confirm"])
        XCTAssertEqual(steps("cursor")[0].actions, [.openCursor])
    }

    func testClaudeIsTheAppFirstThenClaudeAiAsAdvanced() throws {
        let s = steps("claude", setups: ["claude": try remote("claude")])
        XCTAssertEqual(s.map(\.title), ["Set up the Claude app on this Mac", "Use it on claude.ai and your phone too", "Confirm"])
        XCTAssertEqual(s[0].actions, [.setUpClaude])
        XCTAssertTrue(s[1].advanced)
        XCTAssertEqual(s[1].detail, "Create a link.")
        XCTAssertEqual(s[1].actions, [.openFromAnywhere])
        XCTAssertEqual(steps("claude", setups: ["claude": try remote("claude")], remoteReady: true)[1].actions,
                       [.createLink(.claude, enabled: true)])
    }

    func testACloudAgentReachesThenLinksThenConfirms() throws {
        let s = steps("grok", setups: ["grok": try remote("grok")])
        XCTAssertEqual(s.map(\.title), ["Let Grok reach this Mac", "Create a link for Grok", "Confirm"])
        XCTAssertEqual(s.map(\.detail).prefix(2), ["Reach it.", "Create a link."])
        XCTAssertTrue(s[0].advanced && !s[0].done)
        XCTAssertEqual(s[1].actions, [.createLink(.grok, enabled: false)])
        let ready = steps("grok", setups: ["grok": try remote("grok")], remoteReady: true)
        XCTAssertTrue(ready[0].done)
        XCTAssertEqual(ready[1].actions, [.createLink(.grok, enabled: true)])
    }

    func testTheConfirmLineReadsTheLiveRowInWords() {
        func line(_ row: AgentLiveRow?) -> String { AgentSteps.confirmLine(live: row, name: "Codex", now: now, locale: en) }
        XCTAssertEqual(line(nil), "Waiting for Codex…")
        XCTAssertEqual(line(AgentLiveRow(id: "codex", connected: true, lastSeenAt: "2026-09-24T11:59:40Z", via: "mcp")),
                       "Connected just now")
        XCTAssertEqual(line(AgentLiveRow(id: "codex", connected: true, lastSeenAt: "2026-09-24T09:00:00Z", via: "mcp")),
                       "Connected 3 hours ago")
        XCTAssertEqual(line(AgentLiveRow(id: "codex", connected: true, lastSeenAt: nil, via: "config")), "Connected")
        XCTAssertEqual(line(AgentLiveRow(id: "codex", connected: false, lastSeenAt: "2026-09-20T09:00:00Z", via: nil)),
                       "Waiting for Codex…")
    }

    func testOnlyTheHookedAgentsSaveOnTheirOwn() {
        XCTAssertNil(AgentSteps.honesty(for: AgentCatalog.entry(for: "claude-code")!))
        XCTAssertNil(AgentSteps.honesty(for: AgentCatalog.entry(for: "codex")!))
        XCTAssertEqual(AgentSteps.honesty(for: AgentCatalog.entry(for: "grok")!), Copy.agentNoAutosave)
        XCTAssertEqual(Copy.agentNoAutosave, "Saves when you or it asks — it has no automatic save.")
    }

    func testTheSummaryCountsWhatIsConnected() {
        XCTAssertEqual(Copy.agentsConnectedSummary(0), "Connect as many as you like")
        XCTAssertEqual(Copy.agentsConnectedSummary(2), "2 connected · connect as many as you like")
    }
}
