import Foundation
import Observation

/// G191 — how a finished bookmark sync reaches the question. The watcher marks the syncs its own file watch started
/// (`live`, a task-local, so `BrowserImportActions.syncChannel` needs no new parameter and every other caller — a
/// catch-up, a Sync now, an import — stays not-live by default); `syncChannel` hands every bookmark result here.
enum BookmarkSyncSignal {
    @TaskLocal static var live = false

    /// The one listener (the app's `SaveWhyCenter`); nil in tests and before launch finishes.
    @MainActor static var observer: (@MainActor (BookmarkSyncResult, Bool) -> Void)?

    @MainActor static func post(_ result: BookmarkSyncResult) {
        observer?(result, live)
    }
}

/// What shows the panel. The live one is `SaveWhyPanelController` (an `NSPanel`); tests record calls.
@MainActor
protocol SaveWhyPresenting: AnyObject {
    func show(_ center: SaveWhyCenter)
    func hide()
    func focusText()
}

/// G191 — decides, asks, and posts. Holds the open panel's state; the panel view reads it and sends events back.
/// The answer itself is the backend's business (`POST /sources/saved-why`): the app only shows the panel and posts.
@MainActor
@Observable
final class SaveWhyCenter {
    private(set) var state: SaveWhyPanelState?
    private(set) var options = SavedWhyOptions()
    /// The last way a panel closed — for tests and diagnostics, never shown.
    private(set) var lastOutcome: SaveWhyPanelState.Outcome?
    /// The last decision the policy took, likewise.
    private(set) var lastDecision: SaveWhyPolicy.Decision?
    private(set) var lastPostFailed = false

    @ObservationIgnored let prefs: SaveWhyPrefs
    @ObservationIgnored private let api: any SavedWhyAPI
    @ObservationIgnored private weak var presenter: (any SaveWhyPresenting)?
    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private var timer: Task<Void, Never>?
    @ObservationIgnored private var posting: Task<Void, Never>?

    init(prefs: SaveWhyPrefs = SaveWhyPrefs(defaults: .standard), api: any SavedWhyAPI = APIClient.shared,
         presenter: (any SaveWhyPresenting)? = nil, now: @escaping () -> Date = Date.init) {
        self.prefs = prefs
        self.api = api
        self.presenter = presenter
        self.now = now
    }

    func attach(presenter: any SaveWhyPresenting) { self.presenter = presenter }

    /// Listen to every bookmark sync from now on.
    func start() {
        BookmarkSyncSignal.observer = { [weak self] result, live in
            Task { @MainActor in await self?.noticed(result, live: live) }
        }
    }

    var isShowing: Bool { state?.isOpen == true }

    /// A bookmark sync finished. Asks only when `SaveWhyPolicy` says so; otherwise does nothing at all.
    func noticed(_ result: BookmarkSyncResult, live: Bool) async {
        let decision = SaveWhyPolicy.decide(.init(
            enabled: prefs.enabled, live: live, result: result, now: now(), lastAsked: prefs.lastAsked,
            mutedHosts: prefs.mutedHosts, showing: isShowing))
        lastDecision = decision
        guard case .ask(let item) = decision else { return }
        // Counted from the decision, so a second sync during the options read cannot ask twice.
        prefs.lastAsked = now()
        guard let fetched = try? await api.savedWhyOptions(), !fetched.reasons.isEmpty else { return }
        guard !isShowing else { return }
        options = fetched
        state = SaveWhyPanelState(item: item, order: fetched.reasons.map(\.key), maxText: fetched.maxText)
        presenter?.show(self)
        run(SaveWhyPanelState.opening())
    }

    func send(_ event: SaveWhyPanelState.Event) {
        guard var current = state else { return }
        let effects = current.send(event)
        state = current
        run(effects)
    }

    private func run(_ effects: [SaveWhyPanelState.Effect]) {
        for effect in effects {
            switch effect {
            case .startTimer(let seconds):
                timer?.cancel()
                timer = Task { @MainActor [weak self] in
                    try? await Task.sleep(for: .seconds(seconds))
                    guard !Task.isCancelled, let self, let phase = self.state?.phase else { return }
                    self.send(phase == .answered ? .lingerElapsed : .timeout)
                }
            case .focusText:
                presenter?.focusText()
            case .post(let answer):
                guard let url = state?.item.url else { continue }
                posting = Task { @MainActor [weak self, api] in
                    do { try await api.saveWhy(url: url, answer: answer); self?.lastPostFailed = false }
                    catch { self?.lastPostFailed = true }
                }
            case .mute(let host):
                prefs.mute(host)
            case .close:
                timer?.cancel()
                timer = nil
                if case .closed(let outcome)? = state?.phase { lastOutcome = outcome }
                presenter?.hide()
            }
        }
    }

    /// Tests: wait for the answer's request to finish.
    func settle() async { await posting?.value }
}
