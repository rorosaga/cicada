import Foundation
import AppKit
import Darwin

@Observable
final class BackendProcess {
    var isRunning = false
    private var process: Process?
    private var terminationObserver: NSObjectProtocol?

    deinit {
        stop()
    }

    /// Round-4 final review, finding 2 — with Open at login and Keep memory working both on, launchd's RunAtLoad
    /// uvicorn and this login-launched app race for :8000. uvicorn runs its lifespan before it binds, so the port
    /// probe below can see a free port and spawn a second backend; if the child wins, launchd's KeepAlive copy
    /// fails its bind and restarts (a full startup) every ~10 s all session. When the LaunchAgent plist exists,
    /// launchd owns the port: wait for it to bind, and spawn only if nothing has after `launchdGrace`.
    static let launchdGrace: Duration = .seconds(15)
    private var launchdWait: Task<Void, Never>?

    func start(launchAgentPlist: URL = BackendAgentPolicy.plistURL()) {
        guard !isRunning else { return }
        if FileManager.default.fileExists(atPath: launchAgentPlist.path) {
            isRunning = true
            guard launchdWait == nil else { return }
            launchdWait = Task { @MainActor [weak self] in
                let clock = ContinuousClock()
                let deadline = clock.now.advanced(by: Self.launchdGrace)
                while clock.now < deadline {
                    if Task.isCancelled { return }
                    if self?.isPortInUse(port: 8000) ?? true { return }
                    try? await Task.sleep(for: .seconds(1))
                }
                // A plist launchd never loaded (unbootstrapped by hand): the app's own backend, as before.
                guard let self, !Task.isCancelled else { return }
                self.launchdWait = nil
                self.isRunning = false
                self.spawn()
            }
            return
        }
        spawn()
    }

    private func spawn() {
        guard !isRunning else { return }

        // If something is already bound to 127.0.0.1:8000 (e.g. a manually
        // launched `uvicorn` for development), don't spawn a second copy —
        // that just leaves an orphaned child and a "port in use" error.
        if isPortInUse(port: 8000) {
            print("Backend already running on port 8000 — skipping spawn.")
            isRunning = true
            return
        }

        // Kill the child process when the app quits so we don't leave orphans.
        if terminationObserver == nil {
            terminationObserver = NotificationCenter.default.addObserver(
                forName: NSApplication.willTerminateNotification,
                object: nil,
                queue: .main
            ) { [weak self] _ in
                self?.stop()
            }
        }

        let memoryPath = resolveMemoryPath()
        let apiPath = resolveAPIPath()

        // Ensure memory directory exists
        let fm = FileManager.default
        for sub in ["entities", "nudges", "clarifications", "episodes"] {
            let dir = memoryPath.appendingPathComponent(sub)
            try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        }

        // Load .env file for API key
        let envFile = apiPath.appendingPathComponent(".env")
        var environment = ProcessInfo.processInfo.environment
        environment["CICADA_MEMORY_PATH"] = memoryPath.path
        environment["PYTHONPATH"] = apiPath.deletingLastPathComponent().path

        if fm.fileExists(atPath: envFile.path),
           let envContents = try? String(contentsOf: envFile, encoding: .utf8) {
            environment.merge(Self.envOverlay(envContents)) { _, new in new }
        }

        let proc = Process()
        let command = Self.spawnCommand(installRoot: apiPath.deletingLastPathComponent())
        proc.executableURL = command.executable
        proc.arguments = command.arguments
        proc.currentDirectoryURL = apiPath.deletingLastPathComponent()
        proc.environment = environment
        proc.standardOutput = FileHandle.nullDevice
        proc.standardError = FileHandle.nullDevice

        do {
            try proc.run()
            process = proc
            isRunning = true
        } catch {
            print("Failed to start backend: \(error)")
        }
    }

    func stop() {
        launchdWait?.cancel()
        launchdWait = nil
        process?.terminate()
        process = nil
        isRunning = false
    }

