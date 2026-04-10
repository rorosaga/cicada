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

    private func resolveMemoryPath() -> URL {
        // Development: use sibling memory/ directory
        let bundlePath = Bundle.main.bundlePath
        if bundlePath.contains(".build") || bundlePath.contains("DerivedData") {
            // Dev build — resolve relative to known project structure
            let cicadaRoot = findCicadaRoot()
            return cicadaRoot.appendingPathComponent("memory")
        }
        // Production: ~/cicada/memory
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("cicada/memory")
    }

    private func resolveAPIPath() -> URL {
        let bundlePath = Bundle.main.bundlePath
        if bundlePath.contains(".build") || bundlePath.contains("DerivedData") {
            return findCicadaRoot().appendingPathComponent("api")
        }
        // Production: bundled in app resources
        return Bundle.main.resourceURL?
            .appendingPathComponent("api") ?? URL(fileURLWithPath: "/usr/local/cicada/api")
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

    private func findCicadaRoot() -> URL {
        // Walk up from bundle path to find cicada/ root
        var url = URL(fileURLWithPath: Bundle.main.bundlePath)
        for _ in 0..<10 {
            url = url.deletingLastPathComponent()
            if FileManager.default.fileExists(atPath: url.appendingPathComponent("CLAUDE.md").path) {
                return url
            }
        }
        // Fallback
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("cicada")
    }
}
