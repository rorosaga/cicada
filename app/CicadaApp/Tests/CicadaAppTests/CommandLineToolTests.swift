import SwiftUI
import XCTest
@testable import CicadaApp

/// G180 unit 3 (TODO ruling 21) — Settings → General's *Install the command-line tool*: one link,
/// `~/.local/bin/cicada`, no admin. The target follows the runtime (a release's stable launcher, a developer
/// checkout's `scripts/cicada`); a working link or a file is never replaced; success is never claimed for a missing
/// target. Every path lives under a temp home — the person's `~/.local/bin` and `~/.cicada` are never touched.
final class CommandLineToolTests: XCTestCase {
    private var temp: URL!
    private let fm = FileManager.default

    override func setUpWithError() throws {
        temp = fm.temporaryDirectory.appendingPathComponent("cli-tool-\(UUID())").resolvingSymlinksInPath()
        try fm.createDirectory(at: temp, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws { try? fm.removeItem(at: temp) }

    private var home: URL { temp.appendingPathComponent("home") }
    private var link: URL { CommandLineTool.linkPath(home: home) }

    @discardableResult
    private func executable(_ url: URL, _ body: String = "#!/bin/sh\necho hi\n") throws -> URL {
        try fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        fm.createFile(atPath: url.path, contents: Data(body.utf8), attributes: [.posixPermissions: 0o755])
        return url
    }

    // MARK: Target

    func testTheTargetFollowsTheRuntime() throws {
        let bin = temp.appendingPathComponent("home/.cicada/bin"), root = temp.appendingPathComponent("checkout")
        XCTAssertEqual(CommandLineTool.target(isRelease: true, launchersAreStable: true, binDir: bin, codeRoot: root),
                       .unavailable(Copy.cliToolWaitForLauncher), "a release whose launcher isn't written yet")
        try executable(bin.appendingPathComponent("cicada"))
        XCTAssertEqual(CommandLineTool.target(isRelease: true, launchersAreStable: true, binDir: bin, codeRoot: root),
                       .available(bin.appendingPathComponent("cicada")))
        XCTAssertEqual(CommandLineTool.target(isRelease: true, launchersAreStable: false, binDir: bin, codeRoot: root),
                       .unavailable(Copy.cliToolMoveApp), "a translocated copy never gets a link")
        XCTAssertEqual(CommandLineTool.target(isRelease: false, launchersAreStable: true, binDir: bin, codeRoot: root),
                       .unavailable(Copy.cliToolNoCheckoutLauncher))
        try executable(root.appendingPathComponent("scripts/cicada"))
        XCTAssertEqual(CommandLineTool.target(isRelease: false, launchersAreStable: true, binDir: bin, codeRoot: root),
                       .available(root.appendingPathComponent("scripts/cicada")),
                       "a developer build links the checkout's launcher, never ~/.cicada/bin it doesn't write")
    }

    // MARK: State

    func testEveryState() throws {
        let target = try executable(temp.appendingPathComponent("release/bin/cicada"))
        XCTAssertEqual(CommandLineTool.state(target: .available(target), home: home, onPath: true), .notInstalled)

        try fm.createDirectory(at: link.deletingLastPathComponent(), withIntermediateDirectories: true)
        try fm.createSymbolicLink(at: link, withDestinationURL: temp.appendingPathComponent("gone"))
        XCTAssertEqual(CommandLineTool.state(target: .available(target), home: home, onPath: true), .notInstalled,
                       "a dangling link is as good as none")
        try fm.removeItem(at: link)

        try fm.createSymbolicLink(at: link, withDestinationURL: target)
        XCTAssertEqual(CommandLineTool.state(target: .available(target), home: home, onPath: true), .installed(onPath: true))
        XCTAssertEqual(CommandLineTool.state(target: .available(target), home: home, onPath: false), .installed(onPath: false))
        try fm.removeItem(at: link)

        let other = try executable(temp.appendingPathComponent("another checkout/scripts/cicada"))
        try fm.createSymbolicLink(at: link, withDestinationURL: other)
        XCTAssertEqual(CommandLineTool.state(target: .available(target), home: home, onPath: true), .elsewhere(other.path))
        try fm.removeItem(at: link)

        fm.createFile(atPath: link.path, contents: Data("notes\n".utf8))
        XCTAssertEqual(CommandLineTool.state(target: .available(target), home: home, onPath: true), .blocked)
        XCTAssertEqual(CommandLineTool.state(target: .unavailable("why"), home: home, onPath: true), .unavailable("why"))
    }

    // MARK: Install

    func testInstallLinksOnceAndNeverReplacesWhatWorks() throws {
        let target = try executable(temp.appendingPathComponent("release/bin/cicada"))
        XCTAssertEqual(CommandLineTool.install(target: .available(target), home: home, onPath: true), .installed(onPath: true))
        XCTAssertEqual(try fm.destinationOfSymbolicLink(atPath: link.path), target.path)
        XCTAssertEqual(CommandLineTool.install(target: .available(target), home: home, onPath: true), .installed(onPath: true),
                       "idempotent")

        try fm.removeItem(at: link)
        try fm.createSymbolicLink(at: link, withDestinationURL: temp.appendingPathComponent("gone"))
        XCTAssertEqual(CommandLineTool.install(target: .available(target), home: home, onPath: false), .installed(onPath: false),
                       "a dangling link is rewritten")

        try fm.removeItem(at: link)
        let other = try executable(temp.appendingPathComponent("elsewhere/cicada"))
        try fm.createSymbolicLink(at: link, withDestinationURL: other)
        XCTAssertEqual(CommandLineTool.install(target: .available(target), home: home, onPath: true), .elsewhere(other.path))
        XCTAssertEqual(try fm.destinationOfSymbolicLink(atPath: link.path), other.path, "left alone")

        try fm.removeItem(at: link)
        fm.createFile(atPath: link.path, contents: Data("notes\n".utf8))
        XCTAssertEqual(CommandLineTool.install(target: .available(target), home: home, onPath: true), .blocked)
        XCTAssertEqual(String(decoding: try Data(contentsOf: link), as: UTF8.self), "notes\n", "left alone")

        try fm.removeItem(at: link)
        XCTAssertEqual(CommandLineTool.install(target: .unavailable("why"), home: home, onPath: true), .unavailable("why"))
        XCTAssertFalse(fm.fileExists(atPath: link.path), "nothing is linked to a target that isn't there")
    }

    // MARK: PATH

    func testThePathCheckReadsTheProfilesWithoutRunningAShell() throws {
        XCTAssertFalse(ShellPath.includesLocalBin(home: home, appPath: "/usr/bin:/bin", read: { _ in nil }))
        XCTAssertTrue(ShellPath.includesLocalBin(home: home, appPath: "/usr/bin:\(home.path)/.local/bin", read: { _ in nil }))
        XCTAssertTrue(ShellPath.includesLocalBin(home: home, appPath: "/usr/bin", read: { url in
            url.lastPathComponent == ".zshrc" ? "export PATH=\"$HOME/.local/bin:$PATH\"\n" : nil
        }))
        XCTAssertFalse(ShellPath.includesLocalBin(home: home, appPath: "/usr/bin", read: { url in
            url.lastPathComponent == ".zshrc" ? "# .local/bin is mentioned only in a comment\nalias ll='ls -l'\n" : nil
        }), "a comment is not a PATH entry")
        XCTAssertTrue(ShellPath.includesLocalBin(home: home, appPath: "/usr/bin", read: { url in
            url.path == "/etc/paths" ? "/usr/bin\n\(self.home.path)/.local/bin\n" : nil
        }))
    }

    // MARK: Copy

    func testTheCopyIsProviderNeutral() {
        let words = [Copy.cliToolTitle, Copy.cliToolInstall, Copy.cliToolInstallHelp, Copy.cliToolPathLine,
                     Copy.cliToolWaitForLauncher, Copy.cliToolMoveApp, Copy.cliToolNoCheckoutLauncher]
            + [CommandLineToolState.notInstalled, .installed(onPath: true), .installed(onPath: false),
               .elsewhere("/x/cicada"), .blocked, .unavailable("u")].map(Copy.cliToolDetail)
        for line in words {
            for name in ["Claude", "Codex", "ChatGPT", "Ollama", "Cursor"] { XCTAssertFalse(line.contains(name), line) }
        }
        XCTAssertTrue(Copy.cliToolDetail(.notInstalled).contains("~/.local/bin/cicada"))
    }

    func testTheRowIsIndexedUnderGeneral() {
        XCTAssertTrue(SettingsIndex.staticEntries.contains { $0.id == .commandLineTool && $0.section == .general })
    }

    // MARK: Offscreen renders (never the app)

    @MainActor
    func testRenderTheRowForReview() throws {
        guard let dir = ProcessInfo.processInfo.environment["G180_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set G180_RENDER_DIR to write the review renders")
        }
        try fm.createDirectory(atPath: dir, withIntermediateDirectories: true)
        defer { CicadaTheme.mode = .dark; CicadaTheme.uiScale = 1 }
        let states: [(String, CommandLineToolState)] = [
            ("not-installed", .notInstalled), ("installed", .installed(onPath: true)),
            ("not-on-path", .installed(onPath: false)), ("elsewhere", .elsewhere("/opt/tools/cicada")),
            ("move-app", .unavailable(Copy.cliToolMoveApp)),
        ]
        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            for (name, state) in states {
                let view = SettingsGroupCard { CommandLineToolRow(state: state, onInstall: {}) }
                    .frame(width: 560)
                    .padding(16)
                    .background(CicadaTheme.bgBase)
                    .environment(\.colorScheme, mode == .dark ? .dark : .light)
                let renderer = ImageRenderer(content: view)
                renderer.scale = 2
                let image = try XCTUnwrap(renderer.nsImage)
                let tiff = try XCTUnwrap(image.tiffRepresentation)
                let png = try XCTUnwrap(NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:]))
                try png.write(to: URL(fileURLWithPath: dir)
                    .appendingPathComponent("cli-tool-\(name)-\(mode == .dark ? "dark" : "light").png"))
            }
        }
    }
}

