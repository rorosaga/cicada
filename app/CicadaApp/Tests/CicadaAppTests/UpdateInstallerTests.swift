import CryptoKit
import XCTest
@testable import CicadaApp

/// G182 phase 5 — staging a verified update beside the app, the helper that swaps it in after the app quits, and the
/// failure marker the next launch reads once. Every download, tool run and spawn is a fake; the helper script is run
/// for real only against folders inside the test's own temporary directory (no launchctl line, no relaunch).
final class UpdateInstallerTests: XCTestCase {
    private var dir: URL!
    private let fm = FileManager.default

    override func setUpWithError() throws {
        dir = fm.temporaryDirectory.appendingPathComponent("UpdateInstallerTests-\(UUID().uuidString)")
        try fm.createDirectory(at: dir, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        // A test may leave a read-only folder behind; make it removable first.
        if let walker = fm.enumerator(atPath: dir.path) {
            for case let path as String in walker {
                try? fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: dir.appendingPathComponent(path).path)
            }
        }
        try? fm.removeItem(at: dir)
    }

    // MARK: Fixtures

    static func plan(installed: String = "/Applications/Cicada.app", plist: String? = nil, relaunch: Bool = false,
                     version: String = "0.3.1") -> UpdateInstaller.HelperPlan {
        let app = URL(fileURLWithPath: installed)
        return UpdateInstaller.HelperPlan(
            pid: 4242, installedApp: installed, stagedApp: UpdateInstaller.stagedURL(installedApp: app).path,
            backupApp: UpdateInstaller.backupURL(installedApp: app).path, trashDir: "/Users/x/.Trash", version: version,
            fromVersion: "0.3.0", logFile: "/Users/x/.cicada/logs/update.log",
            failureMarker: "/Users/x/.cicada/update-failed.json", deferredMarker: "/Users/x/.cicada/update-deferred.json",
            pidFile: "/Users/x/.cicada/update-helper.pid", statusURL: "http://127.0.0.1:8000/sleep/status",
            tokenFile: "/Users/x/.cicada/api_token", launchAgentPlist: plist, uid: 501, relaunch: relaunch)
    }

    /// Answers the three tool runs `stage` makes: unzip (writes an app with `info`), codesign, and the staging copy.
    final class FakeTools: AgentProcessRunning, @unchecked Sendable {
        var info: [String: Any]
        var codesignStatus: Int32 = 0
        var unzipStatus: Int32 = 0
        var calls: [[String]] = []
        let lock = NSLock()

        init(info: [String: Any]) { self.info = info }

        func run(_ argv: [String], environment: [String: String], timeout: Duration) async -> AgentProcessResult {
            lock.lock(); calls.append(argv); lock.unlock()
            let fm = FileManager.default
            switch (argv[0], argv.count) {
            case ("/usr/bin/ditto", 5):   // ditto -x -k <zip> <dir>
                guard unzipStatus == 0 else { return AgentProcessResult(status: unzipStatus, stderr: "bad zip") }
                let contents = URL(fileURLWithPath: argv[4]).appendingPathComponent("Cicada.app/Contents")
                try? fm.createDirectory(at: contents, withIntermediateDirectories: true)
                (info as NSDictionary).write(to: contents.appendingPathComponent("Info.plist"), atomically: true)
                return AgentProcessResult(status: 0, stderr: "")
            case ("/usr/bin/ditto", 3):   // ditto <app> <staged>
                do { try fm.copyItem(atPath: argv[1], toPath: argv[2]) } catch {
                    return AgentProcessResult(status: 1, stderr: "\(error)")
                }
                return AgentProcessResult(status: 0, stderr: "")
            case ("/usr/bin/codesign", _):
                return AgentProcessResult(status: codesignStatus, stderr: "")
            default:
                return AgentProcessResult(status: 127, stderr: "unexpected \(argv)")
            }
        }
    }

    static let goodInfo: [String: Any] = ["CFBundleIdentifier": "com.cicada.app", "CicadaDistribution": "release",
                                          "CFBundleShortVersionString": "0.3.1"]

    private func installer(tools: FakeTools, key: String?, zipBytes: Data, installedFolder: URL? = nil,
                           spawned: SpawnRecorder = SpawnRecorder(), downloads: ProgressBox? = nil) throws -> UpdateInstaller {
        let folder = installedFolder ?? dir.appendingPathComponent("Apps")
        try fm.createDirectory(at: folder.appendingPathComponent("Cicada.app/Contents"), withIntermediateDirectories: true)
        return UpdateInstaller(
            installedApp: folder.appendingPathComponent("Cicada.app"), bundleIdentifier: "com.cicada.app",
            publicKeyBase64: key, cicadaHome: dir.appendingPathComponent("home"), uid: 501, pid: 4242,
            launchAgentPlist: dir.appendingPathComponent("LaunchAgents/com.cicada.backend.plist"),
            trashDir: dir.appendingPathComponent("Trash"), workRoot: dir.appendingPathComponent("work"),
            download: { _, destination, progress in
                downloads?.names.append(destination.lastPathComponent)
                progress(0.5)
                try zipBytes.write(to: destination)
                progress(1)
            },
            runner: tools, spawn: spawned.spawn)
    }

    final class SpawnRecorder: @unchecked Sendable {
        var argv: [[String]] = []
        var error: Error?
        var spawn: UpdateInstaller.Spawn {
            { [self] in
                if let error { throw error }
                argv.append($0)
            }
        }
    }

