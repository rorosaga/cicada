import XCTest
@testable import CicadaApp

/// G182 phase 5 — the updater's state machine, every effect faked: inert outside a release, the automatic switch as
/// the gate for anything the app starts on its own, a found update staged in the background, never installed while
/// Sleep writes, and a failed swap said once.
@MainActor
final class UpdateServiceTests: XCTestCase {
    static let manifest = UpdateManifest(version: "0.3.1", url: URL(string: "https://example.com/Cicada-0.3.1.zip")!,
                                         size: 10, sha256: "aa", signature: "bb",
                                         notesURL: URL(string: "https://example.com/notes"))

    nonisolated static func releaseRuntime(bundle: String = "/Applications/Cicada.app") -> CicadaRuntime {
        CicadaRuntime(distribution: .release, bundlePath: bundle,
                      codeRoot: URL(fileURLWithPath: bundle + "/Contents/Resources/backend/app"),
                      cicadaHome: URL(fileURLWithPath: "/nonexistent/.cicada"), port: 8000,
                      memoryRootDefault: "/nonexistent/cicada/memory")
    }

    /// Counts every effect and answers from settable values.
    final class Fakes {
        var checkResult: Result<UpdateCheckResult, Error> = .success(.upToDate)
        var stageResult: Result<Void, Error> = .success(())
        var handOffError: Error?
        var sleepWriting = false
        var failure: UpdateFailureRecord?
        var deferral: String?
        var recovered: StagedUpdate?
        final class ProbeBox: @unchecked Sendable { var answer: SleepProbe.Answer = .noAnswer }
        let probe = ProbeBox()
        var probeAnswer: SleepProbe.Answer {
            get { probe.answer }
            set { probe.answer = newValue }
        }
        var repairResult = true
        var repairs = 0
        var checks = 0
        var stages = 0
        var handOffs: [Bool] = []
        var terminations = 0
        var cleanups = 0
        var consumed = 0
        let now = Date(timeIntervalSince1970: 1_800_000_000)

        func dependencies() -> UpdateService.Dependencies {
            UpdateService.Dependencies(
                check: { [self] in checks += 1; return try checkResult.get() },
                stage: { [self] manifest, progress in
                    stages += 1
                    progress(0.5)
                    try stageResult.get()
                    return StagedUpdate(manifest: manifest, stagedApp: URL(fileURLWithPath: "/Applications/.Cicada.app.update"),
                                        installedApp: URL(fileURLWithPath: "/Applications/Cicada.app"))
                },
                handOff: { [self] _, relaunch in
                    if let handOffError { throw handOffError }
                    handOffs.append(relaunch)
                },
                terminate: { [self] in terminations += 1 },
                consumeFailure: { [self] in consumed += 1; defer { failure = nil }; return failure },
                consumeDeferral: { [self] in defer { deferral = nil }; return deferral },
                recoverStaged: { [self] in cleanups += 1; return recovered },
                isSleepWriting: { [self] in sleepWriting },
                probeSleep: { [probe] _ in probe.answer },
                repairService: { [self] in repairs += 1; return repairResult },
                // The schedule never really waits in a test: the first sleep suspends until cancelled.
                sleep: { _ in try await Task.sleep(for: .seconds(3600)) },
                now: { [self] in now })
        }
    }

    private var suites: [String] = []

    override func tearDown() {
        for s in suites { UserDefaults.standard.removePersistentDomain(forName: s) }
        super.tearDown()
    }

    private func defaults(automatic: Bool? = nil, lastLaunched: String? = nil) -> UserDefaults {
        let name = "cicada.test.updates.\(UUID().uuidString)"
        suites.append(name)
        let d = UserDefaults(suiteName: name)!
        if let automatic { d.set(automatic, forKey: UpdateService.automaticKey) }
        if let lastLaunched { d.set(lastLaunched, forKey: UpdateService.lastLaunchedKey) }
        return d
    }

    private func service(_ fakes: Fakes, runtime: CicadaRuntime = releaseRuntime(), repo: Bool = true,
                         automatic: Bool? = nil, lastLaunched: String? = nil) -> UpdateService {
        UpdateService(runtime: runtime, repoConfigured: repo, currentVersion: "0.3.0",
                      defaults: defaults(automatic: automatic, lastLaunched: lastLaunched),
                      dependencies: fakes.dependencies())
    }