/// G180 unit 3 — the release `cicada` launcher, run for real: `LauncherInstaller`'s outer shim in a temp
/// `CICADA_HOME/bin` → the bundle's inner launcher (`scripts/release/write-launchers.sh`) → `python -P -m api.cli`.
/// The "bundle" is a temp folder whose interpreter is the checkout's venv and whose `app` is the checkout.
final class CLILauncherEndToEndTests: XCTestCase {
    private var temp: URL!
    private let fm = FileManager.default
    private let repo = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()

    override func setUpWithError() throws {
        temp = fm.temporaryDirectory.appendingPathComponent("cli-e2e-\(UUID())").resolvingSymlinksInPath()
        try fm.createDirectory(at: temp, withIntermediateDirectories: true)
        guard fm.isExecutableFile(atPath: repo.appendingPathComponent("api/.venv/bin/python").path) else {
            throw XCTSkip("the checkout's venv is needed to run the CLI")
        }
    }

    override func tearDownWithError() throws { try? fm.removeItem(at: temp) }

    private func makeBundle(_ name: String) throws -> URL {
        let bundle = temp.appendingPathComponent(name)
        let backend = bundle.appendingPathComponent("Contents/Resources/backend")
        try fm.createDirectory(at: backend.appendingPathComponent("python/bin"), withIntermediateDirectories: true)
        let write = try run("/bin/bash", [repo.appendingPathComponent("scripts/release/write-launchers.sh").path,
                                          backend.appendingPathComponent("bin").path], env: [:], cwd: temp)
        XCTAssertEqual(write.status, 0, write.err)
        let py = backend.appendingPathComponent("python/bin/python3.12")
        let venv = repo.appendingPathComponent("api/.venv/bin/python").path
        fm.createFile(atPath: py.path, contents: Data("#!/bin/sh\nexec \"\(venv)\" \"$@\"\n".utf8),
                      attributes: [.posixPermissions: 0o755])
        try fm.createSymbolicLink(at: backend.appendingPathComponent("app"), withDestinationURL: repo)
        return bundle
    }

