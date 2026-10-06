import Foundation

/// Runs the fixed, read-only git commands in a repo a page declares, as Cicada's own child — the app half of G-repo.
///
/// The backend used to run these itself; under launchd its interpreter is what macOS names, so a repo under
/// `~/Documents` made the Mac ask whether "python3.12" may read the folder. Run from here, the prompt names Cicada
/// (the `~/Library` rail: the app reads the Mac, the backend parses). The raw outputs are posted to
/// `POST /entities/{id}/repos/observed`, where `repo_context.parse_snapshot` — the one parser — reads them.
///
/// The command list is `repo_context.REPO_COMMANDS`, pinned on both sides by
/// `api/tests/fixtures/repo_commands.json` — the app never runs an argv the backend sends. `inside` runs first and
/// nothing else runs unless it prints `true`. Every command: `git -c core.fsmonitor=false -C <path> …` with
/// `GIT_OPTIONAL_LOCKS=0` (a status never rewrites the index), `LC_ALL=C` (the backend reads a refusal in
/// English), 2 s each, the child killed when the card's Task is cancelled.
///
/// Tests never run git on the person's folders: `observe(…, run:)` takes the runner as its seam.
enum GitRunner {
    /// Where a real git lives, in order. Never `/usr/bin/git`: on a Mac without the developer tools that shim pops
    /// the "install command line developer tools" dialog. None found → `git_unavailable`, nothing run.
    static let candidates = [
        "/Library/Developer/CommandLineTools/usr/bin/git",
        "/Applications/Xcode.app/Contents/Developer/usr/bin/git",
        "/opt/homebrew/bin/git",
        "/usr/local/bin/git",
    ]

    static let prefix = ["-c", "core.fsmonitor=false"]

    struct Command: Equatable, Sendable {
        let key: String
        let args: [String]
    }

    static let commands: [Command] = [
        Command(key: "inside", args: ["rev-parse", "--is-inside-work-tree"]),
        Command(key: "remote", args: ["remote", "get-url", "origin"]),
        Command(key: "branch", args: ["rev-parse", "--abbrev-ref", "HEAD"]),
        Command(key: "origin_head", args: ["symbolic-ref", "refs/remotes/origin/HEAD"]),
        Command(key: "status", args: ["status", "--porcelain=v1", "--branch"]),
        Command(key: "worktrees", args: ["worktree", "list", "--porcelain"]),
        Command(key: "common_dir", args: ["rev-parse", "--path-format=absolute", "--git-common-dir"]),
        Command(key: "last_commit", args: ["log", "-1", "--format=%H%x1f%an%x1f%aI%x1f%s"]),
    ]

    static let timeout: TimeInterval = 2
    /// `schemas.REPO_OUTPUT_MAX` / `REPO_STDERR_MAX`, in UTF-8 bytes (never more characters than the server counts).
    static let stdoutLimit = 64 * 1024
    static let stderrLimit = 4 * 1024

    typealias Runner = @Sendable (_ executable: String, _ arguments: [String], _ environment: [String: String],
                                  _ timeout: TimeInterval) async -> ChildProcess.Output

    static let runProcess: Runner = { executable, arguments, environment, timeout in
        await ChildProcess.run(URL(fileURLWithPath: executable), arguments: arguments, environment: environment,
                               timeout: timeout)
    }

    /// G182 — the person's own git first; a release's bundled git (`CicadaRuntime.bundledGit`) only as the last
    /// resort, so a Mac without the developer tools still reads its repos. Never `/usr/bin/git` in either build.
    static func candidates(bundledGit: String?) -> [String] {
        candidates + [bundledGit].compactMap { $0 }
    }

    /// The first real git on this Mac, or nil.
    static func executable(bundledGit: String? = CicadaRuntime.current.bundledGit,
                           isExecutable: (String) -> Bool = { FileManager.default.isExecutableFile(atPath: $0) })
        -> String? {
        candidates(bundledGit: bundledGit).first(where: isExecutable)
    }

