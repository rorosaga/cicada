import Foundation

/// G182 — where Cicada's moving parts live on this Mac, decided once at launch and handed to everything that spawns,
/// registers or allowlists a command.
///
/// Two shapes, never mixed:
/// - **developer** — the app was built from a checkout (`make install-app`, `swift run`). The code root is
///   `BackendProcess.installRoot()`'s G88 ladder, the backend is the checkout's venv, and every command shape is the
///   one `install.sh` has always written. Nothing about the owner's daily setup changes.
/// - **release** — the `.app` carries its own backend at `Contents/Resources/backend/` (`bundle.sh --release
///   --with-backend` stamps `CicadaDistribution = release`). Agents, hooks and the background service run the stable
///   launchers in `~/.cicada/bin` (`LauncherInstaller`), never a path inside the bundle, so moving or updating the
///   app never breaks a registration; memory defaults to the backend's own `~/cicada/memory`, never the bundle.
///
/// Every input is injectable (`resolve`), so tests build either shape without a real Bundle, home or launchd.
struct CicadaRuntime: Equatable, Sendable {
    enum Distribution: Equatable, Sendable { case developer, release }

    static let defaultPort = 8000
    /// `defaults write <bundle id> cicada.port <n>` — a second Mac account, or a port another tool already holds.
    static let portDefaultsKey = "cicada.port"
    static let distributionInfoKey = "CicadaDistribution"
    /// The launchers `LauncherInstaller` writes into `binDir`, one per entry point under `backend/bin`.
    static let launcherNames = ["cicada-backend", "cicada-mcp", "cicada-hook", "cicada-python"]

    let distribution: Distribution
    /// The `.app` this process runs from, standardized.
    let bundlePath: String
    /// What `installRoot()` used to answer: the checkout (developer) or `backend/app` inside the bundle (release).
    let codeRoot: URL
    /// `CICADA_HOME`, else `~/.cicada` — the same home `APIClient.loadToken` reads.
    let cicadaHome: URL
    let port: Int
    /// The memory folder when the live backend has not said: `<checkout>/memory` (developer, as before) or the
    /// backend's own default (release). Never inside the bundle.
    let memoryRootDefault: String

    var isRelease: Bool { distribution == .release }
    /// False while macOS runs the app from a temporary place — a quarantined download it translocated, or a mounted
    /// disk image. Launchers and a re-pointed background service aimed there would break at the next reboot or eject,
    /// so neither is written until the app runs from a real folder (phase-2 review, finding 4).
    var launchersAreStable: Bool { !bundlePath.contains("/AppTranslocation/") && !bundlePath.hasPrefix("/Volumes/") }

    /// The code root as every allowlist compares it (`standardizedFileURL.path`, the `AgentConnectPolicy` rule).
    var root: String { codeRoot.standardizedFileURL.path }
    var binDir: URL { cicadaHome.appendingPathComponent("bin").standardizedFileURL }
    var logDir: URL { cicadaHome.appendingPathComponent("logs").standardizedFileURL }
    var backendURL: String { "http://127.0.0.1:\(port)" }

    /// `<bundle>/Contents/Resources/backend/bin` — what the launchers point at. Only meaningful in a release.
    static func bundledBin(bundlePath: String) -> URL {
        URL(fileURLWithPath: bundlePath).appendingPathComponent("Contents/Resources/backend/bin").standardizedFileURL
    }
    var bundledBin: URL { Self.bundledBin(bundlePath: bundlePath) }

    /// The git a release carries, for `GitRunner`'s last resort; nil in a developer build.
    var bundledGit: String? { isRelease ? bundledBin.appendingPathComponent("git").path : nil }

    private func launcher(_ name: String) -> String { binDir.appendingPathComponent(name).path }

    // MARK: Command shapes

    var pythonPath: String { isRelease ? launcher("cicada-python") : root + "/api/.venv/bin/python" }

    /// The MCP server every agent registers: `python mcp/server.py` (developer) or the launcher alone (release).
    var mcpCommand: (command: String, args: [String]) {
        isRelease ? (launcher("cicada-mcp"), []) : (pythonPath, [root + "/mcp/server.py"])
    }

    /// The argv prefix of a hook-registry call. Two elements in both shapes, so the verb is always `argv[2]`.
    var registryArgv: [String] {
        isRelease ? [launcher("cicada-hook"), "registry"] : [pythonPath, root + "/api/hooks/registry.py"]
    }

    /// A hook's command string, byte for byte what `agent_wiring.hook_command` writes: `kind` is `capture` (Stop)
    /// or `recall` (SessionStart / UserPromptSubmit, G149).
    func hookCommand(kind: String, harness: String) -> String {
        if isRelease { return "\"\(launcher("cicada-hook"))\" \(kind) --harness \(harness)" }
        return "\"\(pythonPath)\" \"\(root)/api/hooks/\(kind).py\" --harness \(harness)"
    }