    private func runtime(bundle: URL) -> CicadaRuntime {
        CicadaRuntime.resolve(
            infoValue: { $0 == CicadaRuntime.distributionInfoKey ? "release" : nil }, bundlePath: bundle.path,
            environment: ["CICADA_HOME": temp.appendingPathComponent("home/.cicada").path, "CICADA_PORT": "49183"],
            storedPort: 0, homeDirectory: temp.appendingPathComponent("home"))
    }

    func testTheShimRunsTheCLIKeepsTheCallersFolderAndSurvivesAMove() throws {
        let bundle = try makeBundle("Cicada E2E.app")
        let rt = runtime(bundle: bundle)
        XCTAssertTrue(rt.isRelease)
        XCTAssertEqual(LauncherInstaller.install(runtime: rt), .wrote(CicadaRuntime.launcherNames))
        let cli = rt.binDir.appendingPathComponent("cicada").path
        let work = temp.appendingPathComponent("a project folder")
        try fm.createDirectory(at: work, withIntermediateDirectories: true)
        let memory = temp.appendingPathComponent("memory")
        try fm.createDirectory(at: memory, withIntermediateDirectories: true)
        let env = ["HOME": temp.appendingPathComponent("home").path, "CICADA_MEMORY_PATH": memory.path,
                   "CICADA_TELEMETRY": "off"]

        let version = try run(cli, ["--version"], env: env, cwd: work)
        XCTAssertEqual(version.status, 0, version.err)
        XCTAssertFalse(version.out.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

        let status = try run(cli, ["status", "--json"], env: env, cwd: work)
        XCTAssertEqual(status.status, 0, status.err)
        let envelope = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(status.out.utf8)) as? [String: Any])
        let data = try XCTUnwrap(envelope["data"] as? [String: Any])
        XCTAssertEqual(data["distribution"] as? String, "release")
        // The CLI reports the real path (`/private/var/…`); Foundation's resolving drops `/private`, so use realpath(3).
        let real = try XCTUnwrap(realpath(work.path, nil).map { p in defer { free(p) }; return String(cString: p) })
        XCTAssertEqual(data["caller_cwd"] as? String, real)