    struct CommandOutput: Equatable, Sendable {
        let rc: Int32
        let stdout: String
        let stderr: String
    }

    /// What is posted for one declared repo: `path` exactly as the page declares it.
    struct Observation: Equatable, Sendable {
        let path: String
        let device: String?
        var outputs: [String: CommandOutput] = [:]
        /// `git_unavailable` | `timeout` | `missing` — why there is nothing to parse.
        var error: String?

        var json: [String: Any] {
            var out: [String: Any] = [
                "path": path,
                "outputs": outputs.mapValues { ["rc": Int($0.rc), "stdout": $0.stdout, "stderr": $0.stderr] },
            ]
            if let device { out["device"] = device }
            if let error { out["error"] = error }
            return out
        }
    }

    static var environment: [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["GIT_OPTIONAL_LOCKS"] = "0"
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["CICADA_CAPTURE"] = "off"
        env["LANG"] = "C"
        env["LC_ALL"] = "C"
        return env
    }

    /// Runs the list in one declared repo. Never throws: every failure is an `error` or a missing key.
    static func observe(path declared: String, device: String?, git: String?,
                        run: Runner = runProcess) async -> Observation {
        var observation = Observation(path: declared, device: device)
        let path = LocationLister.expanded(declared)
        // A relative path names no folder here; never resolve it against the app's own cwd.
        guard path.hasPrefix("/") else {
            observation.error = "missing"
            return observation
        }
        guard let git else {
            observation.error = "git_unavailable"
            return observation
        }
        let env = environment
        for command in commands {
            if Task.isCancelled { break }
            let out = await run(git, prefix + ["-C", path] + command.args, env, timeout)
            let first = command.key == "inside"
            if out.cancelled { break }
            if out.launchFailed || out.timedOut {
                if first { observation.error = out.launchFailed ? "git_unavailable" : "timeout" }
                if first { break } else { continue }
            }
            observation.outputs[command.key] = CommandOutput(
                rc: out.status,
                stdout: capped(out.stdout, bytes: stdoutLimit),
                stderr: first ? capped(out.stderr, bytes: stderrLimit) : "")
            if first && !(out.status == 0 && out.stdout.trimmingCharacters(in: .whitespacesAndNewlines) == "true") {
                break
            }
        }
        return observation
    }

    /// Every declared repo: this Mac's (as the backend decided, `RepoDeclaration.isOnThisMac`) are observed; another
    /// Mac's are posted with no outputs, and the backend answers `other_device` from the declaration alone. One
    /// lookup of git for them all.
    static func observeAll(_ declarations: RepoDeclarationList, run: Runner = runProcess,
                           git: String? = GitRunner.executable()) async -> [Observation] {
        var out: [Observation] = []
        for repo in declarations.repos {
            if Task.isCancelled { break }
            if !repo.isOnThisMac(thisDevice: declarations.thisDevice) {
                out.append(Observation(path: repo.path, device: repo.device))
            } else {
                out.append(await observe(path: repo.path, device: repo.device, git: git, run: run))
            }
        }
        return out
    }

    /// At most `bytes` of UTF-8, cut after the last whole line, so a porcelain listing never ends mid-entry. Past
    /// the cap a dirty count is a floor.
    static func capped(_ text: String, bytes: Int) -> String {
        let data = Data(text.utf8)
        guard data.count > bytes else { return text }
        let head = data.prefix(bytes)
        if let newline = head.lastIndex(of: UInt8(ascii: "\n")) {
            return String(decoding: head[head.startIndex...newline], as: UTF8.self)
        }
        // One line longer than the cap: keep whole scalars only.
        var kept = ""
        var used = 0
        for scalar in text.unicodeScalars {
            let size = String(scalar).utf8.count
            if used + size > bytes { break }
            kept.unicodeScalars.append(scalar)
            used += size
        }
        return kept
    }
}
