import XCTest
@testable import CicadaApp

/// A login-item seam that records calls and answers what the test says.
final class FakeLoginItem: LoginItemControlling, @unchecked Sendable {
    var current: LoginItemStatus = .notRegistered
    var afterRegister: LoginItemStatus = .enabled
    var registerError: Error?
    private(set) var calls: [String] = []
    func status() -> LoginItemStatus { current }
    func register() throws {
        calls.append("register")
        if let registerError { throw registerError }
        current = afterRegister
    }
    func unregister() throws { calls.append("unregister"); current = .notRegistered }
    func openSystemSettingsLoginItems() { calls.append("settings") }
}

/// Answers `launchctl print` and the install script from a table, recording argv and environment.
final class FakeRunner: AgentProcessRunning, @unchecked Sendable {
    var answers: [String: Int32] = [:]
    private(set) var runs: [(argv: [String], env: [String: String])] = []
    func run(_ argv: [String], environment: [String: String], timeout: Duration) async -> AgentProcessResult {
        runs.append((argv, environment))
        return AgentProcessResult(status: answers[argv.joined(separator: " ")] ?? 0, stderr: "")
    }
}

/// Round-4 D3 (G143) — open at login and the background service, as pure rules plus fakes.
@MainActor
final class BackgroundServicesTests: XCTestCase {
    private let root = URL(fileURLWithPath: "/x/cicada")

    func testTheBackendSpawnsInstallShsCommand() {
        let command = BackendProcess.spawnCommand(installRoot: root)
        XCTAssertEqual(command.executable.path, "/x/cicada/api/.venv/bin/python")
        XCTAssertEqual(command.arguments, ["-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000"])
    }

    func testLoginItemStatesAreHonest() {
        XCTAssertEqual(LoginItemState.derive(status: .enabled, requested: true), .on)
        XCTAssertEqual(LoginItemState.derive(status: .requiresApproval, requested: true), .needsApproval)
        XCTAssertEqual(LoginItemState.derive(status: .notRegistered, requested: false), .off)
        guard case .notKept = LoginItemState.derive(status: .notRegistered, requested: true) else {
            return XCTFail("asked for, not kept: say so (D3)")
        }
        guard case .notKept = LoginItemState.derive(status: .notFound, requested: true) else { return XCTFail() }
        guard case .notKept = LoginItemState.derive(status: .enabled, requested: true, error: "x") else { return XCTFail() }
    }

    func testTurningOnRegistersAndAnUnsignedBuildSaysSo() {
        let control = FakeLoginItem()
        control.afterRegister = .notRegistered          // an ad-hoc build macOS will not keep
        let defaults = UserDefaults(suiteName: "login-\(UUID())")!
        let service = LoginItemService(control: control, defaults: defaults)
        service.setEnabled(true)
        XCTAssertEqual(control.calls, ["register"])
        XCTAssertTrue(defaults.bool(forKey: LoginItemService.requestedKey))
        guard case .notKept = service.state else { return XCTFail("never pretend") }
        XCTAssertTrue(service.state.offersSettings)
    }

    /// R-FA7 — allowed from System Settings while the intent said off: the switch reads on, like the sentence.
    func testALoginItemAllowedElsewhereReadsAsOn() {
        let control = FakeLoginItem()
        control.current = .enabled
        let defaults = UserDefaults(suiteName: "login-\(UUID())")!
        let service = LoginItemService(control: control, defaults: defaults)
        XCTAssertEqual(service.state, .on)
        XCTAssertTrue(service.requested)
        XCTAssertTrue(defaults.bool(forKey: LoginItemService.requestedKey))
        XCTAssertEqual(control.calls, [], "reading the state registers nothing")
    }

    func testASwitchOffInSystemSettingsClearsTheIntent() {
        let control = FakeLoginItem()
        let defaults = UserDefaults(suiteName: "login-\(UUID())")!
        let service = LoginItemService(control: control, defaults: defaults)
        service.setEnabled(true)
        XCTAssertEqual(service.state, .on)
        control.current = .notRegistered                // the person turned it off in System Settings
        service.refresh()
        XCTAssertEqual(service.state, .off)
        XCTAssertFalse(defaults.bool(forKey: LoginItemService.requestedKey))
    }