    private func signed(_ bytes: Data, version: String = "0.3.1") throws -> (UpdateManifest, String) {
        let key = Curve25519.Signing.PrivateKey()
        let m = UpdateManifest(version: version, url: URL(string: "https://example.com/Cicada-\(version).zip")!,
                               size: Int64(bytes.count), sha256: UpdateVerifier.sha256Hex(bytes),
                               signature: try key.signature(for: bytes).base64EncodedString())
        return (m, key.publicKey.rawRepresentation.base64EncodedString())
    }

    // MARK: Paths

    func testTheStagedCopyIsAHiddenSiblingSoTheSwapIsARename() {
        let app = URL(fileURLWithPath: "/Applications/Cicada.app")
        XCTAssertEqual(UpdateInstaller.stagedURL(installedApp: app).path, "/Applications/.Cicada.app.update")
        XCTAssertEqual(UpdateInstaller.backupURL(installedApp: app).path, "/Applications/.Cicada.app.old")
    }

    // MARK: Validation

    func testOnlyThisAppAsAReleaseAtThePromisedVersionIsStaged() {
        XCTAssertNoThrow(try UpdateInstaller.validate(info: Self.goodInfo, bundleIdentifier: "com.cicada.app",
                                                      version: "0.3.1"))
        var other = Self.goodInfo; other["CFBundleIdentifier"] = "com.example.other"
        XCTAssertThrowsError(try UpdateInstaller.validate(info: other, bundleIdentifier: "com.cicada.app", version: "0.3.1")) {
            XCTAssertEqual($0 as? UpdateInstaller.Failure, .wrongApp)
        }
        XCTAssertThrowsError(try UpdateInstaller.validate(info: Self.goodInfo, bundleIdentifier: nil, version: "0.3.1")) {
            XCTAssertEqual($0 as? UpdateInstaller.Failure, .wrongApp, "an app that doesn't know its own id updates nothing")
        }
        var dev = Self.goodInfo; dev["CicadaDistribution"] = nil
        XCTAssertThrowsError(try UpdateInstaller.validate(info: dev, bundleIdentifier: "com.cicada.app", version: "0.3.1")) {
            XCTAssertEqual($0 as? UpdateInstaller.Failure, .notRelease)
        }
        XCTAssertThrowsError(try UpdateInstaller.validate(info: Self.goodInfo, bundleIdentifier: "com.cicada.app",
                                                          version: "0.3.2")) {
            XCTAssertEqual($0 as? UpdateInstaller.Failure, .wrongVersion(found: "0.3.1", expected: "0.3.2"))
        }
        XCTAssertThrowsError(try UpdateInstaller.validate(info: nil, bundleIdentifier: "com.cicada.app", version: "0.3.1"))
    }

    // MARK: Stage

    func testStageDownloadsVerifiesUnzipsValidatesAndCopiesBesideTheApp() async throws {
        let bytes = Data((0..<2048).map { UInt8($0 % 199) })
        var (manifest, key) = try signed(bytes)
        // A manifest whose URL ends in something hostile never names the file on disk.
        manifest = UpdateManifest(version: manifest.version, url: URL(string: "https://example.com/dl/..%2F..%2Fevil")!,
                                  size: manifest.size, sha256: manifest.sha256, signature: manifest.signature)
        let tools = FakeTools(info: Self.goodInfo)
        let downloads = ProgressBox()
        let installer = try installer(tools: tools, key: key, zipBytes: bytes, downloads: downloads)
        let progress = ProgressBox()
        let staged = try await installer.stage(manifest, progress: { progress.append($0) })
        XCTAssertEqual(staged.stagedApp.path, dir.appendingPathComponent("Apps/.Cicada.app.update").path)
        XCTAssertEqual(staged.installedApp, installer.installedApp)
        XCTAssertTrue(fm.fileExists(atPath: staged.stagedApp.appendingPathComponent("Contents/Info.plist").path))
        XCTAssertEqual(progress.values, [0.5, 1])
        XCTAssertEqual(downloads.names, ["Cicada.zip"], "always Cicada.zip, never the URL's last path component")
        XCTAssertEqual(tools.calls[0][3].hasSuffix("/Cicada.zip"), true)
        // The manifest rides beside the staged copy, so a deferred install survives a relaunch.
        let sidecar = UpdateInstaller.sidecarURL(stagedApp: staged.stagedApp)
        XCTAssertEqual(sidecar.lastPathComponent, ".Cicada.app.update.json")
        XCTAssertEqual(try JSONDecoder().decode(UpdateManifest.self, from: Data(contentsOf: sidecar)), manifest)
        XCTAssertEqual(tools.calls.map { $0[0] }, ["/usr/bin/ditto", "/usr/bin/codesign", "/usr/bin/ditto"])
        XCTAssertEqual(Array(tools.calls[0].prefix(3)), ["/usr/bin/ditto", "-x", "-k"])
        XCTAssertEqual(Array(tools.calls[1].dropLast()), ["/usr/bin/codesign", "--verify", "--strict", "--deep"])
        // The temporary folder is gone; only the staged copy remains.
        XCTAssertEqual((try? fm.contentsOfDirectory(atPath: dir.appendingPathComponent("work").path)) ?? [], [])
    }

