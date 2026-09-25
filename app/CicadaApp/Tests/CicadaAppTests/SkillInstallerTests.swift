import XCTest
@testable import CicadaApp

/// G138 / R-O26 — the app runs only an agent's own installer, exactly as shown,
/// with capture off; and writes only Cicada's own two skills, never over a
/// changed copy.
final class SkillInstallerTests: XCTestCase {
    private func plan(_ argvs: [[String]], tolerate: [Bool]? = nil, env: [String: String] = [:], runnable: Bool = true) -> SkillInstallPlan {
        SkillInstallPlan(runnable: runnable,
                         steps: argvs.enumerated().map { SkillInstallStep(argv: $1, tolerateFailure: tolerate?[$0] ?? false) },
                         env: env)
    }

    func testOnlyTheAgentsOwnInstallersRun() {
        let resolve: (String) -> String? = { "/opt/tools/\($0)" }
        XCTAssertEqual(SkillInstaller.command(for: plan([["bash", "-c", "x"]]), resolve: resolve), .failure(.programNotAllowed("bash")))
        XCTAssertEqual(SkillInstaller.command(for: plan([["claude", "plugin", "install", "x@y"]], runnable: false), resolve: resolve), .failure(.notRunnable))
        XCTAssertEqual(SkillInstaller.command(for: plan([["npx", "skills"]]), resolve: { _ in nil }), .failure(.programMissing("npx")))
    }

    func testCaptureIsOffWhateverThePlanSaysAndTheCommandIsShownVerbatim() throws {
        let p = plan([["npx", "--yes", "skills", "add", "https://github.com/o/r/tree/abc/skills/x", "-g", "-a", "codex", "-y"]],
                     env: ["CICADA_CAPTURE": "on", "DISABLE_TELEMETRY": "1"])
        let command = try SkillInstaller.command(for: p, resolve: { "/Users/Jane Doe/.local/bin/\($0)" }).get()
        XCTAssertEqual(command.environment["CICADA_CAPTURE"], "off")
        XCTAssertEqual(command.displayLines, [
            "CICADA_CAPTURE=off DISABLE_TELEMETRY=1 '/Users/Jane Doe/.local/bin/npx' --yes skills add https://github.com/o/r/tree/abc/skills/x -g -a codex -y",
        ])
    }

    func testPathLeadsWithEachProgramsFolder() throws {
        let command = try SkillInstaller.command(for: plan([["npx", "skills"]]), resolve: { "/opt/node/bin/\($0)" }).get()
        let env = SkillInstaller.environment(for: command, base: ["PATH": "/usr/bin:/bin", "HOME": "/h"])
        XCTAssertEqual(env["PATH"], "/opt/node/bin:/usr/bin:/bin", "`npx`'s `env node` must find the node beside it")
        XCTAssertEqual(env["HOME"], "/h")
        XCTAssertEqual(env["CICADA_CAPTURE"], "off")
    }

    func testResolutionSearchesPathThenTheBackendsFallbackFolders() {
        let home = URL(fileURLWithPath: "/h")
        let found = SkillInstaller.resolveProgram("claude", path: "/usr/bin", home: home,
                                                  isExecutable: { $0 == "/h/.local/bin/claude" })
        XCTAssertEqual(found, "/h/.local/bin/claude")
        XCTAssertNil(SkillInstaller.resolveProgram("claude", path: "", home: home, isExecutable: { _ in false }))
    }

    /// A Finder-launched app has launchd's bare PATH, the backend's exact
    /// problem — so the two fallback lists must not drift.
    func testFallbackFoldersMirrorTheBackends() throws {
        let py = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("api/services/connections/base.py")
        let text = try String(contentsOf: py, encoding: .utf8)
        for dir in SkillInstaller.fallbackDirectories {
            XCTAssertTrue(text.contains("\"\(dir)\""), "\(dir) is not in _CLI_FALLBACK_DIRS")
        }
    }

