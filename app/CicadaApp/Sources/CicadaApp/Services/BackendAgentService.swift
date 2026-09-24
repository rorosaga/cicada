import Foundation
import Observation

/// What Settings → General says about the background service (R-FA9).
enum BackendAgentState: Equatable {
    case checking, running, stopped, missing, unknown, installing
    case failed(String)
}

/// Round-4 D3 (R-FA8, R-FA9) — the only command the app runs for the background service, pinned to the checkout the
/// app was built from (the `AgentConnectPolicy` rule), and the read-only probe beside it.
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
    /// leave :8000 to launchd (finding 2), so the two can never disagree about which file means "launchd owns it".
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
}

@MainActor
@Observable
final class BackendAgentService {
    private(set) var state: BackendAgentState = .checking

    @ObservationIgnored private let runner: AgentProcessRunning
    @ObservationIgnored let installRoot: URL
    @ObservationIgnored private let plistURL: URL
    @ObservationIgnored private let uid: uid_t
    @ObservationIgnored private let memoryRoot: () async -> String?
    @ObservationIgnored private let envFileContents: () -> String?
    @ObservationIgnored private let onInstalled: () -> Void

    init(runner: AgentProcessRunning = LiveAgentProcessRunner(),
         installRoot: URL = BackendProcess.installRoot(),
         plistURL: URL = BackendAgentPolicy.plistURL(),
         uid: uid_t = getuid(),
         memoryRoot: @escaping () async -> String? = { try? await APIClient.shared.fetchHealth().memoryRoot },
         envFileContents: (() -> String?)? = nil,
         onInstalled: @escaping () -> Void = {}) {
        self.runner = runner
        self.installRoot = installRoot
        self.plistURL = plistURL
        self.uid = uid
        self.memoryRoot = memoryRoot
        let envFile = installRoot.appendingPathComponent("api/.env")
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

    /// Only ever from the person's click on Install.
    func install() async {
        let argv = BackendAgentPolicy.installArgv(installRoot: installRoot)
        guard BackendAgentPolicy.isAllowed(argv, installRoot: installRoot) else {
            state = .failed(Copy.backgroundRefused)
            return
        }
        state = .installing
        guard let memory = BackendAgentPolicy.memoryPath(
            live: await memoryRoot(), envFile: BackendAgentPolicy.envFileMemoryPath(envFileContents())) else {
            state = .failed(Copy.backgroundNeedsBackend)
            return
        }
        let env = BackendAgentPolicy.environment(base: ProcessInfo.processInfo.environment, installRoot: installRoot,
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
}