    private func readyService(_ fakes: Fakes) async -> UpdateService {
        fakes.checkResult = .success(.available(Self.manifest))
        let s = service(fakes)
        await s.check(userInitiated: false)
        XCTAssertEqual(s.state, .ready(Self.manifest))
        return s
    }

    // MARK: Inert outside a release

    func testADeveloperBuildIsInert() async {
        let fakes = Fakes()
        let s = service(fakes, runtime: .developer(codeRoot: URL(fileURLWithPath: "/R/cicada")))
        XCTAssertFalse(s.isActive)
        s.start()
        XCTAssertFalse(s.isScheduled, "no timer")
        XCTAssertEqual(fakes.consumed, 0)
        XCTAssertEqual(fakes.cleanups, 0)
        await s.check(userInitiated: true)
        await s.scheduledTick()
        XCTAssertEqual(fakes.checks, 0, "a developer build never checks, not even from the menu")
        XCTAssertEqual(s.state, .idle)
    }

    func testACopyRunFromADiskImageOrTranslocatedOrWithoutARepoIsInert() {
        let fakes = Fakes()
        XCTAssertFalse(service(fakes, runtime: Self.releaseRuntime(bundle: "/Volumes/Cicada/Cicada.app")).isActive)
        XCTAssertFalse(service(fakes, runtime: Self.releaseRuntime(
            bundle: "/private/var/folders/x/AppTranslocation/ABC/d/Cicada.app")).isActive)
        XCTAssertFalse(service(fakes, repo: false).isActive)
        XCTAssertTrue(service(fakes).isActive)
    }

    // MARK: The switch

    func testAutomaticDefaultsToOnAndPersists() {
        let fakes = Fakes()
        let d = defaults()
        let s = UpdateService(runtime: Self.releaseRuntime(), repoConfigured: true, currentVersion: "0.3.0",
                              defaults: d, dependencies: fakes.dependencies())
        XCTAssertTrue(s.automatic)
        s.automatic = false
        XCTAssertEqual(d.object(forKey: UpdateService.automaticKey) as? Bool, false)
        let again = UpdateService(runtime: Self.releaseRuntime(), repoConfigured: true, currentVersion: "0.3.0",
                                  defaults: d, dependencies: fakes.dependencies())
        XCTAssertFalse(again.automatic)
    }

    func testWithAutomaticOffTheScheduleNeverChecksButTheMenuDoes() async {
        let fakes = Fakes()
        let s = service(fakes, automatic: false)
        s.start()
        XCTAssertTrue(s.isScheduled)
        await s.scheduledTick()
        XCTAssertEqual(fakes.checks, 0, "the switch is the gate for every check the app starts on its own")
        await s.check(userInitiated: false)
        XCTAssertEqual(fakes.checks, 0)
        await s.check(userInitiated: true)
        XCTAssertEqual(fakes.checks, 1, "the menu item is the person's own click")
        XCTAssertEqual(s.state, .upToDate(checkedAt: fakes.now))
    }

    func testWithAutomaticOnTheScheduleChecks() async {
        let fakes = Fakes()
        let s = service(fakes)
        await s.scheduledTick()
        XCTAssertEqual(fakes.checks, 1)
        XCTAssertEqual(s.state, .upToDate(checkedAt: fakes.now))
    }

    // MARK: Found → staged → installed

    func testAFoundUpdateWithAutomaticOnIsStagedInTheBackground() async {
        let fakes = Fakes()
        fakes.checkResult = .success(.available(Self.manifest))
        let s = service(fakes)
        await s.check(userInitiated: false)
        XCTAssertEqual(fakes.stages, 1)
        XCTAssertEqual(s.state, .ready(Self.manifest))
        XCTAssertTrue(fakes.handOffs.isEmpty, "staged, not installed: that waits for quit or Restart to update")
    }

