import AppKit
import Foundation
import Observation

/// Where the updater stands (G182). Every case is what Settings → General says in one line.
enum UpdateState: Equatable {
    case idle
    case checking
    case upToDate(checkedAt: Date)
    /// Newer, found by a check while automatic updates are off: the person chooses when to download it.
    case available(UpdateManifest)
    /// Newer, but this Mac's macOS is older than the release needs.
    case needsNewerMacOS(UpdateManifest, minimum: String)
    case downloading(UpdateManifest, progress: Double)
    /// Downloaded, verified and staged beside the installed app; installs when the person quits, or now on
    /// "Restart to update".
    case ready(UpdateManifest)
    case installing(UpdateManifest)
    /// The whole line to show, in words.
    case failed(String)
}

/// G182 phase 5 — the in-app updater: checks the release repo, gets a newer version ready in the background, and
/// installs it when the person quits (or at once, on "Restart to update").
///
/// **Only a release build** that runs from a real folder (`runtime.isRelease && runtime.launchersAreStable`) and
/// carries a release repo ever does any of this; anywhere else the service is inert — no check, no timer, no
/// observer — and Settings and the app menu hide it. A developer build never checks or updates itself.
///
/// **The switch is the gate.** *Install updates automatically* (`cicada.updates.automatic`, on by default) gates every
/// network call the app starts on its own: the check ~20 s after launch, one every 6 hours, and the background
/// download that follows a find. With it off, only the app menu's *Check for Updates…* looks, and a found update waits
/// for the person's Download.
///
/// **Never while Sleep writes.** Installing stops the background service (the helper boots it out to swap the
/// bundle it runs from), which would cut a cycle mid-stage — the G85 smear. Three looks, freshest last: the Store's
/// cached status disables "Restart to update" (DR-41); at hand-off the backend is asked directly (`SleepProbe` — the
/// cache is nil before the first poll); and the helper asks once more right before anything moves. A deferred install
/// keeps its staged copy, and the next launch adopts it (`UpdateInstaller.recoverStaged`) — no second download.
///
/// **Not at logout or shutdown.** A quit macOS starts on its way down (`NSWorkspace.willPowerOffNotification`)
/// installs nothing: the helper would be stopped mid-swap. The staged copy waits for the next quit.
///
/// **After an update** (the first launch on a new version, or a helper that said so) a background service whose plist
/// exists but which launchd isn't running is installed again once (`BackendAgentService.reinstallIfStopped`).
@MainActor
@Observable
final class UpdateService {
    static let automaticKey = "cicada.updates.automatic"
    static let firstCheckDelay: Duration = .seconds(20)
    static let checkInterval: Duration = .seconds(6 * 60 * 60)
    /// The version this app last launched as — a change means "just updated" (the service repair's trigger).
    static let lastLaunchedKey = "cicada.updates.lastLaunchedVersion"
    static let handOffProbeTimeout: Duration = .seconds(2)
    static let quitProbeTimeout: Duration = .milliseconds(1500)

    /// Every effect the service has on the world, injected so tests drive the state machine with fakes.
    struct Dependencies {
        var check: @MainActor () async throws -> UpdateCheckResult
        var stage: @MainActor (UpdateManifest, @escaping @Sendable (Double) -> Void) async throws -> StagedUpdate
        /// Writes and starts the helper; the Bool is "reopen Cicada afterwards".
        var handOff: @MainActor (StagedUpdate, Bool) throws -> Void
        var terminate: @MainActor () -> Void
        var consumeFailure: @MainActor () -> UpdateFailureRecord?
        /// The version the helper left waiting for Sleep (`update-deferred.json`), read once.
        var consumeDeferral: @MainActor () -> String? = { nil }
        /// Adopts a staged copy a deferred install left behind, or removes a stale one.
        var recoverStaged: @MainActor () -> StagedUpdate?
        /// `ProjectWriteGate.blocked` over the Store's status — the cached answer, for the button.
        var isSleepWriting: @MainActor () -> Bool
        /// The backend asked directly, with a timeout (`SleepProbe`).
        var probeSleep: @Sendable (Duration) async -> SleepProbe.Answer = { _ in .noAnswer }
        /// `BackendAgentService.reinstallIfStopped`: true when the service runs afterwards.
        var repairService: @MainActor () async -> Bool = { true }
        var sleep: @Sendable (Duration) async throws -> Void = { try await Task.sleep(for: $0) }
        var now: @MainActor () -> Date = { Date() }
    }

