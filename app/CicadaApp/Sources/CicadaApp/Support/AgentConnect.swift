import Foundation

struct AgentProcessResult: Equatable {
    let status: Int32
    let stderr: String
}

protocol AgentProcessRunning: Sendable {
    func run(_ argv: [String], environment: [String: String], timeout: Duration) async -> AgentProcessResult
}

/// `Process`, never a shell: argv[0] is an absolute path the backend resolved,
/// and nothing is interpolated into a command string. 124 on timeout, 127 when
/// the binary cannot start — `run_cli`'s conventions (`connections/base.py`).
struct LiveAgentProcessRunner: AgentProcessRunning {
    func run(_ argv: [String], environment: [String: String], timeout: Duration) async -> AgentProcessResult {
        await withCheckedContinuation { continuation in
            let process = Process()
            process.executableURL = URL(fileURLWithPath: argv[0])
            process.arguments = Array(argv.dropFirst())
            process.environment = environment
            let errors = Pipe()
            process.standardError = errors
            process.standardOutput = FileHandle.nullDevice
            process.standardInput = FileHandle.nullDevice
            // The termination handler and the timeout race; the first one wins.
            let once = ResumeOnce(continuation)
            let finish: @Sendable (AgentProcessResult) -> Void = { once.resume($0) }
            process.terminationHandler = { done in
                let data = errors.fileHandleForReading.readDataToEndOfFile()
                finish(AgentProcessResult(status: done.terminationStatus, stderr: String(decoding: data, as: UTF8.self)))
            }
            do {
                try process.run()
            } catch {
                finish(AgentProcessResult(status: 127, stderr: error.localizedDescription))
                return
            }
            let seconds = Double(timeout.components.seconds) + Double(timeout.components.attoseconds) / 1e18
            DispatchQueue.global().asyncAfter(deadline: .now() + seconds) {
                if process.isRunning {
                    process.terminate()
                    finish(AgentProcessResult(status: 124, stderr: "timed out"))
                }
            }
        }
    }
}

/// Resumes a continuation exactly once. A lock-guarded box rather than a
/// captured `var`, so the two racing callbacks stay clean under Swift 6's
/// Sendable checking (a local `func` mutating a captured flag is an error there).
private final class ResumeOnce: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<AgentProcessResult, Never>?

    init(_ continuation: CheckedContinuation<AgentProcessResult, Never>) { self.continuation = continuation }

    func resume(_ result: AgentProcessResult) {
        lock.lock()
        let pending = continuation
        continuation = nil
        lock.unlock()
        pending?.resume(returning: result)
    }
}

enum AgentConnectOutcome: Equatable {
    case done
    /// Not run at all; these are the commands to copy (D-1's fallback).
    case refused([String])
    case failed(String)
}

/// Track I T7 (R-IA28) — the only two command shapes the app will run, pinned to
/// the checkout the app itself was built from (`BackendProcess.installRoot()`).
/// The backend hands the argv over (`GET /agents/wiring`), but a response the app
/// cannot vouch for — another checkout, another verb, one extra token — runs
/// nothing.
enum AgentConnectPolicy {
    /// Each harness's Stop-hook settings file and the harness id install.sh's
    /// `hook_command` names for it (`install.sh:312, 318`).
    static let hookHarnesses: [(settingsSuffix: String, harness: String)] = [
        ("/.claude/settings.json", "claude-code"),
        ("/.codex/hooks.json", "codex"),
    ]

    static func isAllowed(_ argv: [String], installRoot: URL, binaries: Set<String>) -> Bool {
        let root = installRoot.standardizedFileURL.path
        let python = root + "/api/.venv/bin/python"
        guard let head = argv.first else { return false }
        if binaries.contains(head), ["claude", "codex"].contains(URL(fileURLWithPath: head).lastPathComponent) {
            guard argv.count >= 7, Array(argv[1...3]) == ["mcp", "add", "cicada"],
                  let dashes = argv.firstIndex(of: "--"),
                  Array(argv[(dashes + 1)...]) == [python, root + "/mcp/server.py"] else { return false }
            return argv[4..<dashes].allSatisfy { ["--scope", "user", "--env"].contains($0) || $0.hasPrefix("CICADA_MEMORY_PATH=") }
        }
        guard argv.count == 9, head == python, argv[1] == root + "/api/hooks/registry.py", argv[2] == "install",
              argv[3] == "--settings", !argv[4].contains("/../"),
              let harness = hookHarnesses.first(where: { argv[4].hasSuffix($0.settingsSuffix) })?.harness,
              Array(argv[5...6]) == ["--event", "Stop"], argv[7] == "--command" else { return false }
        // The command runs on every agent turn, so it is install.sh's
        // `hook_command` byte for byte — a substring check would let an
        // appended `; curl … | sh` through.
        return argv[8] == "\"\(python)\" \"\(root)/api/hooks/capture.py\" --harness \(harness)"
    }
}

/// Track I T7 (spec decision 14, D-1) — the app registers the MCP server and the
/// Stop hook itself, after the person's click, with the exact commands shown to
/// them first (`FoundRow`'s disclosure = `display`). The same effect as
/// `install.sh:277-321`, and the only route a `.dmg` install will have.
enum AgentConnect {
    static let stepTimeout: Duration = .seconds(15)
    /// `connections/base.py::SCRUBBED_ENV_KEYS` — a child never inherits a key.
    static let scrubbedKeys = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"]

    /// `CICADA_CAPTURE=off` so nothing Cicada runs is captured back as an episode
    /// (R8); the binary's own directory first on PATH, because a Finder-launched
    /// app's PATH is the bare system one.
    static func environment(_ base: [String: String], binary: String) -> [String: String] {
        var env = base
        for key in scrubbedKeys { env.removeValue(forKey: key) }
        env["CICADA_CAPTURE"] = "off"
        let dir = URL(fileURLWithPath: binary).deletingLastPathComponent().path
        env["PATH"] = dir + ":" + (base["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin")
        return env
    }

    static func failureMessage(status: Int32, stderr: String) -> String {
        if status == 3 { return Copy.foundInvalidSettings }
        let first = stderr.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }.first { !$0.isEmpty }
        return first ?? Copy.intakeFailed
    }

    static func run(_ steps: [AgentWiringStep], installRoot: URL, binaries: Set<String>,
                    runner: AgentProcessRunning = LiveAgentProcessRunner(),
                    base: [String: String] = ProcessInfo.processInfo.environment) async -> AgentConnectOutcome {
        guard steps.allSatisfy({ AgentConnectPolicy.isAllowed($0.argv, installRoot: installRoot, binaries: binaries) }) else {
            return .refused(steps.map(\.display))
        }
        for step in steps {
            let result = await runner.run(step.argv, environment: environment(base, binary: step.argv[0]), timeout: stepTimeout)
            if result.status != 0 { return .failed(failureMessage(status: result.status, stderr: result.stderr)) }
        }
        return .done
    }
}