        // The app moved: the shim says how to repair it, and the next launch's rewrite does.
        let moved = temp.appendingPathComponent("Moved Cicada.app")
        try fm.moveItem(at: bundle, to: moved)
        let gone = try run(cli, ["--version"], env: env, cwd: work)
        XCTAssertEqual(gone.status, 127)
        XCTAssertTrue(gone.err.contains("Open Cicada again"), gone.err)
        XCTAssertEqual(LauncherInstaller.install(runtime: runtime(bundle: moved)), .wrote(CicadaRuntime.launcherNames))
        XCTAssertEqual(try run(cli, ["--version"], env: env, cwd: work).status, 0)
    }

    private func run(_ path: String, _ args: [String], env: [String: String], cwd: URL) throws
        -> (status: Int32, out: String, err: String) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: path)
        process.arguments = args
        process.currentDirectoryURL = cwd
        process.environment = ["PATH": "/usr/bin:/bin"].merging(env) { _, new in new }
        let out = Pipe(), err = Pipe()
        process.standardOutput = out
        process.standardError = err
        try process.run()
        let outData = out.fileHandleForReading.readDataToEndOfFile()
        let errData = err.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        return (process.terminationStatus, String(decoding: outData, as: UTF8.self), String(decoding: errData, as: UTF8.self))
    }
}
