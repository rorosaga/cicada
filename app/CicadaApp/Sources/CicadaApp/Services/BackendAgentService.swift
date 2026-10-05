import Foundation
import Observation

/// What Settings → General says about the background service (R-FA9).
enum BackendAgentState: Equatable {
    case checking, running, stopped, missing, unknown, installing
    case failed(String)
}

/// Round-4 D3 (R-FA8, R-FA9) — the only command the app runs for the background service, pinned to the checkout the
/// app was built from (the `AgentConnectPolicy` rule), and the read-only probe beside it. G182: in a release the
/// "checkout" is the bundled `backend/app` (`CicadaRuntime.codeRoot`), so the argv keeps its shape in both builds.
enum BackendAgentPolicy {
    static let label = "com.cicada.backend"
    static let probeTimeout: Duration = .seconds(2)
    static let installTimeout: Duration = .seconds(30)

    static func scriptPath(installRoot: URL) -> String {
        installRoot.standardizedFileURL.path + "/scripts/install-backend-agent.sh"
    }

    static func installArgv(installRoot: URL) -> [String] { ["/bin/bash", scriptPath(installRoot: installRoot)] }

    /// What the row shows before Install, so the person sees exactly what will run (spec decision 14, D-1).
    static func display(installRoot: URL) -> String { installArgv(installRoot: installRoot).joined(separator: " ") }

    static func isAllowed(_ argv: [String], installRoot: URL) -> Bool {
        argv == installArgv(installRoot: installRoot) && !argv[1].contains("/../")
    }

    static func probeArgv(uid: uid_t) -> [String] { ["/bin/launchctl", "print", "gui/\(uid)/\(label)"] }

    /// 124 = timed out, 127 = could not start (`LiveAgentProcessRunner`'s conventions).
    static func state(probeStatus: Int32, plistExists: Bool) -> BackendAgentState {
        if probeStatus == 124 || probeStatus == 127 { return .unknown }
        if probeStatus == 0 { return .running }
        return plistExists ? .stopped : .missing
    }