    func testAFoundUpdateWithAutomaticOffWaitsForTheDownloadClick() async {
        let fakes = Fakes()
        fakes.checkResult = .success(.available(Self.manifest))
        let s = service(fakes, automatic: false)
        await s.check(userInitiated: true)
        XCTAssertEqual(s.state, .available(Self.manifest))
        XCTAssertEqual(fakes.stages, 0)
        await s.download()
        XCTAssertEqual(fakes.stages, 1)
        XCTAssertEqual(s.state, .ready(Self.manifest))
    }

    func testQuittingWithAnUpdateReadyHandsOffWithoutRelaunch() async {
        let fakes = Fakes()
        fakes.checkResult = .success(.available(Self.manifest))
        let s = service(fakes)
        await s.check(userInitiated: false)
        s.appWillTerminate()
        XCTAssertEqual(fakes.handOffs, [false])
        s.appWillTerminate()
        XCTAssertEqual(fakes.handOffs, [false], "one helper per quit")
        XCTAssertEqual(fakes.terminations, 0, "already quitting")
    }

    func testRestartToUpdateHandsOffWithRelaunchThenQuits() async {
        let fakes = Fakes()
        fakes.checkResult = .success(.available(Self.manifest))
        let s = service(fakes)
        await s.check(userInitiated: false)
        await s.restartToUpdate()
        XCTAssertEqual(fakes.handOffs, [true])
        XCTAssertEqual(fakes.terminations, 1)
        XCTAssertEqual(s.state, .installing(Self.manifest))
        s.appWillTerminate()
        XCTAssertEqual(fakes.handOffs, [true], "the quit that follows doesn't start a second helper")
    }

    func testNothingInstallsWhileSleepWrites() async {
        let fakes = Fakes()
        fakes.checkResult = .success(.available(Self.manifest))
        let s = service(fakes)
        await s.check(userInitiated: false)
        fakes.sleepWriting = true
        await s.restartToUpdate()
        s.appWillTerminate()
        XCTAssertTrue(fakes.handOffs.isEmpty, "deferred")
        XCTAssertEqual(fakes.terminations, 0)
        XCTAssertEqual(s.state, .ready(Self.manifest), "still ready for when Sleep is done")
        fakes.sleepWriting = false
        await s.restartToUpdate()
        XCTAssertEqual(fakes.handOffs, [true])
    }

    func testRestartDoesNothingUntilAnUpdateIsReady() async {
        let fakes = Fakes()
        let s = service(fakes)
        await s.restartToUpdate()
        s.appWillTerminate()
        XCTAssertTrue(fakes.handOffs.isEmpty)
        XCTAssertEqual(fakes.terminations, 0)
    }

    // MARK: Sleep, asked fresh

    /// The Store's cache is nil before its first poll; at hand-off the backend itself is asked.
    func testRestartAsksTheBackendFreshAndDefersWithASentence() async {
        for answer in [SleepProbe.Answer.busy, .ambiguous] {
            let fakes = Fakes()
            let s = await readyService(fakes)
            fakes.probeAnswer = answer
            await s.restartToUpdate()
            XCTAssertTrue(fakes.handOffs.isEmpty, "\(answer)")
            XCTAssertEqual(fakes.terminations, 0)
            XCTAssertEqual(s.state, .ready(Self.manifest))
            XCTAssertTrue(s.sleepRefusedRestart)
            XCTAssertEqual(Copy.Updates.statusLine(s.state, now: fakes.now, sleepRefused: s.sleepRefusedRestart),
                           Copy.Updates.readyButSleeping("0.3.1"))
            fakes.probeAnswer = .noAnswer
            await s.restartToUpdate()
            XCTAssertEqual(fakes.handOffs, [true], "nothing answering runs no cycle: go ahead")
            XCTAssertFalse(s.sleepRefusedRestart)
        }
    }

    func testAQuitInstallsNothingWhenTheBackendSaysSleepIsWriting() async {
        let fakes = Fakes()
        let s = await readyService(fakes)
        fakes.probeAnswer = .busy
        s.appWillTerminate()
        XCTAssertTrue(fakes.handOffs.isEmpty)
        fakes.probeAnswer = .idle
        s.appWillTerminate()
        XCTAssertEqual(fakes.handOffs, [false])
    }