    func testAToleratedStepMayFailAndAnyOtherStopsTheRun() async throws {
        let p = plan([["claude", "plugin", "marketplace", "add", "o/r"], ["claude", "plugin", "install", "x@r"]], tolerate: [true, false])
        let command = try SkillInstaller.command(for: p, resolve: { "/bin/\($0)" }).get()
        var ran: [[String]] = []
        let ok = await SkillInstaller.run(command) { step, _ in
            ran.append(step.arguments)
            return .init(status: step.arguments.contains("marketplace") ? 1 : 0, output: "fine")
        }
        XCTAssertEqual(ok, .succeeded(output: "fine\nfine"))
        XCTAssertEqual(ran.count, 2)

        let strict = try SkillInstaller.command(for: plan([["claude", "a"], ["claude", "b"]]), resolve: { "/bin/\($0)" }).get()
        ran = []
        let failed = await SkillInstaller.run(strict) { step, _ in
            ran.append(step.arguments)
            return .init(status: 2, output: "nope")
        }
        XCTAssertEqual(failed, .failed(output: "nope"))
        XCTAssertEqual(ran, [["a"]], "a failure stops before the next step")
    }

    // MARK: Cicada's own bundles

    func testOwnStateTable() {
        XCTAssertEqual(SkillInstaller.state(installedHash: nil, markerHash: nil, bundledHash: nil), .sourceMissing)
        XCTAssertEqual(SkillInstaller.state(installedHash: nil, markerHash: nil, bundledHash: "b"), .notInstalled)
        XCTAssertEqual(SkillInstaller.state(installedHash: "b", markerHash: "b", bundledHash: "b"), .current)
        XCTAssertEqual(SkillInstaller.state(installedHash: "a", markerHash: "a", bundledHash: "b"), .updateAvailable)
        XCTAssertEqual(SkillInstaller.state(installedHash: "x", markerHash: "a", bundledHash: "b"), .changedByYou)
        XCTAssertEqual(SkillInstaller.state(installedHash: "b", markerHash: nil, bundledHash: "b"), .installedByHand(sameAsCicada: true))
        XCTAssertEqual(SkillInstaller.state(installedHash: "x", markerHash: nil, bundledHash: "b"), .installedByHand(sameAsCicada: false))
    }

