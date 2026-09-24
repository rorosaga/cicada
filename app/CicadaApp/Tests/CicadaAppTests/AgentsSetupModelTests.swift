import XCTest
@testable import CicadaApp

/// R-OB13 — F-04's fetches: never blank (a failed fetch keeps the last answer), a pill's setup asked once.
@MainActor
final class AgentsSetupModelTests: XCTestCase {
    func testAFailedFetchKeepsTheLastAnswerAndASetupIsAskedOnce() async throws {
        var wiringAnswers: [AgentWiringResponse?] = [
            AgentWiringResponse(agents: [], python: "/p", repo: "/R", memory: "/M"), nil]
        var asked: [String] = []
        let model = AgentsSetupModel(deps: .init(
            wiring: { wiringAnswers.removeFirst() },
            setup: { harness in asked.append(harness); return nil },
            remote: { nil },
            memoryRoot: { "/M" }))
        await model.load()
        await model.refreshWiring()
        XCTAssertEqual(model.wiring?.repo, "/R", "never blank")
        XCTAssertEqual(model.memoryRoot, "/M")
        let claude = try XCTUnwrap(AgentCatalog.entry(for: "claude"))
        await model.select(claude)
        await model.select(claude)
        XCTAssertEqual(asked, ["claude-desktop", "claude"], "each harness once")
    }
}