    /// The script's own exit codes in words (3: no Python environment, 4: launchd refused); anything else, the
    /// script's first stderr line. Not `AgentConnect.failureMessage`, whose 3 means an unparseable settings file.
    static func failureMessage(status: Int32, stderr: String) -> String {
        switch status {
        case 3: return Copy.backgroundNoPython
        case 4: return Copy.backgroundLaunchdRefused
        default:
            let first = stderr.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }.first { !$0.isEmpty }
            // Never `Copy.intakeFailed` (AgentConnect's fallback): that is the import sentence.
            return first ?? Copy.backgroundInstallFailed
        }
    }

    /// Where launchd's copy of the background service is declared. `BackendProcess.start` reads the same path to
    /// leave the backend's port to launchd (finding 2), so the two can never disagree about which file means "launchd owns it".
    static func plistURL(home: URL = FileManager.default.homeDirectoryForCurrentUser) -> URL {
        home.appendingPathComponent("Library/LaunchAgents/\(label).plist")
    }

    /// Finding 5 — the memory folder the always-on service gets: the live backend's own root first, then the
    /// `CICADA_MEMORY_PATH` install.sh wrote into `api/.env` (the file `BackendProcess` overlays too). Never a guess
    /// from the checkout: install.sh defaults memory to `~/cicada/memory` wherever the repo lives, so
    /// `<installRoot>/memory` would silently serve an empty folder — the split-brain bug, whose symptom is silence.
    /// nil means refuse Install.
    static func memoryPath(live: String?, envFile: String?) -> String? {
        for candidate in [live, envFile] {
            if let c = candidate?.trimmingCharacters(in: .whitespaces), !c.isEmpty { return c }
        }
        return nil
    }

    /// `CICADA_MEMORY_PATH` from an `api/.env` body, parsed like `BackendProcess.envOverlay` plus the quotes and `~`
    /// python-dotenv and a shell would resolve, so the plist names the folder the backend actually reads.
    static func envFileMemoryPath(_ contents: String?, home: String = NSHomeDirectory()) -> String? {
        guard let contents, var value = BackendProcess.envOverlay(contents)["CICADA_MEMORY_PATH"] else { return nil }
        value = value.trimmingCharacters(in: .whitespaces)
        if value.count >= 2, let f = value.first, f == value.last, f == "\"" || f == "'" {
            value = String(value.dropFirst().dropLast())
        }
        if value == "~" { value = home } else if value.hasPrefix("~/") { value = home + value.dropFirst(1) }
        if value.hasPrefix("$HOME/") { value = home + value.dropFirst(5) }
        return value.isEmpty ? nil : value
    }

    static func environment(base: [String: String], installRoot: URL, memoryRoot: String) -> [String: String] {
        var env = base
        for key in AgentConnect.scrubbedKeys { env.removeValue(forKey: key) }
        env["CICADA_CAPTURE"] = "off"
        env["CICADA_REPO"] = installRoot.standardizedFileURL.path
        env["CICADA_MEMORY_PATH"] = memoryRoot
        env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
        return env
    }

    /// G182 — the same environment for this runtime. A release adds what the script needs to write a plist that
    /// runs the stable launcher (`CICADA_BACKEND_PROGRAM`), logs under Cicada's home, and the port the app reads.
    static func environment(base: [String: String], runtime: CicadaRuntime, memoryRoot: String) -> [String: String] {
        var env = environment(base: base, installRoot: runtime.codeRoot, memoryRoot: memoryRoot)
        guard runtime.isRelease else { return env }
        env["CICADA_BACKEND_PROGRAM"] = runtime.binDir.appendingPathComponent("cicada-backend").path
        env["CICADA_LOG_DIR"] = runtime.logDir.path
        env["CICADA_PORT"] = String(runtime.port)
        env["CICADA_HOME"] = runtime.cicadaHome.path
        return env
    }

    /// G182 — a plist written before this build (a venv python, or an older copy of the app) still runs whatever it
    /// named, so a person who chose the background service is quietly left on the old backend. A plan only when the
    /// plist exists, parses, and either runs something other than the launcher or carries another port or home than
    /// this app's (a backend launchd keeps on the old port would run beside the one the app spawns — two schedulers
    /// on one bank). Nothing on disk, or nothing readable, is never a reason to install (the service stays opt-in).
    /// A plist that runs a checkout's venv python that still exists is a developer's own setup and is left alone:
    /// opening a release once must not take over a source install's backend (phase-2 review, finding 3).
    struct Migration: Equatable {
        /// The bank the old plist served — the fallback when the live backend doesn't answer, so a migration never
        /// re-points the service at an empty `~/cicada/memory` (split-brain; phase-2 review, finding 1).
        let memoryPath: String?
    }

    static func migration(plistData: Data?, runtime: CicadaRuntime,
                          fileExists: (String) -> Bool = { FileManager.default.isExecutableFile(atPath: $0) })
        -> Migration? {
        guard let plistData,
              let plist = try? PropertyListSerialization.propertyList(from: plistData, format: nil) as? [String: Any],
              let program = (plist["ProgramArguments"] as? [Any])?.first as? String else { return nil }
        if program.hasSuffix("/api/.venv/bin/python"), fileExists(program) { return nil }
        let env = plist["EnvironmentVariables"] as? [String: Any] ?? [:]
        let launcher = runtime.binDir.appendingPathComponent("cicada-backend").path
        let port = (env["CICADA_PORT"] as? String) ?? String(CicadaRuntime.defaultPort)
        let defaultHome = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".cicada").path
        let home = (env["CICADA_HOME"] as? String) ?? defaultHome
        if program == launcher, port == String(runtime.port), home == runtime.cicadaHome.path { return nil }
        let memory = (env["CICADA_MEMORY_PATH"] as? String).flatMap { $0.isEmpty ? nil : $0 }
        return Migration(memoryPath: memory)
    }
}

@MainActor
@Observable
final class BackendAgentService {
    private(set) var state: BackendAgentState = .checking