    func testInstallUpdateRemoveRoundTripAndAChangedCopyIsNeverTouched() throws {
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("skills-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: tmp) }
        let home = tmp.appendingPathComponent("home"), root = tmp.appendingPathComponent("repo")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try "---\nname: cicada\n---\nv1\n".write(to: root.appendingPathComponent("SKILL.md"), atomically: true, encoding: .utf8)

        XCTAssertEqual(SkillInstaller.ownState(.cicada, .claudeCode, home: home, installRoot: root), .notInstalled)
        try SkillInstaller.install(.cicada, .claudeCode, home: home, installRoot: root)
        XCTAssertEqual(SkillInstaller.ownState(.cicada, .claudeCode, home: home, installRoot: root), .current)
        let folder = SkillInstaller.Target.claudeCode.folder(home: home, bundle: .cicada)
        XCTAssertTrue(FileManager.default.fileExists(atPath: folder.appendingPathComponent(SkillInstaller.markerFile).path))

        try "---\nname: cicada\n---\nv2\n".write(to: root.appendingPathComponent("SKILL.md"), atomically: true, encoding: .utf8)
        XCTAssertEqual(SkillInstaller.ownState(.cicada, .claudeCode, home: home, installRoot: root), .updateAvailable)
        try SkillInstaller.install(.cicada, .claudeCode, home: home, installRoot: root)
        XCTAssertEqual(SkillInstaller.ownState(.cicada, .claudeCode, home: home, installRoot: root), .current)

        try "mine now".write(to: folder.appendingPathComponent("SKILL.md"), atomically: true, encoding: .utf8)
        XCTAssertEqual(SkillInstaller.ownState(.cicada, .claudeCode, home: home, installRoot: root), .changedByYou)
        XCTAssertThrowsError(try SkillInstaller.install(.cicada, .claudeCode, home: home, installRoot: root))
        XCTAssertThrowsError(try SkillInstaller.remove(.cicada, .claudeCode, home: home, installRoot: root))
        XCTAssertEqual(try String(contentsOf: folder.appendingPathComponent("SKILL.md"), encoding: .utf8), "mine now")
    }

    func testRemoveTakesOnlyWhatItWrote() throws {
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("skills-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: tmp) }
        let home = tmp.appendingPathComponent("home"), root = tmp.appendingPathComponent("repo")
        try FileManager.default.createDirectory(at: root.appendingPathComponent("skills/cicada-librarian"), withIntermediateDirectories: true)
        try "lib".write(to: root.appendingPathComponent("skills/cicada-librarian/SKILL.md"), atomically: true, encoding: .utf8)
        try SkillInstaller.install(.cicadaLibrarian, .agents, home: home, installRoot: root)
        let folder = SkillInstaller.Target.agents.folder(home: home, bundle: .cicadaLibrarian)
        try "notes".write(to: folder.appendingPathComponent("NOTES.md"), atomically: true, encoding: .utf8)
        try SkillInstaller.remove(.cicadaLibrarian, .agents, home: home, installRoot: root)
        XCTAssertFalse(FileManager.default.fileExists(atPath: folder.appendingPathComponent("SKILL.md").path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: folder.appendingPathComponent("NOTES.md").path),
                      "a file Cicada didn't write stays")
    }

    /// R-O26, final review — a skill folder linked to the checkout is never
    /// Cicada's copy: Install would write the marker into the repo and Remove
    /// would delete the tracked SKILL.md. Both refuse, even with a marker a
    /// pre-fix Install already left behind in the linked folder.
    func testASkillFolderLinkedToTheCheckoutIsNeverTouched() throws {
        let fm = FileManager.default
        let tmp = fm.temporaryDirectory.appendingPathComponent("skills-\(UUID().uuidString)")
        defer { try? fm.removeItem(at: tmp) }
        let home = tmp.appendingPathComponent("home"), root = tmp.appendingPathComponent("repo")
        let source = root.appendingPathComponent("skills/cicada-librarian")
        try fm.createDirectory(at: source, withIntermediateDirectories: true)
        try "lib".write(to: source.appendingPathComponent("SKILL.md"), atomically: true, encoding: .utf8)
        let folder = SkillInstaller.Target.claudeCode.folder(home: home, bundle: .cicadaLibrarian)
        try fm.createDirectory(at: folder.deletingLastPathComponent(), withIntermediateDirectories: true)
        try fm.createSymbolicLink(at: folder, withDestinationURL: source)

        XCTAssertEqual(SkillInstaller.ownState(.cicadaLibrarian, .claudeCode, home: home, installRoot: root),
                       .installedByHand(sameAsCicada: false))
        XCTAssertThrowsError(try SkillInstaller.install(.cicadaLibrarian, .claudeCode, home: home, installRoot: root))
        XCTAssertFalse(fm.fileExists(atPath: source.appendingPathComponent(SkillInstaller.markerFile).path),
                       "no marker written into the checkout")

        let hash = SkillInstaller.sha256(Data("lib".utf8))
        let stale = try JSONEncoder().encode(SkillInstaller.Marker(sha256: hash, source: "skills/cicada-librarian/SKILL.md"))
        try stale.write(to: source.appendingPathComponent(SkillInstaller.markerFile))
        XCTAssertThrowsError(try SkillInstaller.remove(.cicadaLibrarian, .claudeCode, home: home, installRoot: root))
        XCTAssertEqual(try String(contentsOf: source.appendingPathComponent("SKILL.md"), encoding: .utf8), "lib",
                       "the tracked SKILL.md stays")

        // A plain folder whose SKILL.md alone links into the checkout.
        let cicadaFolder = SkillInstaller.Target.agents.folder(home: home, bundle: .cicada)
        try "own".write(to: root.appendingPathComponent("SKILL.md"), atomically: true, encoding: .utf8)
        try fm.createDirectory(at: cicadaFolder, withIntermediateDirectories: true)
        try fm.createSymbolicLink(at: cicadaFolder.appendingPathComponent("SKILL.md"),
                                  withDestinationURL: root.appendingPathComponent("SKILL.md"))
        XCTAssertEqual(SkillInstaller.ownState(.cicada, .agents, home: home, installRoot: root),
                       .installedByHand(sameAsCicada: false))
        XCTAssertThrowsError(try SkillInstaller.install(.cicada, .agents, home: home, installRoot: root))
        XCTAssertThrowsError(try SkillInstaller.remove(.cicada, .agents, home: home, installRoot: root))
        XCTAssertEqual(try String(contentsOf: root.appendingPathComponent("SKILL.md"), encoding: .utf8), "own")
    }

    /// R-O26 — the app names an agent's skill folders in exactly one file.
    func testOnlyTheInstallerNamesAgentSkillFolders() throws {
        let writers = try ThemeTokenTests.swiftSources().filter { file in
            let code = try String(contentsOf: file, encoding: .utf8)
                .components(separatedBy: .newlines)
                .filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("//") }
                .joined(separator: "\n")
            return code.contains(".claude/skills") || code.contains(".agents/skills")
        }.map(\.lastPathComponent)
        XCTAssertEqual(writers, ["SkillInstaller.swift"])
    }
}
