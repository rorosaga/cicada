import XCTest
@testable import CicadaApp

/// Track I part b — the one turn-on (extracted from `OnThisMacStrip`, part a
/// T7) that the `+` strip, the Welcome's Start and Getting started share.
@MainActor
final class FoundTurnOnTests: XCTestCase {
    private func wiring() -> AgentWiringResponse {
        AgentWiringResponse(agents: [AgentWiring(id: "codex", installed: true, binary: "/bin/codex", recall: "off",
                                                 autosave: "off",
                                                 connect: [AgentWiringStep(step: "mcp", display: "d0", argv: ["a"], touches: [])],
                                                 detail: nil)],
                            python: "/R/api/.venv/bin/python", repo: "/R", memory: "/M")
    }

    private func deps(wiring: AgentWiringResponse? = nil, connect: AgentConnectOutcome = .done,
                      sync: Result<String, Error> = .success("412 bookmarks saved"),
                      readiness: FoundItem.Readiness? = .ready,
                      opened: @escaping (URL) -> Void = { _ in }, drop: IntakeOutcome? = nil) -> FoundTurnOnDeps {
        FoundTurnOnDeps(wiring: { wiring }, installRoot: URL(fileURLWithPath: "/R"),
                        connect: { _, _, _ in connect }, syncBrowser: { _ in try sync.get() },
                        readiness: { _ in readiness }, open: opened, commitDrop: { _ in drop }, refresh: {})
    }

    func testAnAgentRunsItsStepsAndReportsOn() async {
        let r = await FoundTurnOn.run(.agent("codex"), deps: deps(wiring: wiring()))
        XCTAssertEqual(r, .on(nil))
    }

    func testARefusalHandsBackTheLinesAndAnExitThreeIsItsSentence() async {
        let refused = await FoundTurnOn.run(.agent("codex"), deps: deps(wiring: wiring(), connect: .refused(["d0"])))
        XCTAssertEqual(refused, .refused(["d0"]))
        let invalid = await FoundTurnOn.run(.agent("codex"),
                                            deps: deps(wiring: wiring(), connect: .failed(Copy.foundInvalidSettings)))
        XCTAssertEqual(invalid, .failed(Copy.foundInvalidSettings))
    }

    func testNoWiringMeansTheBackendIsDownNotThatTheAgentIsOff() async {
        let r = await FoundTurnOn.run(.agent("codex"), deps: deps(wiring: nil))
        XCTAssertEqual(r, .failed(Copy.foundBackendDown))
    }

    func testABlockedBrowserOpensFullDiskAccessAndReadsNothing() async {
        var opened: [URL] = []
        let r = await FoundTurnOn.run(.browser("safari-bookmarks"),
                                      deps: deps(readiness: .needsPermission, opened: { opened.append($0) }))
        XCTAssertEqual(r, .needsPermission)
        XCTAssertEqual(opened, [BrowserFileError.fullDiskAccessURL])
    }

    func testABrowserSyncReturnsItsOwnLine() async {
        let r = await FoundTurnOn.run(.browser("chrome-bookmarks"), deps: deps())
        XCTAssertEqual(r, .on("412 bookmarks saved"))
    }

    func testCursorOpensItsDeepLinkAndClaudeDesktopFinishesInSettings() async {
        var opened: [URL] = []
        let cursor = await FoundTurnOn.run(.agent("cursor"), deps: deps(wiring: wiring(), opened: { opened.append($0) }))
        XCTAssertEqual(cursor, .openedApp)
        XCTAssertEqual(opened.first?.scheme, "cursor")
        let desktop = await FoundTurnOn.run(.agent("claude-desktop"), deps: deps())
        XCTAssertEqual(desktop, .finishInSettings(.agents))
    }

    func testADroppedExportIsCommittedAndSaysWhatCameIn() async {
        var outcome = IntakeOutcome(vendor: "chatgpt", origin: "chatgpt-export")
        outcome.created = 3
        let r = await FoundTurnOn.run(.dropped("x"), deps: deps(drop: outcome))
        XCTAssertEqual(r, .on(IntakeSummary.headline(outcome)))
    }
}
