import CryptoKit
import Foundation

/// The one place the app runs an agent's installer or writes into an agent's
/// skill folders (G138, R-O26).
///
/// Third-party skills: only the command the agent's own installer takes — an
/// argv, never a shell string, allowlisted to `claude`, `codex` and `npx`, the
/// program resolved to an absolute path and shown to the person verbatim
/// before it runs, `CICADA_CAPTURE=off` forced (Cicada's own spawns never
/// capture themselves), stdin closed, five minutes at most, terminated on
/// cancel. Cicada's own skills (`cicada`, `cicada-librarian`): the app copies
/// the checkout's SKILL.md into `~/.claude/skills/<name>/` or
/// `~/.agents/skills/<name>/` with a `.cicada-managed.json` marker, never
/// overwrites a copy that no longer matches its marker, and removes only the
/// two files it wrote. This amends G72's "never edits ~/.claude" (R5 D2).
enum SkillInstaller {
    // MARK: Third-party — the agent's own installer, after consent

    static let allowedPrograms: Set<String> = ["claude", "codex", "npx"]
    /// Mirrors `api/services/connections/base.py::_CLI_FALLBACK_DIRS`: a
    /// Finder-launched app has launchd's bare PATH, the backend's problem too.
    static let fallbackDirectories = ["~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin",
                                      "~/.npm-global/bin", "~/.claude/local", "~/.codex/bin"]
    static let timeout: TimeInterval = 300

    struct ResolvedStep: Equatable {
        let executable: String
        let arguments: [String]
        let tolerateFailure: Bool
    }

    struct Command: Equatable {
        let steps: [ResolvedStep]
        /// What Cicada sets on top of the app's own environment.
        let environment: [String: String]

        /// Exactly what runs, one line per step, shell-escaped.
        var displayLines: [String] {
            let prefix = environment.keys.sorted().map { "\($0)=\(SnippetEscape.shell(environment[$0] ?? ""))" }
            return steps.map { step in
                (prefix + [SnippetEscape.shell(step.executable)] + step.arguments.map(SnippetEscape.shell))
                    .joined(separator: " ")
            }
        }
    }

    enum PlanError: Error, Equatable {
        case notRunnable, emptyPlan, programNotAllowed(String), programMissing(String)
    }

    static func command(for plan: SkillInstallPlan, resolve: (String) -> String?) -> Result<Command, PlanError> {
        guard plan.runnable else { return .failure(.notRunnable) }
        guard !plan.steps.isEmpty else { return .failure(.emptyPlan) }
        var steps: [ResolvedStep] = []
        for step in plan.steps {
            let program = step.argv.first ?? ""
            guard allowedPrograms.contains(program) else { return .failure(.programNotAllowed(program)) }
            guard let path = resolve(program) else { return .failure(.programMissing(program)) }
            steps.append(ResolvedStep(executable: path, arguments: Array(step.argv.dropFirst()),
                                      tolerateFailure: step.tolerateFailure))
        }
        var env = plan.env
        env["CICADA_CAPTURE"] = "off"
        return .success(Command(steps: steps, environment: env))
    }

    static func resolveProgram(_ name: String,
                               path: String? = ProcessInfo.processInfo.environment["PATH"],
                               home: URL = FileManager.default.homeDirectoryForCurrentUser,
                               isExecutable: (String) -> Bool = { FileManager.default.isExecutableFile(atPath: $0) }) -> String? {
        let fallback = fallbackDirectories.map { $0.hasPrefix("~/") ? home.appendingPathComponent(String($0.dropFirst(2))).path : $0 }
        let dirs = (path ?? "").split(separator: ":").map(String.init) + fallback
        for dir in dirs where !dir.isEmpty {
            let candidate = (dir as NSString).appendingPathComponent(name)
            if isExecutable(candidate) { return candidate }
        }
        return nil
    }

