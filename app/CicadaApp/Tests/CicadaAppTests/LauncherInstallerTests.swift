import XCTest
@testable import CicadaApp

/// G182 item 2 — the stable launchers in `<CICADA_HOME>/bin`. Every write goes to a temp `CICADA_HOME`; the scripts
/// that run here run a fake backend inside a temp "bundle", never anything of the person's.
final class LauncherInstallerTests: XCTestCase {
    private var temp: URL!

    override func setUpWithError() throws {
        temp = FileManager.default.temporaryDirectory.appendingPathComponent("launchers-\(UUID())")
        try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: temp)
    }

    /// A release runtime whose bundle and home both live under `temp`.
    private func release(bundle: String? = nil, port: String = "8000") -> CicadaRuntime {
        let bundle = bundle ?? temp.appendingPathComponent("Cicada.app").path
        return CicadaRuntime.resolve(
            infoValue: { $0 == CicadaRuntime.distributionInfoKey ? "release" : nil }, bundlePath: bundle,
            environment: ["CICADA_HOME": temp.appendingPathComponent("home").path, "CICADA_PORT": port],
            storedPort: 0, homeDirectory: temp, fileExists: { $0.hasSuffix("/backend/bin/cicada-backend") })
    }

    func testTheScriptQuotesThePathAndPinsThePort() {
        let script = LauncherInstaller.launcherScript(name: "cicada-mcp", bundlePath: "/Users/x/My Apps/Rod's Cicada.app",
                                                      port: 8123)
        XCTAssertTrue(script.hasPrefix("#!/bin/sh\n"))
        XCTAssertTrue(script.contains(
            "\ntarget='/Users/x/My Apps/Rod'\\''s Cicada.app/Contents/Resources/backend/bin/cicada-mcp'\n"), script)
        XCTAssertTrue(script.contains(": \"${CICADA_PORT:=8123}\"; export CICADA_PORT\n"))
        XCTAssertTrue(script.contains("exec \"$target\" \"$@\"\n"))
        XCTAssertTrue(script.contains("exit 127"))
        XCTAssertTrue(script.contains("(G182)"))
        XCTAssertEqual(LauncherInstaller.singleQuoted("a'b"), #"'a'\''b'"#)
    }

    func testTheWriterIsAtomicIdempotentAndExecutable() throws {
        let runtime = release()
        let fm = FileManager.default
        XCTAssertEqual(LauncherInstaller.install(runtime: runtime), .wrote(CicadaRuntime.launcherNames))
        for name in CicadaRuntime.launcherNames {
            let path = runtime.binDir.appendingPathComponent(name).path
            XCTAssertEqual(fm.contents(atPath: path),
                           Data(LauncherInstaller.launcherScript(name: name, bundlePath: runtime.bundlePath, port: 8000).utf8))
            let mode = try XCTUnwrap(fm.attributesOfItem(atPath: path)[.posixPermissions] as? NSNumber).intValue
            XCTAssertEqual(mode, 0o755, name)
        }
        XCTAssertEqual(try fm.contentsOfDirectory(atPath: runtime.binDir.path).sorted(),
                       CicadaRuntime.launcherNames.sorted(), "no temp file is left behind")
        XCTAssertEqual(LauncherInstaller.install(runtime: runtime), .wrote([]), "unchanged content is not rewritten")

        // A launcher another copy of the app wrote (or a stale mode) is repaired, and only that one.
        let mcp = runtime.binDir.appendingPathComponent("cicada-mcp").path
        try Data("#!/bin/sh\nexit 0\n".utf8).write(to: URL(fileURLWithPath: mcp))
        try fm.setAttributes([.posixPermissions: NSNumber(value: 0o644)],
                             ofItemAtPath: runtime.binDir.appendingPathComponent("cicada-hook").path)
        XCTAssertEqual(LauncherInstaller.install(runtime: runtime), .wrote(["cicada-mcp", "cicada-hook"]))
        // A new port is a new script.
        XCTAssertEqual(LauncherInstaller.install(runtime: release(port: "8124")), .wrote(CicadaRuntime.launcherNames))
    }

    func testADeveloperBuildWritesNothing() {
        let developer = CicadaRuntime.developer(codeRoot: URL(fileURLWithPath: "/R"),
                                                cicadaHome: temp.appendingPathComponent("home"))
        XCTAssertEqual(LauncherInstaller.install(runtime: developer), .skipped)
        XCTAssertFalse(FileManager.default.fileExists(atPath: temp.appendingPathComponent("home").path))
    }

    func testAnUnwritableHomeIsReportedNeverThrown() {
        let blocker = temp.appendingPathComponent("home")
        FileManager.default.createFile(atPath: blocker.path, contents: Data())   // a file where the folder should be
        guard case .failed = LauncherInstaller.install(runtime: release()) else { return XCTFail("say so, don't crash") }
    }

    /// The scripts themselves, run by `/bin/sh`: the arguments and the port reach the bundled entry point, and a
    /// bundle that moved away says how to repair it.
    func testTheLauncherExecsTheBundledEntryPoint() throws {
        let bundle = temp.appendingPathComponent("My Apps/Rod's Cicada.app")
        let bin = CicadaRuntime.bundledBin(bundlePath: bundle.path)
        try FileManager.default.createDirectory(at: bin, withIntermediateDirectories: true)
        let fake = bin.appendingPathComponent("cicada-hook")
        try Data("#!/bin/sh\necho \"port=$CICADA_PORT args=$*\"\n".utf8).write(to: fake)
        try FileManager.default.setAttributes([.posixPermissions: NSNumber(value: 0o755)], ofItemAtPath: fake.path)
        let runtime = release(bundle: bundle.path, port: "8222")
        LauncherInstaller.install(runtime: runtime)
        let launcher = runtime.binDir.appendingPathComponent("cicada-hook").path

        let ran = try run(launcher, ["capture", "--harness", "claude-code"], env: [:])
        XCTAssertEqual(ran.status, 0)
        XCTAssertEqual(ran.out, "port=8222 args=capture --harness claude-code\n")
        XCTAssertEqual(try run(launcher, [], env: ["CICADA_PORT": "9001"]).out, "port=9001 args=\n",
                       "a port the caller set wins over the one baked in")

        try FileManager.default.removeItem(at: bundle)
        let gone = try run(launcher, [], env: [:])
        XCTAssertEqual(gone.status, 127)
        XCTAssertTrue(gone.err.contains("Open Cicada again"), gone.err)
        XCTAssertTrue(gone.err.contains(bundle.path), gone.err)
    }

    private func run(_ path: String, _ args: [String], env: [String: String]) throws
        -> (status: Int32, out: String, err: String) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: path)
        process.arguments = args
        process.environment = ["PATH": "/usr/bin:/bin"].merging(env) { _, new in new }
        let out = Pipe(), err = Pipe()
        process.standardOutput = out
        process.standardError = err
        try process.run()
        process.waitUntilExit()
        return (process.terminationStatus,
                String(decoding: out.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self),
                String(decoding: err.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self))
    }
}
