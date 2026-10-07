import XCTest
@testable import CicadaApp

final class CursorIntegrationTests: XCTestCase {
    func testCapabilityStatusSurvivesDecodeWithoutChangingMCPState() throws {
        let data = Data(#"{"id":"cursor","recall":"on","autosave":"n/a","autorecall":"off","capabilities":{"startup":"documented","capture":"unsupported","verification":"synthetic","surface":"local-ide"}}"#.utf8)
        let row = try JSONDecoder().decode(AgentWiring.self, from: data)
        XCTAssertEqual(row.recall, "on")
        XCTAssertEqual(row.autorecall, "off")
        let encoded = try JSONSerialization.jsonObject(with: JSONEncoder().encode(row)) as! [String: Any]
        XCTAssertEqual((encoded["capabilities"] as? [String: String])?["capture"], "unsupported")
    }

    func testStartupStepIsSeparateFromOpenCursorAndConfirm() {
        let action = AgentWiringStep(step: "autorecall", display: "merge startup hook", argv: [], touches: ["~/.cursor/hooks.json"])
        let row = AgentWiring(id: "cursor", installed: true, binary: nil, recall: "on", autosave: "n/a",
                              connect: [], detail: nil, autorecall: "off", autorecallOn: [action],
                              capabilities: ["startup": "documented", "capture": "unsupported"])
        let steps = AgentSteps.steps(for: AgentCatalog.entry(for: "cursor")!, setups: [:], wiring: row,
                                    live: nil, remoteReady: false)
        XCTAssertEqual(steps.count, 3)
        XCTAssertEqual(steps.first?.actions, [.openCursor])
        XCTAssertTrue(steps.contains { $0.actions == [.autoRecall([action])] })
        let startup = steps.first { $0.actions == [.autoRecall([action])] }
        XCTAssertFalse(startup?.detail.contains("mention") == true, "startup only must not promise per-prompt recall")
        XCTAssertFalse(AutoRecall.detail(row).contains("mention"))
        XCTAssertTrue(steps.last?.isConfirm == true)
        XCTAssertNotNil(AgentSteps.honesty(for: AgentCatalog.entry(for: "cursor")!))
    }

    func testCheckoutStartupRegistryAllowsOnlyItsPinnedCommand() {
        let root = "/synthetic/cicada"
        let runtime = CicadaRuntime.developer(codeRoot: URL(fileURLWithPath: root))
        let command = "'\(root)/api/.venv/bin/python' '\(root)/api/hooks/cursor.py'"
        let argv = [runtime.pythonPath, root + "/api/hooks/cursor_registry.py", "install", "--settings",
                    NSHomeDirectory() + "/.cursor/hooks.json", "--command", command]
        XCTAssertTrue(AgentConnectPolicy.isAllowed(argv, runtime: runtime, binaries: []))
        XCTAssertFalse(AgentConnectPolicy.isAllowed(argv + ["--event", "stop"], runtime: runtime, binaries: []))
        var injected = argv; injected[6] += "; touch /synthetic/unsafe"
        XCTAssertFalse(AgentConnectPolicy.isAllowed(injected, runtime: runtime, binaries: []))
        var project = argv; project[4] = "/synthetic/project/.cursor/hooks.json"
        XCTAssertFalse(AgentConnectPolicy.isAllowed(project, runtime: runtime, binaries: []))
    }

    func testReleaseUsesStableLauncherOnlyAndUninstallIsScoped() {
        let runtime = CicadaRuntime(distribution: .release, bundlePath: "/synthetic/Cicada.app",
            codeRoot: URL(fileURLWithPath: "/synthetic/Cicada.app/Contents/Resources/backend/app"),
            cicadaHome: URL(fileURLWithPath: "/synthetic/cicada-home"), port: 49178, memoryRootDefault: "/synthetic/bank")
        let prefix = ["/synthetic/cicada-home/bin/cicada-hook", "cursor_registry"]
        let settings = NSHomeDirectory() + "/.cursor/hooks.json"
        let command = "'/synthetic/cicada-home/bin/cicada-hook' cursor"
        XCTAssertTrue(AgentConnectPolicy.isAllowed(prefix + ["install", "--settings", settings, "--command", command],
                                                  runtime: runtime, binaries: []))
        XCTAssertTrue(AgentConnectPolicy.isAllowed(prefix + ["uninstall", "--settings", settings], runtime: runtime, binaries: []))
        XCTAssertFalse(AgentConnectPolicy.isAllowed(prefix + ["uninstall", "--settings", settings, "--all"], runtime: runtime, binaries: []))
    }
}
