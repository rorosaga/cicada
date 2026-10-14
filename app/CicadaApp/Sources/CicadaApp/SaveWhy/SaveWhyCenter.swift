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
        /// A sync finished whose bookmarks an early look (numbered `look`) already decided about: every link that look
        /// or an earlier one saw is saved now.
        case afterEarlyLook(look: Int)
    }

    /// The one listener (the app's `SaveWhyCenter`); nil in tests and before launch finishes.
    @MainActor static var observer: (@MainActor (BookmarkSyncResult, Delivery) -> Void)?
    /// The early look (the center's `lookEarly`): the look's number when it looked, whatever it decided; nil when not.
    @MainActor static var early: (@MainActor (BookmarkBytes, Int) async -> Int?)?
    /// The center's look numbers (`SaveWhyCenter.takeLook`).
    @MainActor static var numberLook: (@MainActor () -> Int)?

    /// A look's number, taken BEFORE its file is read (review B2): a sync that read the file before bookmark C existed
    /// must never carry a higher number than C's own look, or its landing would release C's held answer to a 404 that
    /// is then final. Numbering by read order means a higher number always read newer bytes. Nil when not live.
    @MainActor static func takeLook() -> Int? {
        guard live, let numberLook else { return nil }
        return numberLook()
    }

    /// Only a live sync looks early — a catch-up, Sync now, Turn on or import is never a moment of saving.
    @MainActor static func lookEarly(_ bytes: BookmarkBytes, look: Int?) async -> Int? {
        guard live, let look, let early else { return nil }
        return await early(bytes, look)
    }

    @MainActor static func post(_ result: BookmarkSyncResult, lookedEarly: Int? = nil) {
        observer?(result, lookedEarly.map { .afterEarlyLook(look: $0) } ?? .synced(live: live))
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
    @ObservationIgnored private(set) var awaitingIngest: [String: (channel: String, look: Int)] = [:]
    /// Every link an early look saw as fresh, with that look's number, until a sync that read after it lands.
    @ObservationIgnored private(set) var seenFresh: [String: (channel: String, look: Int)] = [:]
    @ObservationIgnored private var lookCount = 0
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
                case .afterEarlyLook(let look): await self?.ingested(result, look: look)
                }
            }
        }
        BookmarkSyncSignal.early = { [weak self] bytes, look in await self?.lookEarly(bytes, look: look) }
        BookmarkSyncSignal.numberLook = { [weak self] in self?.takeLook() ?? 0 }
        Task { await refreshOptions() }
    }

    /// G191 live — the early look: decide on the bookmarks in `bytes` the bank does not hold yet, before the sync
    /// that saves them. Nil when it did not look (the switch off, the person typing, or no answer — an older
    /// backend), so the sync's own result decides as before; else the look's number, which the sync hands back
    /// when it lands (`ingested`).
    ///
    /// **A save while an earlier sync still runs (measured 2026-10-14: the second of two bookmarks 12 s apart asked
    /// only after +12 s).** The watcher looks at once for such a save (`BrowserWatcher`'s `peek`) instead of waiting
    /// for the sync ahead. Its bytes then hold the earlier bookmark too, not saved yet — so every link a look saw as
    /// fresh is remembered (`seenFresh`) until a sync that read after it lands, and a later look subtracts what an
    /// earlier one already saw: "one fresh bookmark" means one new since the last look, not two.
    func lookEarly(_ bytes: BookmarkBytes, look given: Int? = nil) async -> Int? {
        guard prefs.enabled, state?.phase != .writing else { return nil }
        let look = given ?? takeLook()   // the caller's, taken before it read `bytes`
        let options = cachedOptions == nil ? Task { await refreshOptions() } : nil
        guard let result = try? await api.freshBookmarks(bytes) else { return nil }
        await options?.value
        await noticed(newSinceEarlierLooks(result, look: look), live: true, early: look)
        return look
    }

    /// The next look's number — the caller takes it just before reading the file (`BookmarkSyncSignal.takeLook`).
    func takeLook() -> Int {
        lookCount += 1
        return lookCount
    }

    /// `result` without the links another look already saw (their syncs not landed yet); records the rest. A link
    /// keeps the lowest number that saw it: a sync whose look read it is the one whose landing saves it.
    func newSinceEarlierLooks(_ result: BookmarkSyncResult, look: Int) -> BookmarkSyncResult {
        var out = result
        let seenBefore = result.fresh.filter { seenFresh[$0.url] != nil }
        for item in result.fresh {
            if let seen = seenFresh[item.url] { seenFresh[item.url] = (seen.channel, min(seen.look, look)) }
            else { seenFresh[item.url] = (item.channel, look) }
        }
        let before = Set(seenBefore.map(\.url))
        out.fresh = result.fresh.filter { !before.contains($0.url) }
        out.freshTotal = max(0, result.freshTotal - seenBefore.count)
        return out
    }

    /// The sync after early look `look` finished: every link that look or an earlier one saw on its channels is
    /// saved now, so a held answer can land. A link a later look saw waits for its own sync.
    func ingested(_ result: BookmarkSyncResult, look: Int) async {
        let channels = Set(result.sources.map(\.channel))
        let landed: ((channel: String, look: Int)) -> Bool = { channels.contains($0.channel) && $0.look <= look }
        awaitingIngest = awaitingIngest.filter { !landed($0.value) }
        seenFresh = seenFresh.filter { !landed($0.value) }
        await retryHeld()
    }

    func refreshOptions() async {
        if let fetched = try? await api.savedWhyOptions(), !fetched.reasons.isEmpty { cachedOptions = fetched }
    }

    var isShowing: Bool { state?.isOpen == true }

    /// A bookmark sync finished. Asks only when `SaveWhyPolicy` says so; otherwise does nothing at all.
    func noticed(_ result: BookmarkSyncResult, live: Bool, early: Int? = nil) async {
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
        if let early { awaitingIngest[item.url] = (item.channel, early) }
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