    func testTheInstallArgvIsPinnedToThisCheckout() {
        XCTAssertEqual(BackendAgentPolicy.installArgv(installRoot: root),
                       ["/bin/bash", "/x/cicada/scripts/install-backend-agent.sh"])
        XCTAssertTrue(BackendAgentPolicy.isAllowed(["/bin/bash", "/x/cicada/scripts/install-backend-agent.sh"], installRoot: root))
        XCTAssertFalse(BackendAgentPolicy.isAllowed(["/bin/bash", "/y/cicada/scripts/install-backend-agent.sh"], installRoot: root))
        XCTAssertFalse(BackendAgentPolicy.isAllowed(["/bin/bash", "/x/cicada/scripts/install-backend-agent.sh", "--x"], installRoot: root))
        XCTAssertFalse(BackendAgentPolicy.isAllowed(["/bin/sh", "/x/cicada/scripts/install-backend-agent.sh"], installRoot: root))
    }

    func testTheInstallEnvironmentIsScrubbedAndNeverCaptured() {
        let env = BackendAgentPolicy.environment(base: ["ANTHROPIC_API_KEY": "k", "HOME": "/h"], installRoot: root,
                                                 memoryRoot: "/m/memory")
        XCTAssertEqual(env["CICADA_CAPTURE"], "off")
        XCTAssertEqual(env["CICADA_REPO"], "/x/cicada")
        XCTAssertEqual(env["CICADA_MEMORY_PATH"], "/m/memory")
        XCTAssertNil(env["ANTHROPIC_API_KEY"])
        XCTAssertTrue(env["PATH"]?.contains("/usr/bin") ?? false)
        XCTAssertEqual(BackendAgentPolicy.environment(base: [:], installRoot: root, memoryRoot: nil)["CICADA_MEMORY_PATH"],
                       "/x/cicada/memory", "no live root: the memory BackendProcess serves (R-FA8)")
    }

    func testTheProbeReadsLaunchdWithoutChangingIt() {
        XCTAssertEqual(BackendAgentPolicy.probeArgv(uid: 501), ["/bin/launchctl", "print", "gui/501/com.cicada.backend"])
        XCTAssertEqual(BackendAgentPolicy.state(probeStatus: 0, plistExists: true), .running)
        XCTAssertEqual(BackendAgentPolicy.state(probeStatus: 113, plistExists: true), .stopped)
        XCTAssertEqual(BackendAgentPolicy.state(probeStatus: 113, plistExists: false), .missing)
        XCTAssertEqual(BackendAgentPolicy.state(probeStatus: 124, plistExists: true), .unknown)
        XCTAssertEqual(BackendAgentPolicy.state(probeStatus: 127, plistExists: false), .unknown)
    }

    func testInstallRunsTheScriptThenHandsLaunchdThePort() async throws {
        let runner = FakeRunner()
        let plist = FileManager.default.temporaryDirectory.appendingPathComponent("agent-\(UUID()).plist")
        var handedOff = false
        let service = BackendAgentService(runner: runner, installRoot: root, plistURL: plist, uid: 501,
                                          memoryRoot: { "/m/memory" }, onInstalled: { handedOff = true })
        runner.answers["/bin/launchctl print gui/501/com.cicada.backend"] = 113
        await service.refresh()
        XCTAssertEqual(service.state, .missing)
        runner.answers["/bin/launchctl print gui/501/com.cicada.backend"] = 0
        try Data().write(to: plist)
        await service.install()
        XCTAssertEqual(runner.runs.first { $0.argv.first == "/bin/bash" }?.argv, BackendAgentPolicy.installArgv(installRoot: root))
        XCTAssertTrue(handedOff)
        XCTAssertEqual(service.state, .running)
        try? FileManager.default.removeItem(at: plist)
    }

    func testAFailedInstallSaysWhy() async {
        let runner = FakeRunner()
        runner.answers["/bin/bash /x/cicada/scripts/install-backend-agent.sh"] = 3
        let service = BackendAgentService(runner: runner, installRoot: root,
                                          plistURL: URL(fileURLWithPath: "/nonexistent/agent.plist"), uid: 501,
                                          memoryRoot: { nil }, onInstalled: {})
        await service.install()
        XCTAssertEqual(service.state, .failed(Copy.backgroundNoPython), "the script's exit 3, in words")
        XCTAssertEqual(BackendAgentPolicy.failureMessage(status: 4, stderr: ""), Copy.backgroundLaunchdRefused)
        XCTAssertEqual(BackendAgentPolicy.failureMessage(status: 1, stderr: "\n  boom\nmore"), "boom")
        XCTAssertEqual(BackendAgentPolicy.failureMessage(status: 1, stderr: " \n"), Copy.backgroundInstallFailed,
                       "no words from the script: our own sentence, never the import one")
    }
}