    func testABadSignatureNeverReachesTheUnzip() async throws {
        let bytes = Data(repeating: 3, count: 512)
        let (manifest, _) = try signed(bytes)
        let stranger = Curve25519.Signing.PrivateKey().publicKey.rawRepresentation.base64EncodedString()
        let tools = FakeTools(info: Self.goodInfo)
        let installer = try installer(tools: tools, key: stranger, zipBytes: bytes)
        await assertStageFails(installer, manifest, .verify(.badSignature))
        XCTAssertTrue(tools.calls.isEmpty, "nothing is unzipped, let alone staged")
        XCTAssertFalse(fm.fileExists(atPath: UpdateInstaller.stagedURL(installedApp: installer.installedApp).path))
    }

    func testNoPublicKeyRefusesBeforeDownloading() async throws {
        let bytes = Data(repeating: 3, count: 512)
        let (manifest, _) = try signed(bytes)
        let tools = FakeTools(info: Self.goodInfo)
        await assertStageFails(try installer(tools: tools, key: nil, zipBytes: bytes), manifest, .verify(.noPublicKey))
    }

    func testAWrongAppOrAFailedCodesignIsNeverStaged() async throws {
        let bytes = Data(repeating: 9, count: 256)
        let (manifest, key) = try signed(bytes)
        var wrong = Self.goodInfo; wrong["CFBundleShortVersionString"] = "0.2.0"
        await assertStageFails(try installer(tools: FakeTools(info: wrong), key: key, zipBytes: bytes), manifest,
                               .wrongVersion(found: "0.2.0", expected: "0.3.1"))
        let unsigned = FakeTools(info: Self.goodInfo); unsigned.codesignStatus = 1
        let i = try installer(tools: unsigned, key: key, zipBytes: bytes)
        await assertStageFails(i, manifest, .codesign)
        XCTAssertFalse(fm.fileExists(atPath: UpdateInstaller.stagedURL(installedApp: i.installedApp).path))
        let broken = FakeTools(info: Self.goodInfo); broken.unzipStatus = 1
        await assertStageFails(try installer(tools: broken, key: key, zipBytes: bytes), manifest, .unzip)
    }

    func testAFolderThisAccountCantChangeFailsWithASentenceBeforeDownloading() async throws {
        let bytes = Data(repeating: 1, count: 64)
        let (manifest, key) = try signed(bytes)
        let locked = dir.appendingPathComponent("Locked")
        let tools = FakeTools(info: Self.goodInfo)
        let i = try installer(tools: tools, key: key, zipBytes: bytes, installedFolder: locked)
        try fm.setAttributes([.posixPermissions: 0o555], ofItemAtPath: locked.path)
        await assertStageFails(i, manifest, .folderNotWritable(locked.path))
        XCTAssertTrue(tools.calls.isEmpty)
        XCTAssertTrue(UpdateInstaller.Failure.folderNotWritable(locked.path).message.contains(locked.path))
    }

    // MARK: Hand off

    func testHandOffWritesTheHelperAndSpawnsItWithShell() throws {
        let spawned = SpawnRecorder()
        let i = try installer(tools: FakeTools(info: Self.goodInfo), key: "k", zipBytes: Data(), spawned: spawned)
        let staged = UpdateInstaller.stagedURL(installedApp: i.installedApp)
        try fm.createDirectory(at: staged, withIntermediateDirectories: true)
        let manifest = UpdateManifest(version: "0.3.1", url: URL(string: "https://example.com/C.zip")!, size: 1,
                                      sha256: "a", signature: "b")
        try i.handOff(StagedUpdate(manifest: manifest, stagedApp: staged, installedApp: i.installedApp), relaunch: true,
                      currentVersion: "0.3.0")
        XCTAssertEqual(spawned.argv.count, 1)
        XCTAssertEqual(spawned.argv[0][0], "/bin/sh")
        let script = try String(contentsOfFile: spawned.argv[0][1], encoding: .utf8)
        XCTAssertTrue(script.contains("relaunch=1"))
        XCTAssertTrue(script.contains("pid=4242"))
        XCTAssertFalse(script.contains("launchctl"), "no plist on disk, so no service lines")
        let mode = try fm.attributesOfItem(atPath: spawned.argv[0][1])[.posixPermissions] as? NSNumber
        XCTAssertEqual(mode?.intValue, 0o700)
    }

    func testHandOffWithoutAStagedCopyOrWhenTheSpawnFailsThrows() throws {
        let spawned = SpawnRecorder()
        let i = try installer(tools: FakeTools(info: Self.goodInfo), key: "k", zipBytes: Data(), spawned: spawned)
        let manifest = UpdateManifest(version: "0.3.1", url: URL(string: "https://example.com/C.zip")!, size: 1,
                                      sha256: "a", signature: "b")
        let staged = StagedUpdate(manifest: manifest, stagedApp: UpdateInstaller.stagedURL(installedApp: i.installedApp),
                                  installedApp: i.installedApp)
        XCTAssertThrowsError(try i.handOff(staged, relaunch: false, currentVersion: "0.3.0")) {
            XCTAssertEqual($0 as? UpdateInstaller.Failure, .stage)
        }
        try fm.createDirectory(at: staged.stagedApp, withIntermediateDirectories: true)
        spawned.error = DetachedSpawn.Failed(code: EAGAIN)
        XCTAssertThrowsError(try i.handOff(staged, relaunch: false, currentVersion: "0.3.0")) {
            guard case .helper = $0 as? UpdateInstaller.Failure else { return XCTFail("\($0)") }
        }
    }

