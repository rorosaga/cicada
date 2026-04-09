import Foundation

@Observable
final class BackendProcess {
    var isRunning = false
    private var process: Process?

    func start() {
        guard !isRunning else { return }

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