    private(set) var state: UpdateState = .idle
    /// The swap that failed while the app was closed (`update-failed.json`), read once at launch; said for this session.
    private(set) var lastInstallFailure: UpdateFailureRecord?
    /// The version whose install the helper deferred because Sleep was writing — said beside the ready line.
    private(set) var deferredVersion: String?
    /// "Restart to update" was turned down by the backend's fresh answer; cleared by the next restart that goes ahead.
    private(set) var sleepRefusedRestart = false
    /// Persisted per viewer. Turning it on is the person's own click, so it looks right away.
    var automatic: Bool {
        didSet {
            guard automatic != oldValue else { return }
            defaults.set(automatic, forKey: Self.automaticKey)
            if automatic { Task { await self.check(userInitiated: false) } }
        }
    }
    /// False in a developer build, a copy run from a disk image or a translocated download, or a release missing its
    /// repo: nothing runs and nothing shows.
    let isActive: Bool
    let currentVersion: String?

    @ObservationIgnored private let deps: Dependencies
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private var staged: StagedUpdate?
    @ObservationIgnored private var scheduler: Task<Void, Never>?
    @ObservationIgnored private var terminateObserver: NSObjectProtocol?
    @ObservationIgnored private var powerOffObserver: NSObjectProtocol?
    @ObservationIgnored private var handedOff = false
    @ObservationIgnored private(set) var poweringOff = false
    /// The launch-time service repair, kept so tests can await it.
    @ObservationIgnored private(set) var repairTask: Task<Void, Never>?

    init(runtime: CicadaRuntime, repoConfigured: Bool, currentVersion: String?,
         defaults: UserDefaults = .standard, dependencies: Dependencies) {
        isActive = Self.isActive(runtime: runtime, repoConfigured: repoConfigured)
        self.currentVersion = currentVersion
        self.defaults = defaults
        self.deps = dependencies
        automatic = defaults.object(forKey: Self.automaticKey) as? Bool ?? true
    }

    static func isActive(runtime: CicadaRuntime, repoConfigured: Bool) -> Bool {
        runtime.isRelease && runtime.launchersAreStable && repoConfigured
    }

    /// True once `start()` armed the timer — never in an inert build.
    var isScheduled: Bool { scheduler != nil }

    // MARK: Launch

