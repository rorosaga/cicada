import AppKit
import Foundation
import Observation
import OSLog

/// G231 — the per-viewer switch and memory, in the app's defaults (`cicada.connectSuggest.*`): per Mac, outside every
/// bank (`ConnectSuggestMemory` says why).
struct ConnectSuggestStore {
    static let enabledKey = "cicada.connectSuggest.enabled"
    static let memoryKey = "cicada.connectSuggest.memory"

    let defaults: UserDefaults

    /// On unless the person turned it off (`ConnectSuggestPolicy`'s first rule says why).
    var enabled: Bool {
        get { defaults.object(forKey: Self.enabledKey) as? Bool ?? true }
        nonmutating set { defaults.set(newValue, forKey: Self.enabledKey) }
    }

    var memory: ConnectSuggestMemory {
        get {
            guard let data = defaults.data(forKey: Self.memoryKey),
                  let memory = try? JSONDecoder().decode(ConnectSuggestMemory.self, from: data) else { return .init() }
            return memory
        }
        nonmutating set { defaults.set(try? JSONEncoder().encode(newValue), forKey: Self.memoryKey) }
    }
}

/// The app that just came to the front, as values — what `NSWorkspace`'s activation hands over, minus the process.
struct ConnectSuggestActivation: Equatable {
    let bundleId: String?
    let name: String?
    let pid: pid_t
    let launchedAt: Date?
}

/// What shows the suggestion. The live one is `ConnectSuggestPanelController`; tests record calls.
@MainActor
protocol ConnectSuggestPresenting: AnyObject {
    func show(_ center: ConnectSuggestCenter)
    func hide()
}

/// G231 — watches the frontmost app, decides (`ConnectSuggestPolicy`), shows the notch panel and records the answer.
/// Every way the world reaches it is injected, so the respect rules run in tests against a fake clock and a fake
/// front app. Logs ids and enums only (`com.cicada.app`, category `connect-suggest`): the source's catalogue id and
/// the decision or outcome — never a window, a title or anything the app shows.
@MainActor
@Observable
final class ConnectSuggestCenter {
    static let logger = Logger(subsystem: "com.cicada.app", category: "connect-suggest")

    private(set) var state: ConnectSuggestPanelState?
    private(set) var lastDecision: ConnectSuggestPolicy.Decision?
    private(set) var lastOutcome: ConnectSuggestPanelState.Outcome?
    /// The app icon the panel shows beside the worm (the running app's own, from AppKit).
    @ObservationIgnored private(set) var icon: NSImage?

    @ObservationIgnored let store: ConnectSuggestStore
    @ObservationIgnored private weak var presenter: ConnectSuggestPresenting?
    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private let wait: (TimeInterval) async -> Void
    @ObservationIgnored private let launchedAt: Date
    @ObservationIgnored private var observer: NSObjectProtocol?
    @ObservationIgnored private var pendingPid: pid_t?
    @ObservationIgnored private var ticking: Task<Void, Never>?

    // The world, set by the app at launch (`CicadaApp.launch`).
    /// The source's status in the active memory (`SourceCatalog`), nil when not read yet or not in the catalogue here.
    @ObservationIgnored var status: (String) -> SourceCatalogStatus? = { _ in nil }
    @ObservationIgnored var memoryKnown: () -> Bool = { false }
    /// Setup ran or was skipped for the active memory (`OnboardingState`).
    @ObservationIgnored var setUp: () -> Bool = { false }
    @ObservationIgnored var isDemo: () -> Bool = { true }
    @ObservationIgnored var saveWhyOpen: () -> Bool = { false }
    /// The pid in front now, to confirm the app stayed after the dwell.
    @ObservationIgnored var frontmostPid: () -> pid_t? = { NSWorkspace.shared.frontmostApplication?.processIdentifier }
    @ObservationIgnored var iconFor: (pid_t) -> NSImage? = { NSRunningApplication(processIdentifier: $0)?.icon }
    /// Yes: open the source's page (`AppRouter.routeToCatalogEntry`).
    @ObservationIgnored var onYes: (String) -> Void = { _ in }

    /// Whether an open panel's clock ticks by itself (tests send `.tick` by hand).
    @ObservationIgnored private let ticks: Bool
    /// The open panel's own clock (its timeout and its arm delay): monotonic, as the ask-why panel's is, so a wall
    /// clock stepped back can never freeze it. The memory's dates (14 days, one a day) stay on the wall clock.
    @ObservationIgnored private let uptime: () -> TimeInterval

    init(store: ConnectSuggestStore = ConnectSuggestStore(defaults: .standard), now: @escaping () -> Date = Date.init,
         uptime: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
         wait: @escaping (TimeInterval) async -> Void = { try? await Task.sleep(for: .seconds($0)) },
         ticks: Bool = true) {
        self.store = store
        self.now = now
        self.uptime = uptime
        self.wait = wait
        self.ticks = ticks
        self.launchedAt = now()
    }

    var enabled: Bool {
        get { access(keyPath: \.enabled); return store.enabled }
        set {
            withMutation(keyPath: \.enabled) { store.enabled = newValue }
            if !newValue { close(.notNow, record: false) }
        }
    }