    static func environment(for command: Command,
                            base: [String: String] = ProcessInfo.processInfo.environment) -> [String: String] {
        var env = base
        for (key, value) in command.environment { env[key] = value }
        var lead: [String] = []
        for step in command.steps {
            let dir = (step.executable as NSString).deletingLastPathComponent
            if !lead.contains(dir) { lead.append(dir) }
        }
        env["PATH"] = (lead + [base["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin"]).joined(separator: ":")
        return env
    }

    struct StepResult: Equatable {
        let status: Int32
        let output: String
    }

    enum Outcome: Equatable {
        case succeeded(output: String)
        case failed(output: String)
    }

    typealias Runner = (ResolvedStep, [String: String]) async -> StepResult

    static func run(_ command: Command, runner: Runner = runProcess) async -> Outcome {
        let env = environment(for: command)
        var transcript: [String] = []
        for step in command.steps {
            if Task.isCancelled { return .failed(output: "Cancelled.") }
            let result = await runner(step, env)
            transcript.append(result.output.trimmingCharacters(in: .whitespacesAndNewlines))
            if result.status != 0 && !step.tolerateFailure { return .failed(output: tail(transcript)) }
        }
        return .succeeded(output: tail(transcript))
    }

    static func tail(_ parts: [String], lines: Int = 20) -> String {
        parts.joined(separator: "\n").components(separatedBy: "\n").suffix(lines).joined(separator: "\n")
    }

    /// One step as a child process: argv, never a shell; output collected as it
    /// arrives (a full pipe would otherwise stall the child); killed at the
    /// timeout or when the task is cancelled.
    static func runProcess(_ step: ResolvedStep, _ env: [String: String]) async -> StepResult {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: step.executable)
        process.arguments = step.arguments
        process.environment = env
        process.standardInput = FileHandle.nullDevice
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        let buffer = OutputBuffer()
        pipe.fileHandleForReading.readabilityHandler = { buffer.append($0.availableData) }
        return await withTaskCancellationHandler {
            await withCheckedContinuation { continuation in
                process.terminationHandler = { p in
                    pipe.fileHandleForReading.readabilityHandler = nil
                    buffer.append(pipe.fileHandleForReading.readDataToEndOfFile())
                    continuation.resume(returning: StepResult(status: p.terminationStatus, output: buffer.text))
                }
                do {
                    try process.run()
                    // Cancelled between the check in `run` and this launch:
                    // `onCancel` already ran and found nothing to stop.
                    if Task.isCancelled { process.terminate() }
                    DispatchQueue.global().asyncAfter(deadline: .now() + timeout) {
                        if process.isRunning { process.terminate() }
                    }
                } catch {
                    continuation.resume(returning: StepResult(status: -1, output: error.localizedDescription))
                }
            }
        } onCancel: {
            if process.isRunning { process.terminate() }
        }
    }

    private final class OutputBuffer: @unchecked Sendable {
        private let lock = NSLock()
        private var data = Data()
        func append(_ chunk: Data) { lock.lock(); data.append(chunk); lock.unlock() }
        var text: String { lock.lock(); defer { lock.unlock() }; return String(decoding: data, as: UTF8.self) }
    }

    // MARK: Cicada's own bundles

    static let markerFile = ".cicada-managed.json"

    enum Target: String, CaseIterable, Identifiable {
        case claudeCode = "claude-code", agents
        var id: String { rawValue }
        var label: String { self == .claudeCode ? "Claude Code" : "Codex and other agents" }
        var mark: String { self == .claudeCode ? "claude-code" : "codex" }
        func folder(home: URL, bundle: CicadaSkillBundle) -> URL {
            let root = self == .claudeCode ? ".claude/skills" : ".agents/skills"
            return home.appendingPathComponent(root).appendingPathComponent(bundle.rawValue)
        }
    }

    struct Marker: Codable, Equatable {
        let sha256: String
        let source: String
    }

    enum OwnState: Equatable {
        case sourceMissing, notInstalled, current, updateAvailable, changedByYou
        case installedByHand(sameAsCicada: Bool)
    }