    @ObservationIgnored private let runner: AgentProcessRunning
    @ObservationIgnored let runtime: CicadaRuntime
    var installRoot: URL { runtime.codeRoot }
    @ObservationIgnored private let plistURL: URL
    @ObservationIgnored private let uid: uid_t
    @ObservationIgnored private let memoryRoot: () async -> String?
    @ObservationIgnored private let envFileContents: () -> String?
    @ObservationIgnored private let onInstalled: () -> Void

    init(runner: AgentProcessRunning = LiveAgentProcessRunner(),
         runtime: CicadaRuntime = .current,
         plistURL: URL = BackendAgentPolicy.plistURL(),
         uid: uid_t = getuid(),
         memoryRoot: @escaping () async -> String? = { try? await APIClient.shared.fetchHealth().memoryRoot },
         envFileContents: (() -> String?)? = nil,
         onInstalled: @escaping () -> Void = {}) {
        self.runner = runner
        self.runtime = runtime
        self.plistURL = plistURL
        self.uid = uid
        self.memoryRoot = memoryRoot
        let envFile = runtime.codeRoot.appendingPathComponent("api/.env")
        self.envFileContents = envFileContents ?? { try? String(contentsOf: envFile, encoding: .utf8) }
        self.onInstalled = onInstalled
    }

    var display: String { BackendAgentPolicy.display(installRoot: installRoot) }

    func refresh() async {
        if state == .installing { return }
        let probe = await runner.run(BackendAgentPolicy.probeArgv(uid: uid), environment: ["PATH": "/usr/bin:/bin"],
                                     timeout: BackendAgentPolicy.probeTimeout)
        state = BackendAgentPolicy.state(probeStatus: probe.status,
                                         plistExists: FileManager.default.fileExists(atPath: plistURL.path))
    }

    /// From the person's click on Install, or `migrateIfNeeded` keeping a choice they already made (with the bank
    /// the old plist served as the fallback memory path).
    func install(previousMemory: String? = nil) async {
        let argv = BackendAgentPolicy.installArgv(installRoot: installRoot)
        guard BackendAgentPolicy.isAllowed(argv, installRoot: installRoot) else {
            state = .failed(Copy.backgroundRefused)
            return
        }
        state = .installing
        // G182 — a release has no `api/.env`; its fallback is the backend's own default, never a bundle path.
        let fallback = runtime.isRelease ? (previousMemory ?? runtime.memoryRootDefault)
            : BackendAgentPolicy.envFileMemoryPath(envFileContents())
        guard let memory = BackendAgentPolicy.memoryPath(live: await memoryRoot(), envFile: fallback) else {
            state = .failed(Copy.backgroundNeedsBackend)
            return
        }
        let env = BackendAgentPolicy.environment(base: ProcessInfo.processInfo.environment, runtime: runtime,
                                                 memoryRoot: memory)
        let result = await runner.run(argv, environment: env, timeout: BackendAgentPolicy.installTimeout)
        guard result.status == 0 else {
            state = .failed(BackendAgentPolicy.failureMessage(status: result.status, stderr: result.stderr))
            return
        }
        onInstalled()
        state = .checking
        await refresh()
    }

    /// G182 — on a release's launch: when the background service is already installed but its plist runs something
    /// other than the launcher (a checkout's venv, an older copy of the app), run the same install once so the
    /// person's choice follows the app. No plist → nothing (the service stays opt-in). Returns whether it ran.
    @discardableResult
    func migrateIfNeeded(readPlist: (URL) -> Data? = { try? Data(contentsOf: $0) },
                         fileExists: (String) -> Bool = { FileManager.default.isExecutableFile(atPath: $0) }) async -> Bool {
        guard runtime.isRelease, runtime.launchersAreStable, state != .installing else { return false }
        guard let plan = BackendAgentPolicy.migration(plistData: readPlist(plistURL), runtime: runtime,
                                                      fileExists: fileExists) else { return false }
        await install(previousMemory: plan.memoryPath)
        return true
    }
}
