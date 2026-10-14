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
        // Capture-everywhere: Cursor's own hooks save its chats, so no "no automatic save" line.
        XCTAssertNil(AgentSteps.honesty(for: AgentCatalog.entry(for: "cursor")!))
    }

    func testSavingChatsIsItsOwnStepWhileTheCaptureHooksAreOff() {
        let save = AgentWiringStep(step: "hook", display: "merge capture hooks", argv: [], touches: ["~/.cursor/hooks.json"])
        func row(_ autosave: String, _ connect: [AgentWiringStep]) -> AgentWiring {
            AgentWiring(id: "cursor", installed: true, binary: nil, recall: "on", autosave: autosave,
                        connect: connect, detail: nil, autorecall: "on", autorecallOn: [],
                        capabilities: ["startup": "documented", "capture": "documented"])
        }
        func steps(_ wiring: AgentWiring) -> [AgentStep] {
            AgentSteps.steps(for: AgentCatalog.entry(for: "cursor")!, setups: [:], wiring: wiring, live: nil,
                             remoteReady: false)
        }
        let off = steps(row("off", [save]))
        XCTAssertEqual(off.map(\.title), ["Open in Cursor", Copy.agentStepSaveChats, "Confirm"])
        XCTAssertEqual(off[1].actions, [.connectForMe([save])])
        XCTAssertEqual(steps(row("on", [])).map(\.title), ["Open in Cursor", "Confirm"])
    }

    func testCaptureSwitchArgvIsPinnedAndScoped() {
        let root = "/synthetic/cicada"
        let runtime = CicadaRuntime.developer(codeRoot: URL(fileURLWithPath: root))
        let prefix = [runtime.pythonPath, root + "/api/hooks/cursor_registry.py"]
        let settings = NSHomeDirectory() + "/.cursor/hooks.json"
        let command = "'\(root)/api/.venv/bin/python' '\(root)/api/hooks/cursor.py'"
        let install = prefix + ["install", "--settings", settings, "--command", command]
        XCTAssertTrue(AgentConnectPolicy.isAllowed(install + ["--hook", "capture"], runtime: runtime, binaries: []))
        XCTAssertFalse(AgentConnectPolicy.isAllowed(install + ["--hook", "stop"], runtime: runtime, binaries: []))
        XCTAssertFalse(AgentConnectPolicy.isAllowed(install + ["--hook", "capture", "--hook", "startup"],
                                                   runtime: runtime, binaries: []))
        for group in ["startup", "capture"] {
            XCTAssertTrue(AgentConnectPolicy.isAllowed(prefix + ["uninstall", "--settings", settings, "--hook", group],
                                                      runtime: runtime, binaries: []), group)
        }
        XCTAssertFalse(AgentConnectPolicy.isAllowed(prefix + ["uninstall", "--settings", settings, "--hook", "all"],
                                                   runtime: runtime, binaries: []))
        XCTAssertFalse(AgentConnectPolicy.isAllowed(prefix + ["uninstall", "--settings", "/synthetic/project/.cursor/hooks.json",
                                                              "--hook", "capture"], runtime: runtime, binaries: []))
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