    /// The sources the person said No to, with the app name shown when it was suggested.
    var declined: [(id: String, name: String)] {
        access(keyPath: \.declined)
        let memory = store.memory
        return memory.declined.map { ($0, memory.sources[$0]?.name ?? $0) }
    }

    func undoDecline(_ entryId: String) {
        withMutation(keyPath: \.declined) {
            store.memory = ConnectSuggestPolicy.undoDecline(entryId, in: store.memory)
        }
    }

    func attach(presenter: ConnectSuggestPresenting) { self.presenter = presenter }

    /// The notch has two voices and the ask-why question always wins (DESIGN_RULES §9 2026-11-03): no offer starts
    /// while it shows, and an open offer leaves the moment it is about to show — through the question's own center,
    /// which lives as long as the app, so this holds with the main window closed (review of #585).
    func yields(to saveWhy: SaveWhyCenter) {
        saveWhyOpen = { [weak saveWhy] in saveWhy?.state != nil }
        saveWhy.willShow = { [weak self] in self?.yield() }
    }

    func start() {
        guard observer == nil else { return }
        observer = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main) { [weak self] note in
            guard let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication else { return }
            let activation = ConnectSuggestActivation(bundleId: app.bundleIdentifier, name: app.localizedName,
                                                      pid: app.processIdentifier, launchedAt: app.launchDate)
            MainActor.assumeIsolated { self?.activated(activation) }
        }
    }

    /// An app came to the front. Cicada itself coming forward (a Yes, a click on its window) never closes the panel —
    /// a Yes already did; any other app does.
    func activated(_ app: ConnectSuggestActivation) {
        Task { @MainActor [weak self] in await self?.enter(app) }
    }

    /// The whole of one activation, awaitable (tests drive it with an instant `wait`).
    func enter(_ app: ConnectSuggestActivation) async {
        if app.pid == ProcessInfo.processInfo.processIdentifier { return }
        if let open = state, open.bundleId != app.bundleId { input(.appChanged) }
        guard let target = ConnectSuggestApps.target(bundleId: app.bundleId), let bundleId = app.bundleId else {
            pendingPid = nil
            return
        }
        pendingPid = app.pid
        await wait(ConnectSuggestPolicy.dwell)
        dwelt(app, target: target, bundleId: bundleId)
    }

    private func dwelt(_ app: ConnectSuggestActivation, target: ConnectSuggestApps.Target, bundleId: String) {
        // Still the app the person entered, still in front: a ⌘-Tab that passed through it is not entering it.
        guard pendingPid == app.pid, frontmostPid() == app.pid else { return }
        pendingPid = nil
        let context = ConnectSuggestPolicy.Context(
            now: now(), enabled: store.enabled, memoryKnown: memoryKnown(), setUp: setUp(), isDemo: isDemo(),
            status: status(target.entryId), appLaunchedAt: app.launchedAt, cicadaLaunchedAt: launchedAt,
            saveWhyOpen: saveWhyOpen(), showing: state != nil)
        let decision = ConnectSuggestPolicy.decide(target, memory: store.memory, context: context)
        lastDecision = decision
        switch decision {
        case .skip(let why):
            Self.logger.debug("skip \(target.entryId, privacy: .public) \(why.rawValue, privacy: .public)")
        case .suggest:
            show(target, name: app.name ?? target.entryId, bundleId: bundleId, pid: app.pid)
        }
    }

    private func show(_ target: ConnectSuggestApps.Target, name: String, bundleId: String, pid: pid_t) {
        let at = now()
        store.memory = ConnectSuggestPolicy.shown(target.entryId, name: name, at: at, in: store.memory)
        icon = iconFor(pid)
        state = ConnectSuggestPanelState(target: target, appName: name, bundleId: bundleId, shownAt: uptime())
        Self.logger.info("show \(target.entryId, privacy: .public)")
        presenter?.show(self)
        ticking?.cancel()
        guard ticks else { return }
        ticking = Task { @MainActor [weak self] in
            while let self, self.state != nil, !Task.isCancelled {
                await self.wait(0.5)
                self.input(.tick)
            }
        }
    }

    func input(_ input: ConnectSuggestPanelState.Input) {
        guard var open = state else { return }
        let outcome = open.handle(input, at: uptime())
        state = open
        if let outcome { close(outcome, record: true) }
    }

    /// The ask-why question is about to use the notch.
    func yield() { input(.superseded) }

    private func close(_ outcome: ConnectSuggestPanelState.Outcome, record: Bool) {
        guard let open = state else { return }
        state = nil
        ticking?.cancel()
        ticking = nil
        presenter?.hide()
        lastOutcome = outcome
        if record {
            store.memory = ConnectSuggestPolicy.answered(open.target.entryId, outcome.answer, at: now(),
                                                         in: store.memory)
        }
        Self.logger.info("close \(open.target.entryId, privacy: .public) \(outcome.name, privacy: .public)")
        if outcome == .yes { onYes(open.target.entryId) }
    }
}