    // MARK: The helper script's text

    func testEveryPathIsSingleQuotedEvenWithASpaceAndAQuote() {
        let script = UpdateInstaller.helperScript(Self.plan(installed: "/Users/x/My Apps/Bob's Cicada.app"))
        XCTAssertTrue(script.hasPrefix("#!/bin/sh\n"))
        XCTAssertTrue(script.contains(#"app='/Users/x/My Apps/Bob'\''s Cicada.app'"#), script)
        XCTAssertTrue(script.contains(#"staged='/Users/x/My Apps/.Bob'\''s Cicada.app.update'"#))
        XCTAssertTrue(script.contains(#"sidecar='/Users/x/My Apps/.Bob'\''s Cicada.app.update.json'"#))
        XCTAssertTrue(script.contains(#"backup='/Users/x/My Apps/.Bob'\''s Cicada.app.old'"#))
        XCTAssertTrue(script.contains(#"/bin/mv "$app" "$backup""#), "variables are always double-quoted where used")
        XCTAssertTrue(script.contains(#"/bin/mv "$staged" "$app""#))
    }

    func testTheServiceIsStoppedAndRestartedOnlyWhenAPlistIsGiven() {
        let without = UpdateInstaller.helperScript(Self.plan(plist: nil))
        XCTAssertFalse(without.contains("launchctl"))
        XCTAssertFalse(without.contains("plist="))
        XCTAssertTrue(without.contains("start_service() { return 0; }"))
        let with = UpdateInstaller.helperScript(Self.plan(plist: "/Users/x/Library/LaunchAgents/com.cicada.backend.plist"))
        XCTAssertTrue(with.contains("plist='/Users/x/Library/LaunchAgents/com.cicada.backend.plist'"))
        XCTAssertTrue(with.contains("service='gui/501/com.cicada.backend'"))
        XCTAssertTrue(with.contains(#"/bin/launchctl bootout "$service""#))
        XCTAssertTrue(with.contains(#"/bin/launchctl bootstrap 'gui/501' "$plist""#))
        XCTAssertTrue(with.contains("booted=1"))
        let bootout = with.range(of: #"/bin/launchctl bootout "$service""#)!.lowerBound
        let moveAside = with.range(of: #"/bin/mv "$app" "$backup""#)!.lowerBound
        XCTAssertLessThan(bootout, moveAside, "the service stops before its bundle moves")
        let sleepCheck = with.range(of: "if sleep_busy; then")!.lowerBound
        XCTAssertLessThan(sleepCheck, bootout, "Sleep is asked about before the service is stopped")
    }

    /// launchd refuses a bootstrap that races its own bootout: three tries a second apart, then the marker says so.
    func testTheServiceRestartIsRetriedAndAFailureIsWrittenDown() {
        let with = UpdateInstaller.helperScript(Self.plan(plist: "/p.plist"))
        XCTAssertEqual(UpdateInstaller.bootstrapTries, 3)
        XCTAssertTrue(with.contains(#"while [ "$tries" -lt 3 ]; do"#))
        XCTAssertTrue(with.contains(#"if [ "$tries" -lt 3 ]; then /bin/sleep 1; fi"#))
        XCTAssertTrue(with.contains(#"start_service || svc=', "service_stopped": true'"#), "a failed swap says it too")
        XCTAssertTrue(with.contains(#""installed": true, "service_stopped": true}"#))
        XCTAssertTrue(with.contains(LauncherInstaller.singleQuoted(Copy.Updates.helperServiceDidNotStart)))
        // After the swap, the service starts before the app reopens.
        let start = with.range(of: "if ! start_service; then")!.lowerBound
        let finish = with.range(of: "finish 0\n", options: .backwards)!.lowerBound
        XCTAssertLessThan(start, finish)
    }

    func testAFailedSwapPutsTheOldCopyBackAndLeavesTheMarker() {
        let script = UpdateInstaller.helperScript(Self.plan())
        XCTAssertTrue(script.contains(#"if [ ! -e "$app" ]; then /bin/mv "$backup" "$app""#), "the restore branch")
        XCTAssertTrue(script.contains(#"printf '{"version": "%s", "reason": "%s"%s}\n' "$version" "$1" "$svc" > "$marker""#))
        XCTAssertTrue(script.contains("marker='/Users/x/.cicada/update-failed.json'"))
        XCTAssertTrue(script.contains("log='/Users/x/.cicada/logs/update.log'"))
        XCTAssertTrue(script.contains("trash='/Users/x/.Trash'"))
        XCTAssertTrue(script.contains(#""$trash/Cicada $(/bin/date '+%Y-%m-%d %H.%M.%S').app""#))
        XCTAssertTrue(script.contains(#"while kill -0 "$pid" 2>/dev/null"#))
        XCTAssertTrue(script.contains("-ge \(UpdateInstaller.quitPolls)"))
        XCTAssertTrue(script.contains("trap '' HUP INT"))
        for reason in [Copy.Updates.helperDidNotQuit, Copy.Updates.helperMoveAside, Copy.Updates.helperMoveIn,
                       Copy.Updates.helperServiceDidNotStart] {
            XCTAssertFalse(reason.contains("\"") || reason.contains("\\"), "goes into JSON unescaped: \(reason)")
            XCTAssertTrue(script.contains(LauncherInstaller.singleQuoted(reason)), reason)
        }
    }

    /// The tester's install script may replace the bundle too: a vanished staged copy or an app that appeared at the
    /// installed path makes the helper step aside — no swap over someone else's copy, no alarming marker.
    func testTheHelperStepsAsideWhenSomethingElseTouchedTheBundle() {
        let script = UpdateInstaller.helperScript(Self.plan())
        XCTAssertEqual(script.components(separatedBy: #"if [ ! -d "$staged" ]; then step_aside "the new copy is gone"; fi"#)
            .count - 1, 2, "checked before and after waiting for the app")
        let aside = script.range(of: #"/bin/mv "$app" "$backup""#)!.upperBound
        let appeared = script.range(of: #"if [ -e "$app" ]; then"#)!
        let moveIn = script.range(of: #"if ! /bin/mv "$staged" "$app"; then"#)!.lowerBound
        XCTAssertLessThan(aside, appeared.lowerBound)
        XCTAssertLessThan(appeared.upperBound, moveIn, "checked just before the new copy moves in")
        XCTAssertTrue(script.contains(#"step_aside "another copy of Cicada was put in place meanwhile""#))
        let stepAside = script.range(of: "step_aside() {")!
        let body = script[stepAside.upperBound...].prefix(while: { $0 != "}" })
        XCTAssertFalse(body.contains("marker"), "stepping aside writes no failure")
        XCTAssertFalse(body.contains("open"), "and reopens nothing — the other installer does")
    }

    /// Logout or shutdown sends TERM: between the two renames the old copy goes back before the helper exits.
    func testTermRestoresTheOldCopyWhenItIsOutOfPlace() {
        let script = UpdateInstaller.helperScript(Self.plan(plist: "/p.plist"))
        XCTAssertTrue(script.contains("trap on_term TERM"))
        XCTAssertTrue(script.contains(#"if [ ! -e "$app" ] && [ -d "$backup" ]; then /bin/mv "$backup" "$app""#))
        let trap = script.range(of: "trap on_term TERM")!.lowerBound
        XCTAssertLessThan(trap, script.range(of: #"/bin/mv "$app" "$backup""#)!.lowerBound)
        let onTerm = script.range(of: "on_term() {")!
        XCTAssertTrue(script[onTerm.upperBound...].prefix(400).contains("start_service"))
    }

    /// The helper asks the backend itself right before anything moves; the token goes in on stdin, never in argv.
    func testTheHelperAsksTheBackendWithTheTokenOnStdin() {
        let script = UpdateInstaller.helperScript(Self.plan())
        XCTAssertTrue(script.contains("statusurl='http://127.0.0.1:8000/sleep/status'"))
        XCTAssertTrue(script.contains("tokenfile='/Users/x/.cicada/api_token'"))
        XCTAssertTrue(script.contains(#"printf 'header = "Authorization: Bearer %s"\n' "$(/bin/cat "$tokenfile")" | /usr/bin/curl -fsS --noproxy '*' --max-time 2 -K - "$statusurl""#))
        XCTAssertTrue(script.contains("7|28|52|56) return 1 ;;"), "no answer at all: no cycle is running there")
        XCTAssertTrue(script.contains(#"*'"writing":true'*|*'"status":"running"'*) return 0 ;;"#))
        XCTAssertTrue(script.contains("deferred='/Users/x/.cicada/update-deferred.json'"))
    }

    func testTheRelaunchFlag() {
        XCTAssertTrue(UpdateInstaller.helperScript(Self.plan(relaunch: true)).contains("relaunch=1\n"))
        XCTAssertTrue(UpdateInstaller.helperScript(Self.plan(relaunch: false)).contains("relaunch=0\n"))
        XCTAssertTrue(UpdateInstaller.helperScript(Self.plan()).contains(#"if [ "$relaunch" = 1 ]; then /usr/bin/open "$app""#))
    }

    func testOnlyDigitsAndDotsOfAVersionReachTheScript() {
        let script = UpdateInstaller.helperScript(Self.plan(version: "0.3.1'; rm -rf ~; '"))
        XCTAssertTrue(script.contains("version='unknown'"))
        XCTAssertFalse(script.contains("rm -rf ~"))
        XCTAssertTrue(UpdateInstaller.helperScript(Self.plan(version: "v0.3.1")).contains("version='0.3.1'"))
    }

    // MARK: The helper, run for real inside the test's folder

    /// A PID that has certainly exited.
    private func deadPID() throws -> Int32 {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/true")
        try p.run()
        p.waitUntilExit()
        return p.processIdentifier
    }

    private func runHelper(_ plan: UpdateInstaller.HelperPlan) throws -> Int32 {
        let script = dir.appendingPathComponent("helper.sh")
        try UpdateInstaller.helperScript(plan).write(to: script, atomically: true, encoding: .utf8)
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/sh")
        p.arguments = [script.path]
        p.environment = ["PATH": "/usr/bin:/bin"]
        try p.run()
        p.waitUntilExit()
        return p.terminationStatus
    }

    /// The Sleep status the helper reads: a `file://` URL to a JSON body, so no socket is ever opened.
    private func statusFile(_ json: String) throws -> String {
        let file = dir.appendingPathComponent("status-\(UUID().uuidString).json")
        try Data(json.utf8).write(to: file)
        return file.absoluteString
    }

    private func realPlan(folder: URL, pid: Int32, status: String) -> UpdateInstaller.HelperPlan {
        let app = folder.appendingPathComponent("Bob's Cicada.app")
        let home = dir.appendingPathComponent("home")
        return UpdateInstaller.HelperPlan(
            pid: pid, installedApp: app.path, stagedApp: UpdateInstaller.stagedURL(installedApp: app).path,
            backupApp: UpdateInstaller.backupURL(installedApp: app).path,
            trashDir: dir.appendingPathComponent("Trash").path, version: "0.3.1", fromVersion: "0.3.0",
            logFile: home.appendingPathComponent("logs/update.log").path,
            failureMarker: home.appendingPathComponent("update-failed.json").path,
            deferredMarker: home.appendingPathComponent("update-deferred.json").path,
            pidFile: home.appendingPathComponent("update-helper.pid").path, statusURL: status,
            tokenFile: home.appendingPathComponent("api_token").path,
            launchAgentPlist: nil, uid: getuid(), relaunch: false)
    }

    private func makeApp(at path: String, marker: String) throws {
        let contents = URL(fileURLWithPath: path).appendingPathComponent("Contents")
        try fm.createDirectory(at: contents, withIntermediateDirectories: true)
        try Data(marker.utf8).write(to: contents.appendingPathComponent("which"))
    }

    private func which(_ path: String) -> String? {
        fm.contents(atPath: path + "/Contents/which").map { String(decoding: $0, as: UTF8.self) }
    }

    private func sidecar(_ plan: UpdateInstaller.HelperPlan) -> String {
        UpdateInstaller.sidecarURL(stagedApp: URL(fileURLWithPath: plan.stagedApp)).path
    }

    func testTheHelperSwapsInTheNewCopyAndTrashesTheOld() throws {
        let folder = dir.appendingPathComponent("My Apps")
        let plan = realPlan(folder: folder, pid: try deadPID(),
                            status: try statusFile(#"{"status": "idle", "writing": false}"#))
        try makeApp(at: plan.installedApp, marker: "old")
        try makeApp(at: plan.stagedApp, marker: "new")
        try Data("{}".utf8).write(to: URL(fileURLWithPath: sidecar(plan)))
        XCTAssertEqual(try runHelper(plan), 0)
        XCTAssertEqual(which(plan.installedApp), "new")
        XCTAssertFalse(fm.fileExists(atPath: plan.stagedApp))
        XCTAssertFalse(fm.fileExists(atPath: sidecar(plan)), "the sidecar goes with the staged copy")
        XCTAssertFalse(fm.fileExists(atPath: plan.backupApp))
        let trashed = try fm.contentsOfDirectory(atPath: plan.trashDir)
        XCTAssertEqual(trashed.count, 1)
        XCTAssertTrue(trashed[0].hasPrefix("Cicada ") && trashed[0].hasSuffix(".app"), trashed[0])
        XCTAssertEqual(which(plan.trashDir + "/" + trashed[0]), "old")
        XCTAssertFalse(fm.fileExists(atPath: plan.failureMarker))
        XCTAssertFalse(fm.fileExists(atPath: plan.deferredMarker))
        XCTAssertFalse(fm.fileExists(atPath: plan.pidFile), "the helper tidies its PID file")
        let log = try String(contentsOfFile: plan.logFile, encoding: .utf8)
        XCTAssertTrue(log.contains("updating from 0.3.0 to 0.3.1"))
        XCTAssertTrue(log.contains("installed 0.3.1"))
    }

    func testTheHelperDefersWhileSleepIsWritingAndKeepsTheStagedCopy() throws {
        for body in [#"{"status":"running","writing":false}"#, #"{"status": "idle", "writing": true}"#,
                     #"not json at all"#] {
            try? fm.removeItem(at: dir.appendingPathComponent("Apps"))
            let plan = realPlan(folder: dir.appendingPathComponent("Apps"), pid: try deadPID(), status: try statusFile(body))
            try makeApp(at: plan.installedApp, marker: "old")
            try makeApp(at: plan.stagedApp, marker: "new")
            try Data("{}".utf8).write(to: URL(fileURLWithPath: sidecar(plan)))
            XCTAssertEqual(try runHelper(plan), 0, body)
            XCTAssertEqual(which(plan.installedApp), "old", body)
            XCTAssertEqual(which(plan.stagedApp), "new", "kept for the next quit: \(body)")
            XCTAssertTrue(fm.fileExists(atPath: sidecar(plan)), body)
            XCTAssertFalse(fm.fileExists(atPath: plan.failureMarker), "a deferral is not a failure: \(body)")
            XCTAssertEqual(UpdateFailureMarker.consumeDeferral(home: dir.appendingPathComponent("home")), "0.3.1", body)
        }
    }

    func testAnUnreadableAnswerCountsAsWritingButNoAnswerDoesNot() throws {
        // A status the backend can't serve (here, a file that isn't there: curl exits 37) is ambiguous → defer.
        let missing = dir.appendingPathComponent("no-such-status.json").absoluteString
        let plan = realPlan(folder: dir.appendingPathComponent("Apps"), pid: try deadPID(), status: missing)
        try makeApp(at: plan.installedApp, marker: "old")
        try makeApp(at: plan.stagedApp, marker: "new")
        XCTAssertEqual(try runHelper(plan), 0)
        XCTAssertEqual(which(plan.installedApp), "old")
        XCTAssertTrue(fm.fileExists(atPath: plan.deferredMarker))
    }

    func testTheHelperPutsTheOldCopyBackWhenTheNewOneCantMoveIn() throws {
        let folder = dir.appendingPathComponent("Apps")
        var plan = realPlan(folder: folder, pid: try deadPID(), status: try statusFile(#"{"status":"idle"}"#))
        // A staged copy in a folder the helper can't take it out of: the second rename fails.
        let lockedParent = dir.appendingPathComponent("locked")
        plan.stagedApp = lockedParent.appendingPathComponent("staged.app").path
        try makeApp(at: plan.installedApp, marker: "old")
        try makeApp(at: plan.stagedApp, marker: "new")
        try fm.setAttributes([.posixPermissions: 0o555], ofItemAtPath: lockedParent.path)
        XCTAssertEqual(try runHelper(plan), 1)
        XCTAssertEqual(which(plan.installedApp), "old", "the old copy is back where it was")
        XCTAssertFalse(fm.fileExists(atPath: plan.backupApp))
        let data = try XCTUnwrap(fm.contents(atPath: plan.failureMarker))
        let record = try JSONDecoder().decode(UpdateFailureRecord.self, from: data)
        XCTAssertEqual(record, UpdateFailureRecord(version: "0.3.1", reason: Copy.Updates.helperMoveIn))
    }

    func testTheHelperStepsAsideQuietlyWhenTheStagedCopyIsGone() throws {
        let plan = realPlan(folder: dir.appendingPathComponent("Apps"), pid: try deadPID(),
                            status: try statusFile(#"{"status":"idle"}"#))
        try makeApp(at: plan.installedApp, marker: "old")
        XCTAssertEqual(try runHelper(plan), 0)
        XCTAssertEqual(which(plan.installedApp), "old")
        XCTAssertFalse(fm.fileExists(atPath: plan.failureMarker), "someone else is installing; nothing to alarm about")
        XCTAssertFalse(fm.fileExists(atPath: plan.pidFile))
        XCTAssertTrue(try String(contentsOfFile: plan.logFile, encoding: .utf8).contains("the new copy is gone"))
    }

    // MARK: Leftovers and the marker

    private func stage(at app: URL, version: String, info: [String: Any]? = nil, sidecarVersion: String? = nil) throws {
        let staged = UpdateInstaller.stagedURL(installedApp: app)
        let contents = staged.appendingPathComponent("Contents")
        try fm.createDirectory(at: contents, withIntermediateDirectories: true)
        var plist = Self.goodInfo
        plist["CFBundleShortVersionString"] = version
        for (k, v) in info ?? [:] { plist[k] = v }
        (plist as NSDictionary).write(to: contents.appendingPathComponent("Info.plist"), atomically: true)
        let m = UpdateManifest(version: sidecarVersion ?? version, url: URL(string: "https://example.com/C.zip")!,
                               size: 1, sha256: "a", signature: "b")
        try JSONEncoder().encode(m).write(to: UpdateInstaller.sidecarURL(stagedApp: staged))
    }

    func testAStillValidStagedCopyIsAdoptedAtLaunchWithoutADownload() throws {
        let app = dir.appendingPathComponent("Apps/Cicada.app")
        let pidFile = dir.appendingPathComponent("update-helper.pid")
        try stage(at: app, version: "0.3.1")
        let adopted = UpdateInstaller.recoverStaged(installedApp: app, helperPIDFile: pidFile,
                                                    bundleIdentifier: "com.cicada.app", currentVersion: "0.3.0",
                                                    isAlive: { _ in false })
        XCTAssertEqual(adopted?.manifest.version, "0.3.1")
        XCTAssertEqual(adopted?.stagedApp, UpdateInstaller.stagedURL(installedApp: app))
        XCTAssertTrue(fm.fileExists(atPath: UpdateInstaller.stagedURL(installedApp: app).path))
    }

    func testAStaleOrMismatchedStagedCopyIsRemoved() throws {
        let app = dir.appendingPathComponent("Apps/Cicada.app")
        let pidFile = dir.appendingPathComponent("update-helper.pid")
        let staged = UpdateInstaller.stagedURL(installedApp: app)
        let cases: [(String, () throws -> Void)] = [
            ("no longer newer", { try self.stage(at: app, version: "0.3.0") }),
            ("Info.plist disagrees with the sidecar", { try self.stage(at: app, version: "0.3.1", sidecarVersion: "0.4.0") }),
            ("another app", { try self.stage(at: app, version: "0.3.1", info: ["CFBundleIdentifier": "com.example.x"]) }),
            ("no sidecar", {
                try self.stage(at: app, version: "0.3.1")
                try self.fm.removeItem(at: UpdateInstaller.sidecarURL(stagedApp: staged))
            }),
        ]
        for (why, make) in cases {
            try make()
            XCTAssertNil(UpdateInstaller.recoverStaged(installedApp: app, helperPIDFile: pidFile,
                                                       bundleIdentifier: "com.cicada.app", currentVersion: "0.3.0",
                                                       isAlive: { _ in false }), why)
            XCTAssertFalse(fm.fileExists(atPath: staged.path), why)
            XCTAssertFalse(fm.fileExists(atPath: UpdateInstaller.sidecarURL(stagedApp: staged).path), why)
        }
    }

    func testAStagedCopyARunningHelperUsesIsLeftAlone() throws {
        let app = dir.appendingPathComponent("Apps/Cicada.app")
        let pidFile = dir.appendingPathComponent("update-helper.pid")
        try stage(at: app, version: "0.3.0")   // not newer: would be removed, but a helper is mid-swap
        try Data("777".utf8).write(to: pidFile)
        XCTAssertNil(UpdateInstaller.recoverStaged(installedApp: app, helperPIDFile: pidFile, bundleIdentifier: "com.cicada.app",
                                                   currentVersion: "0.3.0", isAlive: { $0 == 777 }))
        XCTAssertTrue(fm.fileExists(atPath: UpdateInstaller.stagedURL(installedApp: app).path))
    }

    func testTheFailureMarkerIsReadOnceThenDeleted() throws {
        let home = dir.appendingPathComponent("home")
        try fm.createDirectory(at: home, withIntermediateDirectories: true)
        XCTAssertNil(UpdateFailureMarker.consume(home: home))
        try Data(#"{"version": "0.3.1", "reason": "the new copy couldn't be moved into place"}"#.utf8)
            .write(to: UpdateFailureMarker.url(home: home))
        XCTAssertEqual(UpdateFailureMarker.consume(home: home),
                       UpdateFailureRecord(version: "0.3.1", reason: "the new copy couldn't be moved into place"))
        XCTAssertNil(UpdateFailureMarker.consume(home: home), "said once")
        XCTAssertFalse(fm.fileExists(atPath: UpdateFailureMarker.url(home: home).path))
        // The helper's service line decodes too.
        try Data(#"{"version": "0.3.1", "reason": "x", "installed": true, "service_stopped": true}"#.utf8)
            .write(to: UpdateFailureMarker.url(home: home))
        XCTAssertEqual(UpdateFailureMarker.consume(home: home),
                       UpdateFailureRecord(version: "0.3.1", reason: "x", installed: true, serviceStopped: true))
        // An unreadable marker is still removed, so it can't be said wrongly forever.
        try Data("garbage".utf8).write(to: UpdateFailureMarker.url(home: home))
        XCTAssertNil(UpdateFailureMarker.consume(home: home))
        XCTAssertFalse(fm.fileExists(atPath: UpdateFailureMarker.url(home: home).path))
        // The deferral note, read once.
        try Data(#"{"version": "0.3.1"}"#.utf8).write(to: UpdateFailureMarker.deferredURL(home: home))
        XCTAssertEqual(UpdateFailureMarker.consumeDeferral(home: home), "0.3.1")
        XCTAssertNil(UpdateFailureMarker.consumeDeferral(home: home))
    }

    // MARK: Sleep, asked of the backend

    func testTheProbeReadsTheBackendsAnswer() {
        func body(_ s: String) -> Data { Data(s.utf8) }
        XCTAssertEqual(SleepProbe.classify(statusCode: 200, body: body(#"{"status":"idle","writing":false}"#), error: nil), .idle)
        XCTAssertEqual(SleepProbe.classify(statusCode: 200, body: body(#"{"status":"running","writing":false}"#), error: nil),
                       .busy, "a drain between batches still stops if the backend is booted out")
        XCTAssertEqual(SleepProbe.classify(statusCode: 200, body: body(#"{"status":"idle","writing":true}"#), error: nil), .busy)
        XCTAssertEqual(SleepProbe.classify(statusCode: 200, body: body(#"{"other":1}"#), error: nil), .ambiguous)
        XCTAssertEqual(SleepProbe.classify(statusCode: 401, body: body("{}"), error: nil), .ambiguous)
        XCTAssertEqual(SleepProbe.classify(statusCode: nil, body: nil, error: URLError(.cannotConnectToHost)), .noAnswer)
        XCTAssertEqual(SleepProbe.classify(statusCode: nil, body: nil, error: URLError(.timedOut)), .noAnswer)
        XCTAssertEqual(SleepProbe.classify(statusCode: nil, body: nil, error: URLError(.badServerResponse)), .ambiguous)
        XCTAssertTrue(SleepProbe.isBusy(.busy))
        XCTAssertTrue(SleepProbe.isBusy(.ambiguous))
        XCTAssertFalse(SleepProbe.isBusy(.noAnswer), "nothing answering runs no cycle")
        XCTAssertFalse(SleepProbe.isBusy(.idle))
        XCTAssertEqual(SleepProbe.statusURL(port: 8123).absoluteString, "http://127.0.0.1:8123/sleep/status")
    }

    private func assertStageFails(_ installer: UpdateInstaller, _ manifest: UpdateManifest,
                                  _ expected: UpdateInstaller.Failure, file: StaticString = #filePath,
                                  line: UInt = #line) async {
        do {
            _ = try await installer.stage(manifest, progress: { _ in })
            XCTFail("expected \(expected)", file: file, line: line)
        } catch {
            XCTAssertEqual(error as? UpdateInstaller.Failure, expected, file: file, line: line)
        }
    }
}

final class ProgressBox: @unchecked Sendable {
    var names: [String] = []
    private let lock = NSLock()
    private var stored: [Double] = []
    func append(_ v: Double) { lock.lock(); stored.append(v); lock.unlock() }
    var values: [Double] { lock.lock(); defer { lock.unlock() }; return stored }
}