    /// The app's own backend child. Developer: install.sh's `python -m uvicorn` (round-4 D3), on this port.
    /// Release: the launcher, which reads the port from `CICADA_PORT` in its environment.
    var backendSpawn: (executable: URL, arguments: [String]) {
        if isRelease {
            // From a temporary place no launcher is written; run the bundle's own script for this session.
            let path = launchersAreStable ? launcher("cicada-backend")
                : bundledBin.appendingPathComponent("cicada-backend").path
            return (URL(fileURLWithPath: path), [])
        }
        return BackendProcess.spawnCommand(installRoot: codeRoot, port: port)
    }

    // MARK: Resolution

    /// Built once from the real environment.
    static let current: CicadaRuntime = resolve()

    /// Release iff the Info.plist says so AND the bundled backend is really there; anything less is a developer
    /// build, resolved exactly as before G182.
    static func resolve(
        infoValue: (String) -> Any? = { Bundle.main.object(forInfoDictionaryKey: $0) },
        bundlePath: String = Bundle.main.bundlePath,
        environment: [String: String] = ProcessInfo.processInfo.environment,
        storedPort: Int = UserDefaults.standard.integer(forKey: portDefaultsKey),
        homeDirectory: URL = FileManager.default.homeDirectoryForCurrentUser,
        fileExists: @escaping (String) -> Bool = { FileManager.default.fileExists(atPath: $0) }
    ) -> CicadaRuntime {
        let bundle = URL(fileURLWithPath: bundlePath).standardizedFileURL.path
        let release = (infoValue(distributionInfoKey) as? String) == "release"
            && fileExists(bundledBin(bundlePath: bundle).appendingPathComponent("cicada-backend").path)
        let home = environment["CICADA_HOME"].flatMap { $0.isEmpty ? nil : URL(fileURLWithPath: $0) }
            ?? homeDirectory.appendingPathComponent(".cicada")
        // The `cicada.port` default is a release's alone: a developer's launchd plist is written by install.sh on 8000
        // (or `CICADA_PORT`), and an app that followed a stored port there would spawn a second backend beside it.
        let port = Self.port(environment: environment, stored: release ? storedPort : 0)
        if release {
            let code = URL(fileURLWithPath: bundle).appendingPathComponent("Contents/Resources/backend/app")
            return CicadaRuntime(distribution: .release, bundlePath: bundle, codeRoot: code, cicadaHome: home, port: port,
                                 memoryRootDefault: releaseMemoryDefault(environment: environment, bundlePath: bundle,
                                                                         homeDirectory: homeDirectory))
        }
        let code = BackendProcess.installRoot(
            bundlePath: bundlePath, stampedRepoRoot: infoValue("CicadaRepoRoot") as? String,
            homeDirectory: homeDirectory, pathExists: fileExists)
        return CicadaRuntime(distribution: .developer, bundlePath: bundle, codeRoot: code, cicadaHome: home, port: port,
                             memoryRootDefault: code.appendingPathComponent("memory").path)
    }

    /// `CICADA_PORT` (1–65535), else the `cicada.port` default, else 8000 — the same order the launchers and
    /// `install-backend-agent.sh` read, so the app and its backend agree on where to meet.
    /// `stored` is the `cicada.port` default (`integer(forKey:)`, so 0 when unset).
    static func port(environment: [String: String], stored: Int) -> Int {
        if let raw = environment["CICADA_PORT"]?.trimmingCharacters(in: .whitespaces), let value = Int(raw),
           (1...65535).contains(value) {
            return value
        }
        return (1...65535).contains(stored) ? stored : defaultPort
    }

    /// `CICADA_MEMORY_PATH`, else `~/cicada/memory` (`api/config.py`'s own default). A value inside the bundle is
    /// refused: an update replaces the bundle, and a bank must never be replaced with it.
    static func releaseMemoryDefault(environment: [String: String], bundlePath: String, homeDirectory: URL) -> String {
        let fallback = homeDirectory.appendingPathComponent("cicada/memory").path
        guard let raw = environment["CICADA_MEMORY_PATH"], !raw.isEmpty else { return fallback }
        let path = URL(fileURLWithPath: raw).standardizedFileURL.path
        return path == bundlePath || path.hasPrefix(bundlePath + "/") ? fallback : path
    }

    /// A developer runtime pinned to `codeRoot` — what tests and the checkout-shaped call sites build.
    static func developer(codeRoot: URL, cicadaHome: URL = URL(fileURLWithPath: "/nonexistent/.cicada"),
                          port: Int = defaultPort) -> CicadaRuntime {
        CicadaRuntime(distribution: .developer, bundlePath: "/nonexistent/Cicada.app", codeRoot: codeRoot,
                      cicadaHome: cicadaHome, port: port, memoryRootDefault: codeRoot.appendingPathComponent("memory").path)
    }
}
