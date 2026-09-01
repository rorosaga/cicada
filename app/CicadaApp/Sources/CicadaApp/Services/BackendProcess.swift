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

    func start() {
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
            for line in envContents.components(separatedBy: .newlines) {
                let trimmed = line.trimmingCharacters(in: .whitespaces)
                guard !trimmed.isEmpty, !trimmed.hasPrefix("#") else { continue }
                let parts = trimmed.split(separator: "=", maxSplits: 1)
                if parts.count == 2 {
                    environment[String(parts[0])] = String(parts[1])
                }
            }
        }

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        proc.arguments = [
            apiPath.appendingPathComponent(".venv/bin/uvicorn").path,
            "api.main:app",
            "--host", "127.0.0.1",
            "--port", "8000",
        ]
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
        process?.terminate()
        process = nil
        isRunning = false
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
