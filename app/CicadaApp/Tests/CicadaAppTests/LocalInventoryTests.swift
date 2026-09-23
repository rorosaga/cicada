import XCTest
@testable import CicadaApp

/// Track I T7 (design §4.1.3) — detect, don't ask. Absent apps have no row;
/// a blocked Safari needs permission; backend-probed agents appear only once the
/// probe answers ("never blank" is the host's "Checking…" line).
@MainActor
final class LocalInventoryTests: XCTestCase {
    private func wiring(_ agents: [AgentWiring]) -> AgentWiringResponse {
        AgentWiringResponse(agents: agents, python: "/R/python", repo: "/R", memory: "/M")
    }
    private func agent(_ id: String, installed: Bool = true, recall: String = "off", autosave: String = "off",
                       steps: Int = 2) -> AgentWiring {
        AgentWiring(id: id, installed: installed, binary: installed ? "/bin/\(id)" : nil, recall: recall, autosave: autosave,
                    connect: (0..<steps).map { AgentWiringStep(step: "s\($0)", display: "d", argv: ["a"], touches: []) },
                    detail: nil)
    }

    func testRowsAppearOnlyForWhatIsHere() {
        let items = LocalInventory.items(from: InventorySnapshot(
            wiring: wiring([agent("claude-code"), agent("codex", installed: false)]),
            installedBundles: [LocalInventory.cursorBundleId],
            browsers: ["chrome-bookmarks": .off, "safari-bookmarks": .absent],
            claudeDesktopHasCicada: nil))
        XCTAssertEqual(items.map(\.id), [.agent("claude-code"), .agent("cursor"), .browser("chrome-bookmarks")])
    }

    func testStatesMapToReadiness() {
        let items = LocalInventory.items(from: InventorySnapshot(
            wiring: wiring([agent("claude-code", recall: "on", autosave: "on", steps: 0),
                            agent("codex", autosave: "invalid", steps: 1)]),
            installedBundles: [LocalInventory.claudeDesktopBundleId],
            browsers: ["chrome-bookmarks": .on, "safari-bookmarks": .blocked],
            claudeDesktopHasCicada: true))
        let byId = Dictionary(uniqueKeysWithValues: items.map { ($0.id, $0.readiness) })
        XCTAssertEqual(byId[.agent("claude-code")], .alreadyOn)
        XCTAssertEqual(byId[.agent("codex")], .failed(Copy.foundInvalidSettings))
        XCTAssertEqual(byId[.agent("claude-desktop")], .alreadyOn)
        XCTAssertEqual(byId[.browser("chrome-bookmarks")], .alreadyOn)
        XCTAssertEqual(byId[.browser("safari-bookmarks")], .needsPermission)
    }

    /// `recall: unknown` (a probe past its 2 s) with nothing to run is a sentence
    /// and a Retry, never a spinner that cannot end.
    func testATimedOutProbeSaysSoInsteadOfSpinning() {
        let items = LocalInventory.items(from: InventorySnapshot(
            wiring: wiring([agent("codex", recall: "unknown", autosave: "on", steps: 0)]),
            installedBundles: [], browsers: [:], claudeDesktopHasCicada: nil))
        XCTAssertEqual(items.first?.readiness, .failed(Copy.foundCouldNotCheck))
    }

    func testNoWiringYetMeansNoAgentRowsNotFalseOnes() {
        let items = LocalInventory.items(from: InventorySnapshot(wiring: nil, installedBundles: [],
                                                                 browsers: [:], claudeDesktopHasCicada: nil))
        XCTAssertTrue(items.isEmpty)
    }

    func testAgentsArePreTickedAndAppsThatOpenElsewhereAreNot() {
        let items = LocalInventory.items(from: InventorySnapshot(
            wiring: wiring([agent("claude-code")]), installedBundles: [LocalInventory.cursorBundleId],
            browsers: [:], claudeDesktopHasCicada: nil))
        XCTAssertEqual(items.filter(FoundPolicy.defaultOn).map(\.id), [.agent("claude-code")])
    }

    func testRefreshReadsTheProbesAgain() async {
        var chrome: BrowserPresence = .off
        let inventory = LocalInventory(probes: LocalInventoryProbes(
            wiring: { nil }, isInstalled: { _ in false }, browserPresence: { $0 == "chrome-bookmarks" ? chrome : .absent },
            claudeDesktopHasCicada: { nil }))
        XCTAssertFalse(inventory.hasChecked, "empty before the first scan means not asked, not nothing here")
        await inventory.refresh()
        XCTAssertTrue(inventory.hasChecked)
        XCTAssertEqual(inventory.items.first?.readiness, .ready)
        chrome = .on
        await inventory.refresh()
        XCTAssertEqual(inventory.items.first?.readiness, .alreadyOn, "a Full Disk Access grant or a Turn on shows on the next scan")
    }
}