    /// Once per launch: say a failed swap, adopt (or tidy) a staged copy, repair the service after an update, hook
    /// quit and power-off, and arm the schedule. Inert builds return at once.
    func start() {
        guard isActive, scheduler == nil else { return }
        let failure = deps.consumeFailure()
        lastInstallFailure = failure
        deferredVersion = deps.consumeDeferral()
        if let recovered = deps.recoverStaged() {
            staged = recovered
            state = .ready(recovered.manifest)
        }
        let previous = defaults.string(forKey: Self.lastLaunchedKey)
        if let currentVersion { defaults.set(currentVersion, forKey: Self.lastLaunchedKey) }
        let justUpdated = previous != nil && previous != currentVersion
        if failure?.serviceStopped == true || justUpdated {
            repairTask = Task { await self.repairServiceOnce(after: failure) }
        }
        terminateObserver = NotificationCenter.default.addObserver(
            forName: NSApplication.willTerminateNotification, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.appWillTerminate() }
        }
        powerOffObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.willPowerOffNotification, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.systemWillPowerOff() }
        }
        let sleep = deps.sleep
        scheduler = Task { [weak self] in
            try? await sleep(Self.firstCheckDelay)
            while !Task.isCancelled {
                guard let self else { return }
                await self.scheduledTick()
                try? await sleep(Self.checkInterval)
            }
        }
    }

    /// The background service, put back once if an update left it stopped — never while Sleep may be writing (an
    /// install stops the app's own backend child). A repaired service retires the "didn't start again" sentence.
    private func repairServiceOnce(after failure: UpdateFailureRecord?) async {
        guard !deps.isSleepWriting(), !SleepProbe.isBusy(await deps.probeSleep(Self.handOffProbeTimeout)) else { return }
        let running = await deps.repairService()
        if running, failure?.installed == true, lastInstallFailure == failure { lastInstallFailure = nil }
    }

    /// Logout, restart or shutdown is on its way: the quit that follows installs nothing.
    func systemWillPowerOff() { poweringOff = true }

    /// One turn of the schedule: a check only while the switch is on.
    func scheduledTick() async {
        guard automatic else { return }
        await check(userInitiated: false)
    }

    // MARK: Check, download, install

    /// `userInitiated` is the app menu's item: it checks whatever the switch says. A check never interrupts a
    /// download, a staged update or an install.
    func check(userInitiated: Bool) async {
        guard isActive, userInitiated || automatic else { return }
        switch state {
        case .checking, .downloading, .ready, .installing: return
        default: break
        }
        state = .checking
        do {
            switch try await deps.check() {
            case .upToDate:
                state = .upToDate(checkedAt: deps.now())
            case .needsNewerMacOS(let manifest, let minimum):
                state = .needsNewerMacOS(manifest, minimum: minimum)
            case .available(let manifest):
                state = .available(manifest)
                if automatic { await download() }
            }
        } catch {
            state = .failed(Copy.Updates.checkFailed(UpdateChecker.Failure.from(error).message))
        }
    }

    /// Download, verify and stage the found version (the switch's background step, or the person's Download).
    func download() async {
        guard isActive, case .available(let manifest) = state else { return }
        state = .downloading(manifest, progress: 0)
        do {
            let result = try await deps.stage(manifest) { [weak self] fraction in
                Task { @MainActor in self?.progressed(manifest, fraction) }
            }
            staged = result
            state = .ready(manifest)
        } catch {
            let reason = (error as? UpdateInstaller.Failure)?.message ?? error.localizedDescription
            state = .failed(Copy.Updates.downloadFailed(reason))
        }
    }

    /// Whole percents only, so a 150 MB download repaints the row a hundred times, not thousands.
    private func progressed(_ manifest: UpdateManifest, _ fraction: Double) {
        guard case .downloading(let current, let shown) = state, current == manifest else { return }
        let next = min(max(fraction, 0), 1)
        if (next * 100).rounded(.down) > (shown * 100).rounded(.down) { state = .downloading(manifest, progress: next) }
    }

    /// "Restart to update": ask the backend fresh, hand off with relaunch, then quit through the normal flow (a held
    /// Inbox answer is still sent, the backend child still stopped). Deferred — a no-op with a sentence — while Sleep
    /// writes.
    func restartToUpdate() async {
        guard isActive, !handedOff, case .ready(let manifest) = state, let staged else { return }
        guard !deps.isSleepWriting() else { return }
        let answer = await deps.probeSleep(Self.handOffProbeTimeout)
        // The state may have moved while the backend answered.
        guard !handedOff, state == .ready(manifest) else { return }
        guard !SleepProbe.isBusy(answer) else {
            sleepRefusedRestart = true
            return
        }
        do {
            try deps.handOff(staged, true)
            handedOff = true
            sleepRefusedRestart = false
            state = .installing(manifest)
            deps.terminate()
        } catch {
            let reason = (error as? UpdateInstaller.Failure)?.message ?? error.localizedDescription
            state = .failed(Copy.Updates.installStartFailed(reason))
        }
    }

    /// The person quit with an update ready: hand off without relaunch. While Sleep writes, or while macOS logs out
    /// or shuts down, nothing is installed. The backend is asked fresh, blocking the quit for at most ~1.5 s (a
    /// notification handler can't await); the helper asks again before anything moves.
    func appWillTerminate() {
        guard isActive, !handedOff, !poweringOff, case .ready = state, let staged else { return }
        guard !deps.isSleepWriting(), !SleepProbe.isBusy(probeBlocking(Self.quitProbeTimeout)) else { return }
        if (try? deps.handOff(staged, false)) != nil { handedOff = true }
    }

    /// The async probe, waited for on this thread. The probe runs off the main actor (a detached task on the global
    /// executor), so blocking here can't deadlock it; no answer in time counts as no answer.
    private func probeBlocking(_ timeout: Duration) -> SleepProbe.Answer {
        final class Box: @unchecked Sendable { var answer: SleepProbe.Answer = .noAnswer }
        let box = Box()
        let done = DispatchSemaphore(value: 0)
        let probe = deps.probeSleep
        Task.detached {
            box.answer = await probe(timeout)
            done.signal()
        }
        let seconds = Double(timeout.components.seconds) + Double(timeout.components.attoseconds) / 1e18
        return done.wait(timeout: .now() + seconds + 0.5) == .timedOut ? .noAnswer : box.answer
    }

    // MARK: Live wiring

    /// The real thing, from this app's Info.plist (`CicadaUpdateRepo`, `CicadaUpdatePublicKey`) and runtime.
    static func live(runtime: CicadaRuntime = .current,
                     info: @escaping (String) -> Any? = { Bundle.main.object(forInfoDictionaryKey: $0) },
                     isSleepWriting: @escaping @MainActor () -> Bool,
                     repairService: @escaping @MainActor () async -> Bool) -> UpdateService {
        let repo = (info(UpdateChecker.repoInfoKey) as? String)?.trimmingCharacters(in: .whitespaces)
        let version = (info("CFBundleShortVersionString") as? String)?.trimmingCharacters(in: .whitespaces)
        let checker = UpdateChecker(repo: repo, currentVersion: version)
        let bundleIdentifier = info("CFBundleIdentifier") as? String ?? Bundle.main.bundleIdentifier
        let installer = UpdateInstaller(
            installedApp: URL(fileURLWithPath: runtime.bundlePath), bundleIdentifier: bundleIdentifier,
            publicKeyBase64: info(UpdateVerifier.publicKeyInfoKey) as? String,
            cicadaHome: runtime.cicadaHome, port: runtime.port)
        let deps = Dependencies(
            check: { try await checker.check() },
            stage: { manifest, progress in try await installer.stage(manifest, progress: progress) },
            handOff: { staged, relaunch in try installer.handOff(staged, relaunch: relaunch, currentVersion: version) },
            terminate: { NSApp.terminate(nil) },
            consumeFailure: { UpdateFailureMarker.consume(home: runtime.cicadaHome) },
            consumeDeferral: { UpdateFailureMarker.consumeDeferral(home: runtime.cicadaHome) },
            recoverStaged: {
                UpdateInstaller.recoverStaged(installedApp: installer.installedApp, helperPIDFile: installer.helperPIDFile,
                                              bundleIdentifier: bundleIdentifier, currentVersion: version)
            },
            isSleepWriting: isSleepWriting,
            probeSleep: SleepProbe.live(port: runtime.port, tokenFile: installer.tokenFile),
            repairService: repairService)
        return UpdateService(runtime: runtime, repoConfigured: UpdateChecker.isValidRepo(repo), currentVersion: version,
                             dependencies: deps)
    }
}
