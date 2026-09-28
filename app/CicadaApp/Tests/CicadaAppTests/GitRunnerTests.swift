import XCTest
@testable import CicadaApp

/// G-repo: the app runs git in a declared repo, the backend parses. Nothing here runs git on a real folder of the
/// person's — `observe(…, run:)` and `RepoCard.load` take their seams — except `testTheRealChildProcess…`, which
/// runs `/bin/echo`.
final class GitRunnerTests: XCTestCase {
    private final class Calls: @unchecked Sendable {
        private let lock = NSLock()
        private var items: [[String]] = []
        func add(_ argv: [String]) { lock.lock(); items.append(argv); lock.unlock() }
        var all: [[String]] { lock.lock(); defer { lock.unlock() }; return items }
    }

    private func out(_ status: Int32 = 0, _ stdout: String = "", _ stderr: String = "",
                     timedOut: Bool = false, launchFailed: Bool = false) -> ChildProcess.Output {
        ChildProcess.Output(status: status, stdout: stdout, stderr: stderr, timedOut: timedOut,
                            launchFailed: launchFailed)
    }

    // MARK: - The one command list

    /// `api/tests/fixtures/repo_commands.json` is `repo_context.REPO_COMMANDS`: add a command on one side only and
    /// the other goes red.
    func testTheCommandListIsTheSharedFixture() throws {
        struct Fixture: Decodable {
            struct Command: Decodable { let key: String; let args: [String] }
            let prefix: [String]
            let commands: [Command]
        }
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let file = root.appendingPathComponent("api/tests/fixtures/repo_commands.json")
        let fixture = try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: file))
        XCTAssertEqual(fixture.prefix, GitRunner.prefix)
        XCTAssertEqual(fixture.commands.map { GitRunner.Command(key: $0.key, args: $0.args) }, GitRunner.commands)
        XCTAssertGreaterThanOrEqual(GitRunner.commands.count, 8, "read from \(file.path)")
    }

    // MARK: - Which git

    func testTheShimIsNeverChosen() {
        XCTAssertFalse(GitRunner.candidates.contains("/usr/bin/git"))
        XCTAssertNil(GitRunner.executable(isExecutable: { $0 == "/usr/bin/git" }),
                     "the /usr/bin/git shim pops the developer-tools dialog")
    }

    func testResolutionOrder() {
        let all = Set(GitRunner.candidates)
        XCTAssertEqual(GitRunner.executable(isExecutable: { all.contains($0) }),
                       "/Library/Developer/CommandLineTools/usr/bin/git")
        XCTAssertEqual(GitRunner.executable(isExecutable: {
            $0 == "/Applications/Xcode.app/Contents/Developer/usr/bin/git" || $0 == "/opt/homebrew/bin/git"
        }), "/Applications/Xcode.app/Contents/Developer/usr/bin/git")
        XCTAssertEqual(GitRunner.executable(isExecutable: { $0 == "/usr/local/bin/git" }), "/usr/local/bin/git")
    }

    func testNoGitRunsNothingAndSaysSo() async {
        let calls = Calls()
        let obs = await GitRunner.observe(path: "/Users/example/src/alpha-project", device: nil, git: nil) { e, a, _, _ in
            calls.add([e] + a)
            return self.out()
        }
        XCTAssertEqual(obs.error, "git_unavailable")
        XCTAssertTrue(obs.outputs.isEmpty)
        XCTAssertTrue(calls.all.isEmpty)
    }

    func testARelativePathIsMissingAndRunsNothing() async {
        let calls = Calls()
        let obs = await GitRunner.observe(path: "src/alpha-project", device: nil, git: "/opt/homebrew/bin/git") { e, a, _, _ in
            calls.add([e] + a)
            return self.out()
        }
        XCTAssertEqual(obs.error, "missing")
        XCTAssertTrue(calls.all.isEmpty)
    }

    // MARK: - Running the list

    func testEveryCommandRunsWithTheSafetyFlagsAndTheExpandedPath() async {
        let calls = Calls()
        let envs = Calls()
        let obs = await GitRunner.observe(path: "~/src/alpha-project", device: nil, git: "/opt/homebrew/bin/git") { e, a, env, timeout in
            calls.add([e] + a)
            envs.add([env["GIT_OPTIONAL_LOCKS"] ?? "", env["CICADA_CAPTURE"] ?? "", env["LC_ALL"] ?? "", "\(timeout)"])
            return a.contains("--is-inside-work-tree") ? self.out(0, "true\n") : self.out(0, "x\n")
        }
        let home = NSHomeDirectory()
        XCTAssertEqual(calls.all.count, GitRunner.commands.count)
        for (argv, command) in zip(calls.all, GitRunner.commands) {
            XCTAssertEqual(argv, ["/opt/homebrew/bin/git", "-c", "core.fsmonitor=false", "-C",
                                  home + "/src/alpha-project"] + command.args)
        }
        XCTAssertTrue(envs.all.allSatisfy { $0 == ["0", "off", "C", "2.0"] })
        XCTAssertEqual(obs.path, "~/src/alpha-project", "posted exactly as the page declares it")
        XCTAssertEqual(Set(obs.outputs.keys), Set(GitRunner.commands.map(\.key)))
        XCTAssertNil(obs.error)
    }

    func testARefusalStopsAfterTheFirstCommandAndCarriesItsStderr() async {
        let calls = Calls()
        let refusal = "fatal: cannot change to '/Users/example/Documents/alpha': Operation not permitted\n"
        let obs = await GitRunner.observe(path: "/Users/example/Documents/alpha", device: nil, git: "/usr/local/bin/git") { e, a, _, _ in
            calls.add(a)
            return self.out(128, "", refusal)
        }
        XCTAssertEqual(calls.all.count, 1, "nothing runs after a first command that did not say true")
        XCTAssertEqual(obs.outputs["inside"], GitRunner.CommandOutput(rc: 128, stdout: "", stderr: refusal))
        XCTAssertNil(obs.error, "the backend's one parser reads the refusal as `denied`")
        XCTAssertEqual(RepoWords.status("denied"), "Not allowed to open")
        XCTAssertTrue(RepoWords.fix("denied")?.contains("Files and Folders") == true)
        XCTAssertNil(RepoWords.fix("ok"))
    }

    func testAFirstCommandTimeoutOrLaunchFailureIsTheError() async {
        let timedOut = await GitRunner.observe(path: "/x", device: nil, git: "/usr/local/bin/git") { _, _, _, _ in
            self.out(-1, timedOut: true)
        }
        XCTAssertEqual(timedOut.error, "timeout")
        XCTAssertTrue(timedOut.outputs.isEmpty)
        let failed = await GitRunner.observe(path: "/x", device: nil, git: "/usr/local/bin/git") { _, _, _, _ in
            self.out(127, launchFailed: true)
        }
        XCTAssertEqual(failed.error, "git_unavailable")
    }

    func testALaterTimeoutDropsOnlyThatKey() async {
        let obs = await GitRunner.observe(path: "/x", device: nil, git: "/usr/local/bin/git") { _, a, _, _ in
            if a.contains("--is-inside-work-tree") { return self.out(0, "true\n") }
            if a.contains("log") { return self.out(-1, timedOut: true) }
            return self.out(0, "y\n")
        }
        XCTAssertNil(obs.error)
        XCTAssertNil(obs.outputs["last_commit"])
        XCTAssertEqual(obs.outputs.count, GitRunner.commands.count - 1)
        XCTAssertEqual(obs.outputs["branch"]?.stderr, "", "only the first command's stderr is sent")
    }

    func testOutputIsCappedAtALineBoundary() {
        let line = String(repeating: "a", count: 99) + "\n"
        let big = String(repeating: line, count: 1000)  // 100 KB
        let capped = GitRunner.capped(big, bytes: GitRunner.stdoutLimit)
        XCTAssertLessThanOrEqual(capped.utf8.count, GitRunner.stdoutLimit)
        XCTAssertTrue(capped.hasSuffix("\n"))
        XCTAssertEqual(GitRunner.capped("short\n", bytes: 10), "short\n")
        XCTAssertEqual(GitRunner.capped("ééééé", bytes: 5), "éé", "whole scalars only")
    }

    // MARK: - The card's round trip

    func testAnotherMacsRepoIsPostedWithoutRunningGit() async {
        let calls = Calls()
        let declared = RepoDeclarationList(entityId: "alpha-project", thisDevice: "mac-a", repos: [
            RepoDeclaration(path: "~/src/alpha-project", device: nil),
            RepoDeclaration(path: "/Users/example/src/beta", device: "mac-b"),
            RepoDeclaration(path: "/Users/example/src/gamma", device: "mac-a"),
        ])
        let obs = await GitRunner.observeAll(declared, run: { _, a, _, _ in
            calls.add(a)
            return a.contains("--is-inside-work-tree") ? self.out(0, "false\n") : self.out()
        }, git: "/usr/local/bin/git")
        XCTAssertEqual(obs.map(\.path), ["~/src/alpha-project", "/Users/example/src/beta", "/Users/example/src/gamma"])
        XCTAssertEqual(obs[1], GitRunner.Observation(path: "/Users/example/src/beta", device: "mac-b"))
        XCTAssertEqual(calls.all.count, 2, "one first command for each repo on this Mac, none for mac-b's")
        XCTAssertFalse(calls.all.joined().contains("/Users/example/src/beta"))
    }

    /// Device drift: the backend decides which declarations are this Mac (`device: Mac`, the computer name); the app
    /// follows its answer and never compares names itself — only an older backend without it falls back.
    func testTheBackendsOnThisDeviceAnswerWinsOverTheNames() async throws {
        let calls = Calls()
        let wire = Data("""
        {"entity_id": "alpha-project", "this_device": "mac-a.local", "repos": [
          {"path": "/Users/example/src/a", "device": "Mac", "on_this_device": true},
          {"path": "/Users/example/src/b", "device": "mac-a.local", "on_this_device": false},
          {"path": "/Users/example/src/c", "device": "mac-b"}]}
        """.utf8)
        let declared = try JSONDecoder().decode(RepoDeclarationList.self, from: wire)
        XCTAssertEqual(declared.repos.map { $0.isOnThisMac(thisDevice: declared.thisDevice) }, [true, false, false])
        _ = await GitRunner.observeAll(declared, run: { _, a, _, _ in
            calls.add(a)
            return a.contains("--is-inside-work-tree") ? self.out(0, "false\n") : self.out()
        }, git: "/usr/local/bin/git")
        XCTAssertEqual(calls.all.count, 1, "git runs only in the repo the backend called this Mac's")
        XCTAssertTrue(calls.all.joined().contains("/Users/example/src/a"))
    }

    func testTheCardPostsWhatItSawAndRendersTheAnswer() async throws {
        let posted = Calls()
        let answer = try JSONDecoder().decode(RepoContextList.self, from: Data("""
        {"entity_id": "alpha-project", "repos": [{"path": "~/src/alpha-project", "status": "ok",
         "current_branch": "main", "dirty_files": 1}]}
        """.utf8)).repos
        let contexts = await RepoCard.load(
            entityId: "alpha-project",
            declarations: { _ in RepoDeclarationList(entityId: "alpha-project", thisDevice: "mac-a",
                                                     repos: [RepoDeclaration(path: "~/src/alpha-project", device: nil)]) },
            observe: { list in list.repos.map { GitRunner.Observation(path: $0.path, device: $0.device,
                                                                     error: "git_unavailable") } },
            post: { id, obs in
                posted.add([id] + obs.map(\.path))
                XCTAssertEqual(obs.first?.json["error"] as? String, "git_unavailable")
                XCTAssertNil(obs.first?.json["device"])
                return answer
            })
        XCTAssertEqual(posted.all, [["alpha-project", "~/src/alpha-project"]])
        XCTAssertEqual(contexts.map(\.currentBranch), ["main"])
    }

    func testNoDeclarationsMeansNoPostAndNoSection() async {
        let posted = Calls()
        let contexts = await RepoCard.load(
            entityId: "alpha-project",
            declarations: { _ in RepoDeclarationList(entityId: "alpha-project", thisDevice: "mac-a", repos: []) },
            observe: { _ in XCTFail("nothing to observe"); return [] },
            post: { id, _ in posted.add([id]); return [] })
        XCTAssertTrue(contexts.isEmpty)
        XCTAssertTrue(posted.all.isEmpty)
    }

    func testACancelledCardNeverPosts() async {
        let posted = Calls()
        let task = Task {
            await RepoCard.load(
                entityId: "alpha-project",
                declarations: { _ in RepoDeclarationList(entityId: "alpha-project", thisDevice: "mac-a",
                                                         repos: [RepoDeclaration(path: "/x", device: nil)]) },
                observe: { list in
                    withUnsafeCurrentTask { $0?.cancel() }
                    return list.repos.map { GitRunner.Observation(path: $0.path, device: nil, error: "timeout") }
                },
                post: { id, _ in posted.add([id]); return [] })
        }
        let contexts = await task.value
        XCTAssertTrue(contexts.isEmpty)
        XCTAssertTrue(posted.all.isEmpty, "a late answer must never land on another card")
    }

    func testTheDeclarationsDecodeLeniently() throws {
        let list = try JSONDecoder().decode(RepoDeclarationList.self, from: Data("""
        {"entity_id": "alpha-project", "this_device": "mac-a",
         "repos": [{"path": "~/src/alpha-project", "device": null, "worktrees": []}, {"path": ""}, {"device": "x"}]}
        """.utf8))
        XCTAssertEqual(list.thisDevice, "mac-a")
        XCTAssertEqual(list.repos, [RepoDeclaration(path: "~/src/alpha-project", device: nil)])
    }

    // MARK: - The shared child process

    func testTheRealChildProcessDrainsAndReportsAndCancels() async {
        let echo = await ChildProcess.run(URL(fileURLWithPath: "/bin/echo"), arguments: ["hello"], timeout: 5)
        XCTAssertEqual(echo.status, 0)
        XCTAssertEqual(echo.stdout, "hello\n")
        XCTAssertFalse(echo.timedOut || echo.launchFailed || echo.cancelled)

        let missing = await ChildProcess.run(URL(fileURLWithPath: "/nonexistent/tool"), arguments: [], timeout: 5)
        XCTAssertTrue(missing.launchFailed)
        XCTAssertEqual(missing.status, 127)

        let slow = await ChildProcess.run(URL(fileURLWithPath: "/bin/sleep"), arguments: ["5"], timeout: 0.2)
        XCTAssertTrue(slow.timedOut)

        let started = Date()
        let task = Task { await ChildProcess.run(URL(fileURLWithPath: "/bin/sleep"), arguments: ["5"], timeout: 10) }
        try? await Task.sleep(nanoseconds: 200_000_000)
        task.cancel()
        let cancelled = await task.value
        XCTAssertTrue(cancelled.cancelled)
        XCTAssertLessThan(Date().timeIntervalSince(started), 4, "cancellation kills the child")
    }
}