    func testLogoutOrShutdownInstallsNothing() async {
        let fakes = Fakes()
        let s = await readyService(fakes)
        s.systemWillPowerOff()
        s.appWillTerminate()
        XCTAssertTrue(fakes.handOffs.isEmpty, "the helper would be stopped mid-swap")
        XCTAssertEqual(s.state, .ready(Self.manifest), "it waits for the next quit")
    }

    // MARK: A deferred install survives the relaunch

    func testAStagedCopyLeftByADeferralIsAdoptedWithoutADownload() async {
        let fakes = Fakes()
        fakes.recovered = StagedUpdate(manifest: Self.manifest,
                                       stagedApp: URL(fileURLWithPath: "/Applications/.Cicada.app.update"),
                                       installedApp: URL(fileURLWithPath: "/Applications/Cicada.app"))
        fakes.deferral = "0.3.1"
        let s = service(fakes)
        s.start()
        XCTAssertEqual(s.state, .ready(Self.manifest))
        XCTAssertEqual(s.deferredVersion, "0.3.1")
        XCTAssertEqual(Copy.Updates.statusLine(s.state, now: fakes.now, deferredVersion: s.deferredVersion),
                       Copy.Updates.readyAfterDeferral("0.3.1"))
        await s.check(userInitiated: true)
        XCTAssertEqual(fakes.checks, 0, "already ready")
        XCTAssertEqual(fakes.stages, 0, "no second download")
        s.appWillTerminate()
        XCTAssertEqual(fakes.handOffs, [false])
    }

    // MARK: The background service after an update

    func testAServiceTheHelperCouldntRestartIsRepairedOnceAndTheSentenceRetires() async {
        let fakes = Fakes()
        fakes.failure = UpdateFailureRecord(version: "0.3.0", reason: Copy.Updates.helperServiceDidNotStart,
                                            installed: true, serviceStopped: true)
        let s = service(fakes)
        s.start()
        XCTAssertNotNil(s.lastInstallFailure)
        await s.repairTask?.value
        XCTAssertEqual(fakes.repairs, 1)
        XCTAssertNil(s.lastInstallFailure, "the service runs again; nothing left to say")

        let stuck = Fakes()
        stuck.repairResult = false
        stuck.failure = UpdateFailureRecord(version: "0.3.0", reason: "x", installed: true, serviceStopped: true)
        let t = service(stuck)
        t.start()
        await t.repairTask?.value
        XCTAssertEqual(stuck.repairs, 1)
        XCTAssertEqual(Copy.Updates.installFailed(t.lastInstallFailure!, current: "0.3.0"),
                       Copy.Updates.installedServiceStopped("0.3.0"))
    }

    func testTheFirstLaunchOnANewVersionChecksTheServiceOnce() async {
        let updated = Fakes()
        let s = service(updated, lastLaunched: "0.2.9")
        s.start()
        await s.repairTask?.value
        XCTAssertEqual(updated.repairs, 1)

        let same = Fakes()
        let t = service(same, lastLaunched: "0.3.0")
        t.start()
        await t.repairTask?.value
        XCTAssertNil(t.repairTask)
        XCTAssertEqual(same.repairs, 0, "an ordinary launch never touches the service")

        let first = Fakes()
        let u = service(first)
        u.start()
        XCTAssertNil(u.repairTask, "the very first launch isn't an update")
    }

    func testTheServiceRepairWaitsWhileSleepMayBeWriting() async {
        let fakes = Fakes()
        fakes.probeAnswer = .busy
        let s = service(fakes, lastLaunched: "0.2.9")
        s.start()
        await s.repairTask?.value
        XCTAssertEqual(fakes.repairs, 0, "an install stops the app's own backend child")
    }

    // MARK: Failures in words