    enum OwnError: Error, Equatable { case sourceMissing, wouldOverwriteYourCopy, notCicadasCopy }

    static func state(installedHash: String?, markerHash: String?, bundledHash: String?) -> OwnState {
        guard let installed = installedHash else { return bundledHash == nil ? .sourceMissing : .notInstalled }
        guard let marker = markerHash else { return .installedByHand(sameAsCicada: installed == bundledHash) }
        guard installed == marker else { return .changedByYou }
        if let bundled = bundledHash, bundled != installed { return .updateAvailable }
        return .current
    }

    static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private static func hashes(_ bundle: CicadaSkillBundle, _ target: Target, home: URL, installRoot: URL)
        -> (installed: String?, marker: String?, bundled: String?, source: Data?) {
        let folder = target.folder(home: home, bundle: bundle)
        let source = try? Data(contentsOf: installRoot.appendingPathComponent(bundle.sourcePath))
        let installed = (try? Data(contentsOf: folder.appendingPathComponent("SKILL.md"))).map(sha256)
        let marker = (try? Data(contentsOf: folder.appendingPathComponent(markerFile)))
            .flatMap { try? JSONDecoder().decode(Marker.self, from: $0) }?.sha256
        return (installed, marker, source.map(sha256), source)
    }

    static func ownState(_ bundle: CicadaSkillBundle, _ target: Target, home: URL, installRoot: URL) -> OwnState {
        let h = hashes(bundle, target, home: home, installRoot: installRoot)
        return state(installedHash: h.installed, markerHash: h.marker, bundledHash: h.bundled)
    }

    static func install(_ bundle: CicadaSkillBundle, _ target: Target, home: URL, installRoot: URL) throws {
        let h = hashes(bundle, target, home: home, installRoot: installRoot)
        guard let source = h.source, let bundled = h.bundled else { throw OwnError.sourceMissing }
        switch state(installedHash: h.installed, markerHash: h.marker, bundledHash: bundled) {
        case .notInstalled, .updateAvailable, .current, .installedByHand(sameAsCicada: true): break
        default: throw OwnError.wouldOverwriteYourCopy
        }
        let folder = target.folder(home: home, bundle: bundle)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try source.write(to: folder.appendingPathComponent("SKILL.md"), options: .atomic)
        let marker = try JSONEncoder().encode(Marker(sha256: bundled, source: bundle.sourcePath))
        try marker.write(to: folder.appendingPathComponent(markerFile), options: .atomic)
    }

    static func remove(_ bundle: CicadaSkillBundle, _ target: Target, home: URL, installRoot: URL) throws {
        let h = hashes(bundle, target, home: home, installRoot: installRoot)
        guard let installed = h.installed, installed == h.marker else { throw OwnError.notCicadasCopy }
        let folder = target.folder(home: home, bundle: bundle)
        try FileManager.default.removeItem(at: folder.appendingPathComponent("SKILL.md"))
        try? FileManager.default.removeItem(at: folder.appendingPathComponent(markerFile))
        if (try? FileManager.default.contentsOfDirectory(atPath: folder.path))?.isEmpty == true {
            try? FileManager.default.removeItem(at: folder)
        }
    }
}

/// Cicada's two hand-written skills, read from the checkout (G112 compiles more
/// later; they will ride the same writer).
enum CicadaSkillBundle: String, CaseIterable, Identifiable {
    case cicada
    case cicadaLibrarian = "cicada-librarian"

    var id: String { rawValue }
    var sourcePath: String { self == .cicada ? "SKILL.md" : "skills/cicada-librarian/SKILL.md" }
    var title: String { self == .cicada ? "Recall and save" : "Tidy as you work" }
    var summary: String {
        self == .cicada
            ? "Tells your agent when to look things up in Cicada and when to save."
            : "Lets your agent file what you just did into Cicada, the way Sleep would."
    }
}
