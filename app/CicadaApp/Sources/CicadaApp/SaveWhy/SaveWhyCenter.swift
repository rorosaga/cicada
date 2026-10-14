import Foundation
import Observation

/// G191 — how a finished bookmark sync reaches the question. The watcher marks the syncs its own file watch started
/// (`live`, a task-local, so `BrowserImportActions.syncChannel` needs no new parameter and every other caller — a
/// catch-up, a Sync now, an import — stays not-live by default); `syncChannel` hands every bookmark result here.
///
/// **G191 live (2026-10-14): the early look.** Measured on the owner's Mac, the panel came 18 s after the save: the
/// sync answers only after it has fetched each new page and made two commits (6-7 s), and `Store.perform` then waits
/// for four domains to reconcile before `syncChannel` posts its result. So a live sync first sends the same bytes to
/// the read-only `POST /sources/sync-bookmarks/fresh` (`lookEarly`) — a parse and an index check — and the question is
/// decided on that; the sync's own result then only says the link is saved (`afterEarlyLook`), so an answer that got
/// there first can be posted.
enum BookmarkSyncSignal {
    @TaskLocal static var live = false

    enum Delivery: Equatable {
        /// A sync finished; `live` when the watch started it and no early look spoke for it.
        case synced(live: Bool)
        /// A sync finished whose bookmarks an early look already decided about: its links are saved now.
        case afterEarlyLook
    }

    /// The one listener (the app's `SaveWhyCenter`); nil in tests and before launch finishes.
    @MainActor static var observer: (@MainActor (BookmarkSyncResult, Delivery) -> Void)?
    /// The early look (the center's `lookEarly`): true when it looked, whatever it decided.
    @MainActor static var early: (@MainActor (BookmarkBytes) async -> Bool)?

    /// Only a live sync looks early — a catch-up, Sync now, Turn on or import is never a moment of saving.
    @MainActor static func lookEarly(_ bytes: BookmarkBytes) async -> Bool {
        guard live, let early else { return false }
        return await early(bytes)
    }