    func testFailuresBecomeOneLine() async {
        let fakes = Fakes()
        fakes.checkResult = .failure(UpdateChecker.Failure.offline)
        let s = service(fakes)
        await s.check(userInitiated: true)
        XCTAssertEqual(s.state, .failed("Couldn't check for updates: this Mac seems to be offline."))

        fakes.checkResult = .success(.available(Self.manifest))
        fakes.stageResult = .failure(UpdateInstaller.Failure.verify(.badSignature))
        await s.check(userInitiated: true)
        XCTAssertEqual(s.state, .failed(Copy.Updates.downloadFailed(Copy.Updates.reasonBadSignature)))

        fakes.stageResult = .success(())
        await s.check(userInitiated: true)
        fakes.handOffError = UpdateInstaller.Failure.helper("Resource temporarily unavailable")
        await s.restartToUpdate()
        XCTAssertEqual(fakes.terminations, 0, "an app whose helper didn't start doesn't quit")
        guard case .failed(let line) = s.state else { return XCTFail("\(s.state)") }
        XCTAssertTrue(line.hasPrefix("Couldn't start the update: the installer couldn't start"), line)
    }

    func testANewerReleaseThisMacCantRunIsSaid() async {
        let fakes = Fakes()
        fakes.checkResult = .success(.needsNewerMacOS(Self.manifest, minimum: "15.0"))
        let s = service(fakes)
        await s.check(userInitiated: true)
        XCTAssertEqual(s.state, .needsNewerMacOS(Self.manifest, minimum: "15.0"))
        XCTAssertEqual(fakes.stages, 0)
        XCTAssertEqual(Copy.Updates.statusLine(s.state, now: fakes.now), "Version 0.3.1 needs macOS 15.0 or later.")
    }

    func testAFailedSwapIsReadOnceAtLaunch() {
        let fakes = Fakes()
        fakes.failure = UpdateFailureRecord(version: "0.3.1", reason: Copy.Updates.helperMoveIn)
        let s = service(fakes)
        s.start()
        XCTAssertEqual(s.lastInstallFailure, UpdateFailureRecord(version: "0.3.1", reason: Copy.Updates.helperMoveIn))
        XCTAssertEqual(fakes.consumed, 1)
        XCTAssertEqual(fakes.cleanups, 1, "a stale staged copy is tidied at launch")
        s.start()
        XCTAssertEqual(fakes.consumed, 1, "start runs once")
        XCTAssertEqual(Copy.Updates.installFailed(s.lastInstallFailure!, current: s.currentVersion),
                       "The update to 0.3.1 couldn't be installed: the new copy couldn't be moved into place. "
                           + "You're still on 0.3.0.")
    }

    // MARK: The status line

    func testTheStatusLineIsComputedWhenRead() {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let en = Locale(identifier: "en_US")
        XCTAssertNil(Copy.Updates.statusLine(.idle, now: now))
        XCTAssertEqual(Copy.Updates.statusLine(.upToDate(checkedAt: now.addingTimeInterval(-7200)), now: now, locale: en),
                       "Cicada is up to date — checked 2 hours ago.")
        XCTAssertEqual(Copy.Updates.statusLine(.upToDate(checkedAt: now.addingTimeInterval(-5)), now: now, locale: en),
                       "Cicada is up to date — checked now.")
        XCTAssertEqual(Copy.Updates.statusLine(.ready(Self.manifest), now: now),
                       "Version 0.3.1 is ready. It installs when you quit Cicada.")
        XCTAssertEqual(Copy.Updates.statusLine(.downloading(Self.manifest, progress: 0.426), now: now),
                       "Downloading version 0.3.1… 42%")
        XCTAssertEqual(Copy.Updates.statusLine(.available(Self.manifest), now: now), "Version 0.3.1 is available.")
        XCTAssertEqual(Copy.Updates.statusLine(.failed("x"), now: now), "x")
    }

    func testUpdaterCopyIsProviderNeutral() {
        let lines = [Copy.Updates.autoDetail(automatic: true), Copy.Updates.autoDetail(automatic: false),
                     Copy.Updates.reasonNoRelease, Copy.Updates.reasonHTTP(500), Copy.Updates.reasonUnreachable,
                     Copy.Updates.reasonNoManifest, Copy.Updates.waitForSleep, Copy.Updates.whatsNewHelp]
        for line in lines {
            for name in ["github", "claude", "chatgpt", "openai", "anthropic", "ollama"] {
                XCTAssertFalse(line.lowercased().contains(name), "\(name) in \"\(line)\"")
            }
        }
        XCTAssertTrue(Copy.Updates.autoDetail(automatic: false).contains(Copy.Updates.menuItem),
                      "the off sentence names the menu item exactly as the menu spells it")
    }

