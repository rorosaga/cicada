import XCTest
@testable import CicadaApp

/// G117 round 4 (T-Demo) — which bank is the demo (the server's flag, never the name), the order the way home takes
/// (seam 1 for the bank the server chose), and the ids the tour opens inside the demo, pinned to the generator.
@MainActor
final class DemoModeTests: XCTestCase {
    private func roster(active: String, demoIsDemo: Bool = true) -> BanksResponse {
        BanksResponse(banks: [
            MemoryBank(name: "default", active: active == "default", entityCount: 3, episodeCount: 4, createdAt: "",
                       description: nil, legacy: true),
            MemoryBank(name: "demo", active: active == "demo", entityCount: 80, episodeCount: 70, createdAt: "",
                       description: nil, demo: demoIsDemo),
        ], active: active)
    }

    func testTheDemoFlagDecodesAndAnOlderBackendReadsAsNotTheDemo() throws {
        let flagged = try JSONDecoder().decode(MemoryBank.self, from: Data(#"{"name":"demo","active":true,"demo":true}"#.utf8))
        XCTAssertTrue(flagged.demo)
        XCTAssertTrue(flagged.settingActive(false).demo, "ActivateBank's optimistic copy keeps the flag")
        let older = try JSONDecoder().decode(MemoryBank.self, from: Data(#"{"name":"default"}"#.utf8))
        XCTAssertFalse(older.demo)
    }

    func testTheDemoIsTheServersFlagNeverTheName() {
        XCTAssertTrue(DemoMode.isActive(roster(active: "demo")))
        XCTAssertFalse(DemoMode.isActive(roster(active: "default")))
        XCTAssertFalse(DemoMode.isActive(roster(active: "demo", demoIsDemo: false)), "a real bank called demo")
        XCTAssertFalse(DemoMode.isActive(nil), "unknown is never the demo: no banner flashes on a cold launch")
        XCTAssertEqual(DemoMode.demoBank(in: roster(active: "default")), "demo")
        XCTAssertNil(DemoMode.demoBank(in: roster(active: "default", demoIsDemo: false)))
        // The auto-start's gate: the roster moves before `Store.bank` does (`Store.refresh` awaits `hydrate` between).
        XCTAssertTrue(DemoMode.isShowing(roster(active: "demo"), bank: "demo"))
        XCTAssertFalse(DemoMode.isShowing(roster(active: "demo"), bank: "default"),
                       "the roster says demo but the pages still show the bank being left")
        XCTAssertFalse(DemoMode.isShowing(roster(active: "demo", demoIsDemo: false), bank: "demo"))
    }

    func testLeavingSendsTheHeldAnswerFirstAndOpensOnboardingForTheBankTheServerChose() async {
        var calls: [String] = []
        let home = roster(active: "default")
        let outcome = await DemoMode.leave(DemoMode.ExitEffects(
            flushHeld: { calls.append("flush") },
            leaveDemo: { calls.append("leave"); return home },
            refreshBanks: { calls.append("refresh") },
            resetOnboarding: { calls.append("reset:\($0)") },
            openOnboarding: { calls.append("open") }))
        XCTAssertEqual(outcome, .left("default"))
        XCTAssertEqual(calls, ["flush", "leave", "refresh", "reset:default", "open"],
                       "seam 1 — reset the bank the server landed on, never the demo's, then the one door")
    }

    /// Settings' *Back to your memory* switches back without touching the landing bank's setup flag (final review 2).
    func testBackToYourMemoryLeavesWithoutReopeningSetup() async {
        var calls: [String] = []
        let home = roster(active: "default")
        let outcome = await DemoMode.leave(DemoMode.ExitEffects(
            flushHeld: { calls.append("flush") },
            leaveDemo: { calls.append("leave"); return home },
            refreshBanks: { calls.append("refresh") },
            resetOnboarding: { calls.append("reset:\($0)") },
            openOnboarding: { calls.append("open") }), openSetup: false)
        XCTAssertEqual(outcome, .left("default"))
        XCTAssertEqual(calls, ["flush", "leave", "refresh"], "a set-up bank's flag is never cleared by this door")
    }

    func testAFailedLeaveOpensNothingAndSaysWhy() async {
        struct Refused: LocalizedError { var errorDescription: String? { "The service is not running" } }
        var calls: [String] = []
        let outcome = await DemoMode.leave(DemoMode.ExitEffects(
            flushHeld: { calls.append("flush") },
            leaveDemo: { throw Refused() },
            refreshBanks: { calls.append("refresh") },
            resetOnboarding: { calls.append("reset:\($0)") },
            openOnboarding: { calls.append("open") }))
        XCTAssertEqual(outcome, .failed("The service is not running"))
        XCTAssertEqual(calls, ["flush"])
    }

    func testAServerThatKeepsTheDemoOpenOpensNothing() async {
        var opened = false
        let still = roster(active: "demo")
        let outcome = await DemoMode.leave(DemoMode.ExitEffects(
            flushHeld: {}, leaveDemo: { still }, refreshBanks: {}, resetOnboarding: { _ in },
            openOnboarding: { opened = true }))
        XCTAssertEqual(outcome, .stayed)
        XCTAssertFalse(opened)
    }

    /// `api/tests/fixtures/demo_showcase.json` is the generator's own answer (`test_demo_showcase.py` holds the other
    /// side): rename the showcase person on one side only and this goes red.
    func testTheShowcaseIdsAreTheGenerators() throws {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .deletingLastPathComponent()   // app
            .deletingLastPathComponent()   // repo root
        let file = root.appendingPathComponent("api/tests/fixtures/demo_showcase.json")
        let ids = try JSONDecoder().decode([String: String].self, from: Data(contentsOf: file))
        XCTAssertEqual(ids["person"], DemoShowcase.person)
        XCTAssertEqual(ids["project"], DemoShowcase.project)
    }
}
