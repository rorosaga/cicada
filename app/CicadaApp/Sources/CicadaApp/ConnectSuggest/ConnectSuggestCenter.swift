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
    /// Yes: connect the source through the one plan (`NotchConnector`, which is `SourceConnect`): turn on what one click
    /// can, or open the source's page where a choice is needed. Answers what it came to; the write returns before
    /// anything is confirmed, so the words are "Turned on", never "Connected".
    @ObservationIgnored var connect: (String) async -> ConnectSuggestResult = { _ in .openedPage }
    /// The setting the panel's one button opens (Accessibility), a preflight link: never a prompt.
    @ObservationIgnored var openSetting: (MacPermission) -> Void = { _ in }
    /// G221 (ruling 77b) — a site's offer was answered Yes while it held saves the person had just made there: keep
    /// them (store, learn, ask why). Called after `onYes`, once the panel has left.
    @ObservationIgnored var onHeld: ([SiteSaveCandidate]) -> Void = { _ in }
    /// The saves the open offer holds, oldest first: in memory only, dropped with any answer but Yes.
    @ObservationIgnored private(set) var held: [SiteSaveCandidate] = []
    static let heldMax = 8
    /// One press of Yes, and everything that belongs to it alone: the saves it keeps once what it turned on has come back,
    /// and what it came to (nil while it is still turning on). Per press, never shared: a Yes still connecting after its
    /// panel left must keep ITS saves, and a second site's offer shown meanwhile must neither lend its held saves to it nor
    /// lose them (G245 finish).
    private final class Press {
        let entryId: String
        var saves: [SiteSaveCandidate]
        var result: ConnectSuggestResult?
        init(entryId: String, saves: [SiteSaveCandidate]) { self.entryId = entryId; self.saves = saves }
    }

    /// The press on the open panel, nil when Yes was not pressed on it (a press whose panel left lives on in its own task).
    @ObservationIgnored private var current: Press?
    @ObservationIgnored private var connecting: [Task<Void, Never>] = []

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
        return memory.declined.filter(ConnectSuggestApps.offered).map { ($0, memory.sources[$0]?.name ?? $0) }
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
        // `isShowing`, not `state != nil`: the question's last state stays after it closes, which silenced every offer
        // for the rest of the session once one question had shown (found 2026-11-24).
        saveWhyOpen = { [weak saveWhy] in saveWhy?.isShowing == true }
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

    /// An app came to the front. It never closes an open panel (owner 2026-11-25: only the person's answer or the
    /// panel's own bar does); it may be an app worth offering once the open one is gone.
    func activated(_ app: ConnectSuggestActivation) {
        Task { @MainActor [weak self] in await self?.enter(app) }
    }

    /// The whole of one activation, awaitable (tests drive it with an instant `wait`).
    func enter(_ app: ConnectSuggestActivation) async {
        if app.pid == ProcessInfo.processInfo.processIdentifier { return }
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

    /// G221 — the page in the front browser is on a site whose saves Cicada can notice and the person has not
    /// connected it: the same offer, the same rules (the switch, once a day, No is kept, Not now waits), with the
    /// site's own mark. `connected` is the site's switch on this Mac; the source's own state is the catalogue's
    /// (`status`, the word its page shows), so a source the page shows as set up is never offered (plan section 7).
    /// Answers whether the visit is spent: false only for a refusal about the moment (`Skip.passes`), which the next
    /// rest on the same page asks again.
    @discardableResult
    func offer(site: SiteSaveSite, connected: Bool, pid: pid_t, bundleId: String,
               trigger: ConnectSuggestPolicy.Trigger = .entered) -> Bool {
        let target = ConnectSuggestApps.site(site.key)
        let context = ConnectSuggestPolicy.Context(
            now: now(), enabled: store.enabled, memoryKnown: memoryKnown(), setUp: setUp(), isDemo: isDemo(),
            status: connected ? .connected : status(site.key), appLaunchedAt: nil, cicadaLaunchedAt: launchedAt,
            saveWhyOpen: saveWhyOpen(), showing: state != nil)
        let decision = ConnectSuggestPolicy.decide(target, memory: store.memory, context: context, trigger: trigger)
        lastDecision = decision
        guard case .suggest = decision else {
            if case .skip(let why) = decision { return !why.passes }
            return true
        }
        let mark = OriginIconography.logoName(for: site.origin).flatMap(LogoImage.bundledImageNow(for:))
        show(target, name: site.name, bundleId: bundleId, pid: pid, icon: mark, trigger: trigger)
        return true
    }

    /// G221 (ruling 77b, owner 2026-11-24) — the person clicked the save control of a site they have not connected:
    /// the offer shows at that moment and holds the save, which only Yes keeps. An offer for that site already open
    /// takes the save too, so a Yes pressed after it keeps it.
    func offer(saved save: SiteSaveCandidate, site: SiteSaveSite, pid: pid_t, bundleId: String) {
        let target = ConnectSuggestApps.site(site.key)
        guard save.offers else {
            // The person took it off again before answering: the offer lets go of it (and never shows for an unsave).
            if state?.target == target, current == nil {
                held.removeAll { $0.item == save.item }
                state?.keepsSave = held.contains { $0.outcome == .saved }
            }
            return
        }
        if let open = state, open.target == target {
            guard let press = current else {
                hold(save)
                return
            }
            // Yes was already pressed: the save is kept once it has turned on (now, if it already has).
            if let result = press.result {
                if !result.isFailure { onHeld([save]) }
            } else {
                press.saves.append(save)
            }
            return
        }
        offer(site: site, connected: false, pid: pid, bundleId: bundleId, trigger: .saveClick)
        if state?.target == target, lastDecision == .suggest { hold(save) }
    }

    /// Whether a save click on this site could bring its offer now (ruling 77b): only then is a site that is not
    /// connected read at all. Never in a demo memory, before setup, with the switch off, or for a site the memory
    /// says not to offer.
    func listens(site key: String) -> Bool {
        store.enabled && memoryKnown() && setUp() && !isDemo()
            && (status(key).map { $0 == .off } ?? true)     // a source the page shows as set up is never offered
            && ConnectSuggestPolicy.listens(ConnectSuggestApps.site(key), memory: store.memory, now: now())
    }

    private func hold(_ save: SiteSaveCandidate) {
        held.removeAll { $0.item == save.item }
        held.append(save)
        if held.count > Self.heldMax { held.removeFirst(held.count - Self.heldMax) }
        state?.keepsSave = held.contains { $0.outcome == .saved }
    }

    private func show(_ target: ConnectSuggestApps.Target, name: String, bundleId: String, pid: pid_t,
                      icon mark: NSImage? = nil, trigger: ConnectSuggestPolicy.Trigger = .entered) {
        let at = now()
        store.memory = ConnectSuggestPolicy.shown(target.entryId, name: name, at: at, trigger: trigger,
                                                  in: store.memory)
        held = []
        current = nil
        icon = mark ?? iconFor(pid)
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
        let confirmed = open.confirmedAt != nil
        let outcome = open.handle(input, at: uptime())
        state = open
        if !confirmed, open.confirmedAt != nil { begin(open.target.entryId) }
        if input == .openSetting, outcome != nil { openSetting(.accessibility) }
        if let outcome { close(outcome, record: true) }
    }

    /// The Yes was pressed: run the one connect plan. The panel says "Turning on…" until it comes back; the answer is
    /// kept the moment it does (a quit while the panel confirms keeps it), Not now when it was refused.
    private func begin(_ entryId: String) {
        // The saves the offer held are this press's from here on; the next offer starts from nothing.
        let press = Press(entryId: entryId, saves: held)
        held = []
        current = press
        let connect = self.connect
        connecting.append(Task { @MainActor [weak self] in
            let came = await connect(entryId)
            self?.finished(came, press: press)
        })
    }

    private func finished(_ came: ConnectSuggestResult, press: Press) {
        let entryId = press.entryId
        Self.logger.info("connect \(entryId, privacy: .public) \(came.logName, privacy: .public)")
        let open = current === press && state?.target.entryId == entryId && state?.isConnecting == true
        if open || came.isFailure {
            store.memory = ConnectSuggestPolicy.answered(entryId, came.isFailure ? .notNow : .yes, at: now(),
                                                         in: store.memory)
        }
        if !came.isFailure, !press.saves.isEmpty { onHeld(press.saves) }
        press.saves = []
        press.result = came
        guard open, var panel = state else { return }
        let outcome = panel.finish(came, at: uptime())
        state = panel
        if let outcome { close(outcome, record: false) }
    }

    /// The ask-why question is about to use the notch.
    func yield() { input(.superseded) }

    /// Tests: wait for the Yes's connect to come back.
    func settle() async {
        for task in connecting { await task.value }
        connecting = []
    }

    private func close(_ outcome: ConnectSuggestPanelState.Outcome, record: Bool) {
        guard let open = state else { return }
        state = nil
        ticking?.cancel()
        ticking = nil
        presenter?.hide()
        lastOutcome = outcome
        // The saves the offer held are kept only on Yes, once the Yes has turned something on; any other answer drops
        // them here, unread by anything else. A Yes that has not finished keeps them for when it does.
        let pressedYes = current != nil
        held = []
        current = nil
        if record, open.result == nil || !pressedYes {
            store.memory = ConnectSuggestPolicy.answered(open.target.entryId, outcome.answer, at: now(),
                                                         in: store.memory)
        }
        Self.logger.info("close \(open.target.entryId, privacy: .public) \(outcome.name, privacy: .public)")
    }
}

extension ConnectSuggestResult {
    /// The log's name for it (an enum, never text).
    var logName: String {
        switch self {
        case .turnedOn: "turned_on"
        case .openedPage: "opened_page"
        case .failed: "failed"
        }
    }
}