    // MARK: Wiring

    func testTheMenuItemAndTheRowExistOnlyBehindIsActive() throws {
        let commands = try String(contentsOf: XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.path.hasSuffix("Support/ShellCommands.swift") }), encoding: .utf8)
        XCTAssertTrue(commands.contains("CommandGroup(after: .appInfo)"))
        XCTAssertTrue(commands.contains("if updates.isActive"))
        XCTAssertTrue(commands.contains("check(userInitiated: true)"))
        let general = try String(contentsOf: XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.path.hasSuffix("Views/Settings/SettingsGeneralView.swift") }), encoding: .utf8)
        let version = try XCTUnwrap(general.range(of: "SettingsRow(.appVersion,")).lowerBound
        let gate = try XCTUnwrap(general.range(of: "if updates.isActive")).lowerBound
        let row = try XCTUnwrap(general.range(of: "SettingsRow(.autoUpdate,")).lowerBound
        XCTAssertLessThan(version, gate, "in Version's card, after it (DR-37)")
        XCTAssertLessThan(gate, row)
        let app = try String(contentsOf: XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.path.hasSuffix("CicadaApp.swift") }), encoding: .utf8)
        XCTAssertTrue(app.contains(".environment(updates)"))
        XCTAssertTrue(app.contains("ShellCommands(router: appRouter, updates: updates)"))
    }

    func testTheRowIsIndexedAndLandsOnVersion() {
        XCTAssertTrue(SettingsIndex.staticIDs.contains(.autoUpdate))
        let entry = SettingsIndex.staticEntries.first { $0.id == .autoUpdate }
        XCTAssertEqual(entry?.anchor, .appVersion, "a developer build hides the row; Version is always there")
        let all = SettingsIndex.staticEntries + SettingsIndex.pageEntries
        XCTAssertTrue(SettingsIndex.search("automatic updates", in: all).prefix(3).contains { $0.entry.id == .autoUpdate })
        XCTAssertTrue(SettingsIndex.search("upgrade", in: all).contains { $0.entry.id == .autoUpdate })
    }
}

/// G182 phase 5 — the launch-time repair: a plist launchd isn't running is installed again once; no plist, nothing.
@MainActor
final class BackendAgentReinstallTests: XCTestCase {
    /// `launchctl print` fails until the install script has run.
    final class Runner: AgentProcessRunning, @unchecked Sendable {
        var installed = false
        var installs = 0
        func run(_ argv: [String], environment: [String: String], timeout: Duration) async -> AgentProcessResult {
            if argv.first == "/bin/bash" { installs += 1; installed = true; return AgentProcessResult(status: 0, stderr: "") }
            return AgentProcessResult(status: installed ? 0 : 113, stderr: "")
        }
    }

    private func plist(exists: Bool) throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("agent-\(UUID().uuidString).plist")
        if exists { try Data("<plist/>".utf8).write(to: url) }
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }

    func testAStoppedServiceIsInstalledAgainOnce() async throws {
        let runner = Runner()
        let service = BackendAgentService(runner: runner, runtime: .developer(codeRoot: URL(fileURLWithPath: "/x/cicada")),
                                          plistURL: try plist(exists: true), uid: 501, memoryRoot: { "/m" },
                                          envFileContents: { nil }, onInstalled: {})
        let running = await service.reinstallIfStopped()
        XCTAssertTrue(running)
        XCTAssertEqual(runner.installs, 1)
        let again = await service.reinstallIfStopped()
        XCTAssertTrue(again)
        XCTAssertEqual(runner.installs, 1, "a running service is left alone")
    }

    func testNoPlistMeansTheServiceWasNeverChosen() async throws {
        let runner = Runner()
        let service = BackendAgentService(runner: runner, runtime: .developer(codeRoot: URL(fileURLWithPath: "/x/cicada")),
                                          plistURL: try plist(exists: false), uid: 501, memoryRoot: { "/m" },
                                          envFileContents: { nil }, onInstalled: {})
        let running = await service.reinstallIfStopped()
        XCTAssertFalse(running)
        XCTAssertEqual(runner.installs, 0, "the service stays opt-in")
    }
}