    /// `KEY=value` lines of an `api/.env`, comments and blanks skipped. Shared with `BackendAgentPolicy` so the
    /// always-on service reads the same memory folder this spawn would (round-4 final review, finding 5).
    static func envOverlay(_ contents: String) -> [String: String] {
        var out: [String: String] = [:]
        for line in contents.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard !trimmed.isEmpty, !trimmed.hasPrefix("#") else { continue }
            let parts = trimmed.split(separator: "=", maxSplits: 1)
            if parts.count == 2 { out[String(parts[0])] = String(parts[1]) }
        }
        return out
    }

    /// Round-4 D3 (R-FA10) — install.sh's own command: `python -m uvicorn`, the interpreter itself as the executable
    /// (no `/usr/bin/env`). The venv's `uvicorn` console script hardcodes its interpreter in the shebang, so moving
    /// the repo broke it — exactly what `install.sh`'s NOTE forbids for the LaunchAgent plist.
    static func spawnCommand(installRoot: URL) -> (executable: URL, arguments: [String]) {
        (installRoot.appendingPathComponent("api/.venv/bin/python"),
         ["-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000"])
    }

    /// R-FA8 — after the background service is installed, give launchd the port: stop only the child THIS app
    /// spawned (never a developer's uvicorn that happened to hold :8000 — `start()` spawns nothing then, so
    /// `process` is nil and this is a no-op).
    func stopSpawnedChild() {
        guard process != nil else { return }
        stop()
    }

    /// The Cicada checkout/install root: the repo directory in dev builds, or
    /// the checkout that produced an installed app. Shared by the backend
    /// spawn paths and the Connect page (which renders copy-pasteable MCP
    /// registration commands).
    ///
    /// Resolution order (G88):
    ///   1. `CicadaRepoRoot` stamped into Info.plist by `bundle.sh` at build
    ///      time (`git rev-parse --show-toplevel`), if present AND still on
    ///      disk. Without the disk check, a repo that was moved after the
    ///      last build would silently point at a directory that no longer
    ///      exists instead of falling back.
    ///   2. Dev builds (`.build` / `DerivedData` in the bundle path): walk up
    ///      from the executable looking for `CLAUDE.md`.
    ///   3. `~/cicada` — the pre-G88 heuristic, kept as a last resort for an
    ///      app bundle built before this fix shipped (no stamp present).
    ///
    /// Parameters default to the real environment; tests inject fakes so the
    /// whole ladder is exercisable without a real Bundle/FileManager.
    static func installRoot(
        bundlePath: String = Bundle.main.bundlePath,
        stampedRepoRoot: String? = Bundle.main.object(forInfoDictionaryKey: "CicadaRepoRoot") as? String,
        homeDirectory: URL = FileManager.default.homeDirectoryForCurrentUser,
        pathExists: (String) -> Bool = { FileManager.default.fileExists(atPath: $0) }
    ) -> URL {
        if let stamped = stampedRepoRoot, !stamped.isEmpty, pathExists(stamped) {
            return URL(fileURLWithPath: stamped)
        }
        if bundlePath.contains(".build") || bundlePath.contains("DerivedData") {
            return findCicadaRoot(bundlePath: bundlePath, homeDirectory: homeDirectory, pathExists: pathExists)
        }
        return homeDirectory.appendingPathComponent("cicada")
    }

    private func resolveMemoryPath() -> URL {
        Self.installRoot().appendingPathComponent("memory")
    }

    /// `api/` lives inside the same checkout as `installRoot()` resolves —
    /// there is no separate "bundled into Resources" copy (`bundle.sh` never
    /// copies `api/` into the `.app`), so this just derives from the same
    /// ladder rather than re-deriving its own (previously stale) heuristic.
    /// In practice this path only matters when nothing already holds :8000 —
    /// the supported story is the always-on launchd backend from `install.sh`.
    private func resolveAPIPath() -> URL {
        Self.installRoot().appendingPathComponent("api")
    }

    private func isPortInUse(port: UInt16) -> Bool {
        // Try to bind a transient socket on 127.0.0.1:port. If bind() succeeds
        // the port is free; if it fails with EADDRINUSE, something else owns it.
        let sock = socket(AF_INET, SOCK_STREAM, 0)
        guard sock >= 0 else { return false }
        defer { close(sock) }

        var yes: Int32 = 1
        setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &yes, socklen_t(MemoryLayout<Int32>.size))

        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = in_port_t(port).bigEndian
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")

        let bindResult = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.bind(sock, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        return bindResult < 0 && errno == EADDRINUSE
    }

    private static func findCicadaRoot(
        bundlePath: String = Bundle.main.bundlePath,
        homeDirectory: URL = FileManager.default.homeDirectoryForCurrentUser,
        pathExists: (String) -> Bool = { FileManager.default.fileExists(atPath: $0) }
    ) -> URL {
        // Walk up from bundle path to find cicada/ root. Works for a `.build`
        // bundle path (sits inside the checkout), but an Xcode DerivedData
        // build lives under ~/Library/Developer/Xcode/DerivedData — a
        // location with no ancestor relationship to the checkout at all — so
        // that shape always exhausts the walk and lands on the fallback below.
        var url = URL(fileURLWithPath: bundlePath)
        for _ in 0..<10 {
            url = url.deletingLastPathComponent()
            if pathExists(url.appendingPathComponent("CLAUDE.md").path) {
                return url
            }
        }
        // Fallback — uses the injected home directory, not a hardcoded real
        // one, so this whole ladder stays testable without touching disk.
        return homeDirectory.appendingPathComponent("cicada")
    }
}