    @MainActor static func post(_ result: BookmarkSyncResult, lookedEarly: Bool = false) {
        observer?(result, lookedEarly ? .afterEarlyLook : .synced(live: live))
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
    /// Answers held for a retry (review B1) — how many, for tests and diagnostics.
    var heldCount: Int { outbox.entries.count }

    @ObservationIgnored let prefs: SaveWhyPrefs
    @ObservationIgnored let outbox: SaveWhyOutbox
    @ObservationIgnored private var retrying = false
    @ObservationIgnored private let api: any SavedWhyAPI
    @ObservationIgnored private weak var presenter: (any SaveWhyPresenting)?
    @ObservationIgnored private let now: () -> Date
    /// A monotonic clock for the input guard (`input`), apart from `now` so a test can hold one and move the other.
    @ObservationIgnored private let uptime: () -> TimeInterval
    @ObservationIgnored private var shownAt: TimeInterval?
    /// The options last fetched, so a question shows at once; refreshed after each one is asked.
    @ObservationIgnored private(set) var cachedOptions: SavedWhyOptions?
    /// Links asked about from an early look whose sync has not said they are saved yet (url → channel): an answer
    /// the backend refuses with 404 meanwhile is held, not dropped, and sent when the sync lands.
    @ObservationIgnored private(set) var awaitingIngest: [String: String] = [:]
    /// The last input the guard ignored — for tests and diagnostics, never shown.
    private(set) var lastIgnored: SaveWhyPanelState.Event?
    @ObservationIgnored private var timer: Task<Void, Never>?
    @ObservationIgnored private var posting: Task<Void, Never>?
    /// The debug harness's panel (`preview`): answered like any other, but nothing is posted or muted.
    @ObservationIgnored private(set) var previewing = false

    init(prefs: SaveWhyPrefs = SaveWhyPrefs(defaults: .standard), api: any SavedWhyAPI = APIClient.shared,
         presenter: (any SaveWhyPresenting)? = nil, now: @escaping () -> Date = Date.init,
         uptime: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.prefs = prefs
        self.outbox = SaveWhyOutbox(defaults: prefs.defaults)
        self.api = api
        self.presenter = presenter
        self.now = now
        self.uptime = uptime
    }

    func attach(presenter: any SaveWhyPresenting) { self.presenter = presenter }

    /// Listen to every bookmark sync from now on.
    func start() {
        BookmarkSyncSignal.observer = { [weak self] result, delivery in
            Task { @MainActor in
                switch delivery {
                case .synced(let live): await self?.noticed(result, live: live)
                case .afterEarlyLook: await self?.ingested(result)
                }
            }
        }
        BookmarkSyncSignal.early = { [weak self] bytes in await self?.lookEarly(bytes) ?? false }
        Task { await refreshOptions() }
    }

    /// G191 live — the early look: decide on the bookmarks in `bytes` the bank does not hold yet, before the sync
    /// that saves them. False when it did not look (the switch off, a panel open, or no answer — an older backend),
    /// so the sync's own result decides as before.
    func lookEarly(_ bytes: BookmarkBytes) async -> Bool {
        guard prefs.enabled, state?.phase != .writing else { return false }
        let options = cachedOptions == nil ? Task { await refreshOptions() } : nil
        guard let result = try? await api.freshBookmarks(bytes) else { return false }
        await options?.value
        await noticed(result, live: true, early: true)
        return true
    }

    /// The sync after an early look finished: its links are saved, so a held answer can land now.
    func ingested(_ result: BookmarkSyncResult) async {
        let channels = Set(result.sources.map(\.channel))
        awaitingIngest = awaitingIngest.filter { !channels.contains($0.value) }
        await retryHeld()
    }

    func refreshOptions() async {
        if let fetched = try? await api.savedWhyOptions(), !fetched.reasons.isEmpty { cachedOptions = fetched }
    }

    var isShowing: Bool { state?.isOpen == true }

    /// A bookmark sync finished. Asks only when `SaveWhyPolicy` says so; otherwise does nothing at all.
    func noticed(_ result: BookmarkSyncResult, live: Bool, early: Bool = false) async {
        let decision = SaveWhyPolicy.decide(.init(
            enabled: prefs.enabled, live: live, result: result, now: now(), lastAsked: prefs.lastAsked,
            mutedHosts: prefs.mutedHosts, writing: state?.phase == .writing, lastURL: prefs.lastURL))
        lastDecision = decision
        guard case .ask(let item) = decision else { return }
        // Counted from the decision, so a second sync during the options read cannot ask twice.
        prefs.lastAsked = now()
        prefs.lastURL = item.url
        // The options already in hand show it at once (G191 live); the first question waits for them.
        let fetched: SavedWhyOptions
        if let cachedOptions {
            fetched = cachedOptions
            Task { await refreshOptions() }
        } else {
            await refreshOptions()
            guard let cachedOptions else { return }
            fetched = cachedOptions
        }
        // G191 live: a newer bookmark replaces the open question — the person is looking at the new page now, and the
        // old one's moment has passed; a tap already made there is kept and posted (`superseded` closes like a
        // timeout). A queue would ask about a page they have left. Never while they are writing (the policy).
        if isShowing {
            guard state?.phase != .writing else { return }
            send(.superseded)
        }
        if early { awaitingIngest[item.url] = item.channel }
        previewing = false
        options = fetched
        state = SaveWhyPanelState(item: item, order: fetched.reasons.map(\.key), maxText: fetched.maxText)
        shownAt = uptime()
        presenter?.show(self)
        run(SaveWhyPanelState.opening())
    }

    /// The debug harness (`SaveWhyPreview`): show the panel now for a sample bookmark from `channel`'s browser, with
    /// the backend's options when it answers and the sample's when it does not. Skips every rule — that is the point —
    /// and writes nothing: an answer is not posted, a muted site is not remembered, the rate limit is not touched.
    func preview(channel: String) async {
        let fetched = (try? await api.savedWhyOptions()).flatMap { $0.reasons.isEmpty ? nil : $0 }
            ?? SaveWhyPreview.sampleOptions
        if isShowing { send(.escape) }
        previewing = true
        options = fetched
        let item = SaveWhyPreview.sample(channel: channel)
        state = SaveWhyPanelState(item: item, order: fetched.reasons.map(\.key), maxText: fetched.maxText)
        shownAt = uptime()
        presenter?.show(self)
        run(SaveWhyPanelState.opening())
    }

    /// G191 live — the person's own input from the panel: every button and click the view forwards comes through
    /// here. Measured 2026-10-14: "Something else…" was found selected with its field open, nothing typed. The panel
    /// now shows within two seconds of the save — while the person's hand is still on the page beneath it — so a
    /// click that lands on the panel before `SaveWhyPolicy.armDelay` has passed was aimed at what was there before,
    /// and chooses nothing (nor closes it). Keys reach the panel only once a click inside made it key
    /// (`SaveWhyNSPanel`). Timers, Esc and the backend never choose: only `tapOther` opens the field.
    func input(_ event: SaveWhyPanelState.Event) {
        let guarded: Bool
        switch event {
        case .tapReason, .tapProject, .tapOther, .dontAskForSite, .clickOutside: guarded = true
        default: guarded = false
        }
        if guarded, let shownAt, uptime() - shownAt < SaveWhyPolicy.armDelay {
            lastIgnored = event
            return
        }
        send(event)
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
                guard !previewing, let url = state?.item.url else { continue }
                let entry = SaveWhyOutbox.Entry(url: url, answer: answer, at: now())
                posting = Task { @MainActor [weak self] in await self?.deliver(entry) }
            case .mute(let host):
                if !previewing { prefs.mute(host) }
            case .close:
                timer?.cancel()
                timer = nil
                if case .closed(let outcome)? = state?.phase { lastOutcome = outcome }
                presenter?.hide()
            }
        }
    }

    /// Send one answer; a failure that may pass (Sleep writing, the backend away) holds it for `retryHeld`.
    private func deliver(_ entry: SaveWhyOutbox.Entry) async {
        do {
            try await api.saveWhy(url: entry.url, answer: entry.answer, at: entry.at)
        } catch {
            if SaveWhyOutbox.verdict(for: error) == .hold || waitsForIngest(entry.url, error) { outbox.hold(entry) }
        }
    }

    /// A 404 for a link an early look asked about, before its sync said it was saved: not refused, early.
    private func waitsForIngest(_ url: String, _ error: Error) -> Bool {
        guard awaitingIngest[url] != nil, case APIError.httpError(404, _) = error else { return false }
        return true
    }

    /// Send every held answer again — called when Sleep's writing flag goes false and on launch. One pass at a time;
    /// an answer that fails again with a passing error stays held, one refused for good or over a day old is dropped.
    func retryHeld() async {
        guard !retrying else { return }
        retrying = true
        defer { retrying = false }
        for entry in outbox.entries {
            if outbox.expired(entry, now: now()) { outbox.remove(entry); continue }
            do {
                try await api.saveWhy(url: entry.url, answer: entry.answer, at: entry.at)
                outbox.remove(entry)
            } catch {
                if waitsForIngest(entry.url, error) { continue }   // its sync has not landed yet: keep it
                if SaveWhyOutbox.verdict(for: error) == .drop { outbox.remove(entry) }
                else { break }   // still refused (Sleep again, or away): wait for the next signal
            }
        }
    }

    /// Tests: wait for the answer's request to finish.
    func settle() async { await posting?.value }
}
