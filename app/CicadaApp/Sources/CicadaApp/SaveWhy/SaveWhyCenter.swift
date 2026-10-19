import Foundation
import Observation
import OSLog

/// G191 v4 — the stage timings of the question, on a monotonic clock: when a browser's file event came, when the
/// instant look had read the file, diffed it, and when the panel showed. Durations only — never a link, a title or a
/// site — logged once per question (`com.cicada.app`, category `save-why`) so a live measurement can tell where time
/// goes: `log stream --predicate 'subsystem == "com.cicada.app" AND category == "save-why"'`.
enum SaveWhyTimings {
    static let logger = Logger(subsystem: "com.cicada.app", category: "save-why")

    struct Look: Equatable, Sendable {
        var event: TimeInterval
        var read: TimeInterval?
        var diffed: TimeInterval?
        var named = false
    }

    static func now() -> TimeInterval { ProcessInfo.processInfo.systemUptime }

    /// "file event → panel 212 ms" in whole milliseconds.
    static func ms(_ seconds: TimeInterval) -> Int { Int((seconds * 1000).rounded()) }
}

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

    /// G191 v3 — the app's own diff (`BookmarkFileDiff`) found one bookmark saved since its last read: the center's
    /// `candidate`, which names the link at once while the early look still decides.
    @MainActor static var offer: (@MainActor (FreshBookmark) -> Void)?
    /// G191 v4 — a live read of `channel` found a bookmark removed and none added (`BookmarkFileDiff`).
    @MainActor static var removed: (@MainActor (String) -> Void)?
    /// G191 v4 — when each channel's last file event came (`SaveWhyTimings.now()`), set by the watcher's instant look:
    /// the panel logs how long after it showed.
    @MainActor static var eventAt: [String: TimeInterval] = [:]

    /// Diff the bytes just read (every read records the baseline; only a live one can name a bookmark) beside the
    /// early look, and hand a named bookmark to the center as soon as the diff has it — not after the look's reply.
    @MainActor static func diffAndLook(channel: String, data: Data, bytes: BookmarkBytes, look: Int?) async -> Int? {
        let live = self.live
        async let looked = lookEarly(bytes, look: look)
        if let named = await BookmarkFileDiff.shared.observe(channel: channel, data: data, live: live) {
            offer?(named)
        } else if live, (BookmarkFileDiff.shared.removedOnLastRead[channel] ?? 0) > 0 {
            removed?(channel)
        }
        return await looked
    }
}

/// What shows the panel. The live one is `SaveWhyPanelController` (an `NSPanel`); tests record calls.
@MainActor
protocol SaveWhyPresenting: AnyObject {
    func show(_ center: SaveWhyCenter)
    func hide()
    /// 2026-10-19 — close, and when the panel held the keyboard and the person did not leave by clicking somewhere
    /// else (Save, Return, Esc, a newer bookmark), hand the keyboard back to the browser they were in.
    func hide(returnFocus: Bool)
    func focusText()
}

extension SaveWhyPresenting {
    func hide(returnFocus: Bool) { hide() }
}

/// G191 — decides, asks, and posts. Holds the open panel's state; the panel view reads it and sends events back.
/// The answer itself is the backend's business (`POST /sources/saved-why`): the app only shows the panel and posts.
///
/// **G191 v3 — three ways in, one answer.** The question can open before the backend has decided anything:
///
/// 1. `bubbleSeen` — Chrome showed its bookmark bubble (`BookmarkBubbleWatcher`): the panel opens at once, pending,
///    with no link yet;
/// 2. `candidate` — the app's own diff of the file Chrome just wrote named one bookmark (`BookmarkFileDiff`): the link
///    fills in (or the panel opens with it);
/// 3. `noticed` — the early look or the sync decided, as before.
///
/// A panel opened by 1 or 2 is **unconfirmed**: the person can tap and type, but nothing is posted until 3 agrees
/// about a bookmark on that browser — then the panel binds to it and an answer already given is sent. If 3 refuses
/// it (a first sync, many at once, an old bookmark, a muted site) or nothing comes within `SaveWhyPolicy.pendingBound`
/// (`confirmBound` once the diff named a link), an untouched panel withdraws — never saved against a guess.
/// 2026-10-19: what the person gave is never dropped for it — a touched panel stays, and an answer about a link the
/// diff named waits in the outbox for its browser's sync (`withdraw`, `syncLanded`). G191 v4 (owner 2026-10-15): the bubble is a trigger, never a fact — the file alone confirms. G191 v5
/// (2026-10-16): only a window of a shape a bookmark confirmed is the bubble, so a toolbar menu never opens it.
@MainActor
@Observable
final class SaveWhyCenter {
    private(set) var state: SaveWhyPanelState?
    private(set) var options = SavedWhyOptions()
    /// Whether the backend agreed to ask about the open panel's bookmark (always, for a panel `noticed` opened).
    private(set) var confirmed = true
    /// The last way a panel closed — for tests and diagnostics, never shown.
    private(set) var lastOutcome: SaveWhyPanelState.Outcome?
    /// The last decision the policy took, likewise.
    private(set) var lastDecision: SaveWhyPolicy.Decision?
    /// Answers held for a retry (review B1) — how many, for tests and diagnostics.
    var heldCount: Int { outbox.entries.count }

    @ObservationIgnored let prefs: SaveWhyPrefs
    @ObservationIgnored let outbox: SaveWhyOutbox
    @ObservationIgnored private var retrying = false
    /// The event being handled, so a close knows whether the person left by clicking elsewhere (the keyboard is then
    /// theirs to place) or not (it goes back to the browser).
    @ObservationIgnored private var closingEvent: SaveWhyPanelState.Event?
    @ObservationIgnored private var retryAgain = false
    @ObservationIgnored private let api: any SavedWhyAPI
    @ObservationIgnored private weak var presenter: (any SaveWhyPresenting)?
    @ObservationIgnored private let now: () -> Date
    /// A monotonic clock for the input guard (`input`), apart from `now` so a test can hold one and move the other.
    @ObservationIgnored private let uptime: () -> TimeInterval
    @ObservationIgnored private var shownAt: TimeInterval?
    /// The options last fetched, so a question shows at once; refreshed after each one is asked.
    @ObservationIgnored private(set) var cachedOptions: SavedWhyOptions?
    /// Every link an early look saw as fresh, with that look's number, until a sync that read after it lands.
    @ObservationIgnored private(set) var seenFresh: [String: (channel: String, look: Int)] = [:]
    @ObservationIgnored private var lookCount = 0
    /// The last input the guard ignored — for tests and diagnostics, never shown.
    private(set) var lastIgnored: SaveWhyPanelState.Event?
    @ObservationIgnored private var timer: Task<Void, Never>?
    @ObservationIgnored private var posting: Task<Void, Never>?
    /// The debug harness's panel (`preview`): answered like any other, but nothing is posted or muted.
    @ObservationIgnored private(set) var previewing = false

    // G191 v3 — the unconfirmed panel.
    /// An answer given on an unconfirmed panel that closed before the backend agreed: sent once it does.
    /// `url` is the link the app's diff had named when it was given (nil when the panel was still pending).
    @ObservationIgnored private(set) var unconfirmedAnswer: (answer: SavedWhyAnswer, at: Date, channel: String,
                                                             url: String?)?
    /// The withdraw timer of the unconfirmed panel (or its held answer).
    @ObservationIgnored private var bound: Task<Void, Never>?
    /// G191 v5 — every bookmark the app's diff names, before any decision: the bubble watcher's only teacher
    /// (`BookmarkBubbleWatcher.bookmarkNamed`), so a shape is remembered only from a bookmark the file confirmed.
    @ObservationIgnored var onNamed: ((FreshBookmark) -> Void)?
    /// When each way in last opened or named the panel (uptime seconds) — for the stage timings, never shown.
    @ObservationIgnored private(set) var marks: [String: TimeInterval] = [:]

    // 2026-10-19 — the panel never closes under the person, and a saved page is edited, not asked again.
    /// Chrome's bookmark bubble the open panel came with, in window-list coordinates: a click inside it is the person
    /// working in Chrome's own bubble, not leaving (owner 2026-10-19).
    private(set) var bubbleFrame: CGRect?
    /// After a click inside the bubble: whether Chrome still shows it (one window-list read, bounds only, right after
    /// the person's own click — `BookmarkBubbleWatcher.lastBubbleStillOpen`). Nil: never asked.
    @ObservationIgnored var bubbleOpen: (@MainActor () -> Bool)?
    /// The page the star was clicked on, when it is a bookmark Cicada already holds (`SavedBookmarkLookup`): the
    /// panel opens filled in with its answer. Nil: never looked up (tests, or no way to tell without asking).
    @ObservationIgnored var existing: (@MainActor (String) async -> ExistingBookmark?)?
    /// A touched pending panel whose browser saved no new bookmark: it stays (only the person closes it), and says
    /// there is nothing to keep its answer with.
    private(set) var noBookmark = false
    /// The open panel is a bookmark Cicada already holds (the star on a saved page), adopted by `adopt`.
    @ObservationIgnored private(set) var onSaved = false

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
                await self?.syncLanded(result)
            }
        }
        BookmarkSyncSignal.early = { [weak self] bytes, look in await self?.lookEarly(bytes, look: look) }
        BookmarkSyncSignal.numberLook = { [weak self] in self?.takeLook() ?? 0 }
        BookmarkSyncSignal.offer = { [weak self] item in self?.candidate(item) }
        BookmarkSyncSignal.removed = { [weak self] channel in self?.bookmarkRemoved(on: channel) }
        Task { await refreshOptions() }
    }

    /// G191 live — the early look: decide on the bookmarks in `bytes` the bank does not hold yet, before the sync
    /// that saves them. Nil when it did not look (the switch off, or no answer — an older backend), so the sync's own
    /// result decides as before; else the look's number, which the sync hands back when it lands (`ingested`).
    ///
    /// **A save while an earlier sync still runs (measured 2026-10-14: the second of two bookmarks 12 s apart asked
    /// only after +12 s).** The watcher looks at once for such a save (`BrowserWatcher`'s `peek`) instead of waiting
    /// for the sync ahead. Its bytes then hold the earlier bookmark too, not saved yet — so every link a look saw as
    /// fresh is remembered (`seenFresh`) until a sync that read after it lands, and a later look subtracts what an
    /// earlier one already saw: "one fresh bookmark" means one new since the last look, not two.
    func lookEarly(_ bytes: BookmarkBytes, look given: Int? = nil) async -> Int? {
        guard prefs.enabled else { return nil }
        let look = given ?? takeLook()   // the caller's, taken before it read `bytes`
        if cachedOptions == nil { Task { await refreshOptions() } }
        guard let result = try? await api.freshBookmarks(bytes) else { return nil }
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
        seenFresh = seenFresh.filter { !landed($0.value) }
        await retryHeld()
    }

    func refreshOptions() async {
        if let fetched = try? await api.savedWhyOptions(), !fetched.reasons.isEmpty { cachedOptions = fetched }
    }

    var isShowing: Bool { state?.isOpen == true }

    /// The open panel, or an answer held from one, is waiting for the backend to agree about `channel`.
    private func unconfirmedOn(_ channel: String) -> Bool {
        (isShowing && !confirmed && state?.channel == channel) || unconfirmedAnswer?.channel == channel
    }

    // MARK: - G191 v3: the early ways in

    /// Chrome showed its bookmark bubble (`BookmarkBubbleWatcher`): open the question now, pending — before Chrome
    /// has written the file. The four fixed reasons stand in when the backend's options are not in hand yet.
    func bubbleSeen(channel: String, frame: CGRect? = nil) {
        guard prefs.enabled else { return }
        if isShowing {
            if state?.isWriting == true { return }   // never interrupt words
            if !confirmed, state?.channel == channel {
                // Already waiting on this browser (G191 v4, measured: "Edit bookmark", Remove, then "Bookmark added"
                // 2.2 s later): the newer bubble restarts the wait, so its own write still binds.
                if state?.isPending == true { armBound(SaveWhyPolicy.pendingBound) }
                return
            }
            send(.superseded)
        }
        // G191 v4: the four reasons are fixed, so the panel never waits on the backend for them.
        let cachedOptions = self.cachedOptions ?? .basic
        if self.cachedOptions == nil { Task { await refreshOptions() } }
        marks["bubble"] = uptime()
        open(SaveWhyPanelState(pendingIn: channel, order: cachedOptions.reasons.map(\.key),
                               maxText: cachedOptions.maxText), options: cachedOptions, confirmed: false)
        bubbleFrame = frame
        armBound(SaveWhyPolicy.pendingBound)
        if let existing {
            Task { @MainActor [weak self] in
                guard let found = await existing(channel) else { return }
                self?.adopt(found)
            }
        }
    }

    /// The star was clicked on a page already bookmarked (Chrome's "Edit bookmark" bubble): the pending panel becomes
    /// that bookmark's, filled in with its newest answer — never a second save. Owner 2026-10-19: "It should just put
    /// the same Cicada prompt, but with the text already filled in or the selection already made if I already did it."
    func adopt(_ found: ExistingBookmark) {
        guard isShowing, !confirmed, var panel = state, panel.isPending, panel.channel == found.item.channel else {
            return
        }
        bound?.cancel()
        bound = nil
        panel.bind(found.item)
        if let answer = found.answer, let at = found.at { panel.adopt(answer, at: at) }
        state = panel
        confirmed = true
        onSaved = true
        marks["existing"] = uptime()
        SaveWhyTimings.logger.info("save-why: the star on a saved bookmark (\(found.answer == nil ? "no answer yet" : "answer filled in", privacy: .public))")
    }

    /// The app's own diff named the one bookmark saved since its last read (live reads only): fill in the link, or
    /// open the question with it, before the early look answers. The policy's own rules still apply (recent, muted,
    /// the same save); the backend's decision confirms it.
    func candidate(_ item: FreshBookmark) {
        onNamed?(item)
        guard prefs.enabled else { return }
        var result = BookmarkSyncResult(new: 0, skipped: 0, sources: [])
        result.fresh = [item]
        result.freshTotal = 1
        guard case .ask = decide(result, live: true, ours: unconfirmedOn(item.channel)) else { return }
        marks["named"] = uptime()
        if isShowing, !confirmed, state?.channel == item.channel {
            state?.bind(item)
            armBound(SaveWhyPolicy.confirmBound)
            return
        }
        if unconfirmedAnswer?.channel == item.channel {
            if unconfirmedAnswer?.url == nil { unconfirmedAnswer?.url = item.url }   // the pending answer's link
            armBound(SaveWhyPolicy.confirmBound)   // the panel closed with an answer: wait for the backend with it
            return
        }
        if isShowing {
            if state?.isWriting == true || state?.item?.url == item.url { return }
            send(.superseded)
        }
        // G191 v4: never wait on the backend for the options (the instant look must not touch the network).
        let cachedOptions = self.cachedOptions ?? .basic
        if self.cachedOptions == nil { Task { await refreshOptions() } }
        open(SaveWhyPanelState(item: item, order: cachedOptions.reasons.map(\.key), maxText: cachedOptions.maxText),
             options: cachedOptions, confirmed: false)
        armBound(SaveWhyPolicy.confirmBound)
    }

    private func decide(_ result: BookmarkSyncResult, live: Bool, ours: Bool) -> SaveWhyPolicy.Decision {
        SaveWhyPolicy.decide(.init(
            enabled: prefs.enabled, live: live, result: result, now: now(), lastAsked: prefs.lastAsked,
            mutedHosts: prefs.mutedHosts, writing: !ours && state?.isWriting == true, lastURL: prefs.lastURL,
            lastAddedAt: prefs.lastAddedAt))
    }

    private func open(_ panel: SaveWhyPanelState, options: SavedWhyOptions, confirmed: Bool) {
        previewing = false
        self.options = options
        self.confirmed = confirmed
        bubbleFrame = nil
        noBookmark = false
        onSaved = false
        unconfirmedAnswer = nil
        state = panel
        shownAt = uptime()
        marks["shown"] = shownAt
        presenter?.show(self)
        logShown(channel: panel.channel)
        run(SaveWhyPanelState.opening())
    }

    /// G191 v4 — one log line per question: how long after the browser's file event it showed, and by which way in.
    private func logShown(channel: String) {
        let way = confirmed ? "backend" : (state?.isPending == true ? "bubble" : "diff")
        guard let event = BookmarkSyncSignal.eventAt[channel] else {
            SaveWhyTimings.logger.info("save-why: panel shown (\(way, privacy: .public)), no file event yet")
            return
        }
        let ms = SaveWhyTimings.ms(SaveWhyTimings.now() - event)
        SaveWhyTimings.logger.info("save-why: file event → panel \(ms) ms (\(way, privacy: .public))")
    }

    /// The unconfirmed panel (or the answer it left) withdraws after `seconds` unless the backend agrees first.
    private func armBound(_ seconds: TimeInterval) {
        bound?.cancel()
        bound = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(seconds))
            guard !Task.isCancelled else { return }
            self?.withdraw(reason: "no confirmation in time")
        }
    }

    /// No bookmark was confirmed (the bound passed, or the backend refused it). What the person gave is never dropped
    /// for it (owner 2026-10-19):
    ///
    /// - an untouched unconfirmed panel leaves, keeping nothing (it was some other bubble, or a bookmark not asked);
    /// - a touched one stays — only the person closes it; with no link named yet it says there is nothing to keep
    ///   its answer with (`noBookmark`);
    /// - an answer already given about a link the app's diff named stays held in the outbox until a sync of its
    ///   browser lands (never posted before one does); one given with no link named yet is dropped — there is no
    ///   bookmark to attach it to.
    ///
    /// `force` (Remove pressed in Chrome's bubble, or the backend named another link) closes even a touched panel and
    /// keeps nothing.
    func withdraw(force: Bool = false, reason: String = "refused") {
        bound?.cancel()
        bound = nil
        if isShowing, !confirmed, let panel = state {
            if panel.engaged && !force {
                if panel.isPending { noBookmark = true }
                SaveWhyTimings.logger.info("save-why: \(reason, privacy: .public); kept open, touched")
            } else {
                send(.withdraw)
                SaveWhyTimings.logger.info("save-why: withdrawn (\(reason, privacy: .public))")
            }
        }
        if let held = unconfirmedAnswer {
            if force, let url = held.url { outbox.discardAwaiting(url: url) }
            if held.url == nil || force {
                SaveWhyTimings.logger.info("save-why: an answer with no bookmark to keep it with was not kept")
            }
        }
        unconfirmedAnswer = nil
    }

    /// G191 v4 — Chrome wrote its file with a bookmark gone and none new: the pending panel's bubble was the "Edit
    /// bookmark" bubble and the person pressed Remove. The pending panel withdraws at once, keeping nothing; a re-add
    /// after it opens its own bubble and its own panel.
    func bookmarkRemoved(on channel: String) {
        guard isShowing, state?.channel == channel else { return }
        if onSaved {
            // The star on a saved page, then Remove (2026-10-19): the removal path applies — nothing is written here.
            send(.withdraw)
            SaveWhyTimings.logger.info("save-why: withdrawn (a saved bookmark removed)")
            return
        }
        guard !confirmed, state?.isPending == true else { return }
        withdraw(force: true, reason: "bookmark removed")
    }

    /// The backend agreed about `item` on the unconfirmed panel's browser: bind, and send an answer already given.
    ///
    /// Review 2026-10-15: only the link the app's diff named (or any, while the panel is still pending with none) — a
    /// backend that agrees about another link on the same browser never takes over the answer given about the first:
    /// the panel withdraws, or the held answer is dropped, and nothing is kept.
    private func confirm(_ item: FreshBookmark, early: Int?) {
        let named = isShowing && !confirmed && state?.channel == item.channel ? state?.item?.url
                                                                             : unconfirmedAnswer?.url
        if let named, named != item.url {
            withdraw(force: true, reason: "another link")
            return
        }
        bound?.cancel()
        bound = nil
        if isShowing, !confirmed, state?.channel == item.channel {
            state?.bind(item)
            confirmed = true
            marks["confirmed"] = uptime()
            return
        }
        confirmed = true
        if let held = unconfirmedAnswer, held.channel == item.channel {
            unconfirmedAnswer = nil
            if held.url == nil {
                outbox.hold(SaveWhyOutbox.Entry(url: item.url, answer: held.answer, at: held.at, addedAt: item.addedAt,
                                                channel: item.channel))
            }
        }
        outbox.release(url: item.url)
        posting = Task { @MainActor [weak self] in await self?.retryHeld() }
    }

    /// A bookmark sync landed (the watch's, a catch-up or Sync now): every answer awaiting that browser's sync may go
    /// now, and every held one is tried again — the link it is about may only just have been saved.
    func syncLanded(_ result: BookmarkSyncResult) async {
        for channel in Set(result.sources.compactMap(\.channel)) { outbox.release(channel: channel) }
        await retryHeld()
    }

    /// A click outside the panel, in window-list coordinates. Inside Chrome's own bookmark bubble it is the person
    /// working there, not leaving (owner 2026-10-19) — unless that click closed the bubble (Done), which leaves too.
    func click(at point: CGPoint) {
        guard isShowing else { return }
        guard let bubbleFrame, bubbleFrame.contains(point) else {
            input(.clickOutside)
            return
        }
        guard let bubbleOpen else { return }
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(SaveWhyPolicy.bubbleCloseCheck))
            guard let self, self.isShowing, self.bubbleFrame == bubbleFrame else { return }
            if !bubbleOpen() {
                self.bubbleFrame = nil
                self.input(.clickOutside)
            }
        }
    }

    // MARK: - The backend's decision

    /// A bookmark sync (or an early look) finished. Asks only when `SaveWhyPolicy` says so; otherwise does nothing —
    /// except that a refusal withdraws an unconfirmed panel on that browser.
    func noticed(_ result: BookmarkSyncResult, live: Bool, early: Int? = nil) async {
        let channels = Set(result.sources.compactMap(\.channel) + result.fresh.map(\.channel))
        let ours = channels.contains { unconfirmedOn($0) }
        let decision = decide(result, live: live, ours: ours)
        lastDecision = decision
        guard case .ask(let item) = decision else {
            if live, ours, case .skip(let reason) = decision, Self.withdraws(reason) {
                withdraw(reason: "refused: \(reason.rawValue)")
            }
            return
        }
        // Counted from the decision, so a second sync during the options read cannot ask twice.
        prefs.lastAsked = now()
        prefs.lastURL = item.url
        prefs.lastAddedAt = item.addedAt
        if unconfirmedOn(item.channel) {
            confirm(item, early: early)
            return
        }
        // The options already in hand show it at once (G191 live); G191 v4: the four fixed reasons stand in until the
        // backend's arrive, so no question waits on a fetch.
        let fetched = cachedOptions ?? .basic
        Task { await refreshOptions() }
        // G191 live: a newer bookmark replaces the open question — the person is looking at the new page now, and the
        // old one's moment has passed; a tap already made there is kept and posted (`superseded` closes like leaving).
        // A queue would ask about a page they have left. Never while they are writing (the policy).
        if isShowing {
            guard state?.isWriting != true else { return }
            send(.superseded)
        }
        open(SaveWhyPanelState(item: item, order: fetched.reasons.map(\.key), maxText: fetched.maxText),
             options: fetched, confirmed: true)
    }

    /// The refusals that mean the unconfirmed panel's bookmark will not be asked about.
    static func withdraws(_ reason: SaveWhyPolicy.Reason) -> Bool {
        switch reason {
        case .firstSync, .bulk, .notRecent, .muted, .noHost, .off: return true
        case .notLive, .noneNew, .repeated, .writing: return false
        }
    }

    /// The debug harness (`SaveWhyPreview`): show the panel now for a sample bookmark from `channel`'s browser, with
    /// the backend's options when it answers and the sample's when it does not. Skips every rule — that is the point —
    /// and writes nothing: an answer is not posted, a muted site is not remembered, the rate limit is not touched.
    func preview(channel: String) async {
        let fetched = (try? await api.savedWhyOptions()).flatMap { $0.reasons.isEmpty ? nil : $0 }
            ?? SaveWhyPreview.sampleOptions
        if isShowing { send(.escape) }
        let item = SaveWhyPreview.sample(channel: channel)
        open(SaveWhyPanelState(item: item, order: fetched.reasons.map(\.key), maxText: fetched.maxText),
             options: fetched, confirmed: true)
        previewing = true
    }

    /// G191 live — the person's own input from the panel: every button and click the view forwards comes through
    /// here. Measured 2026-10-14: a chip was found chosen with nothing done. The panel shows while the person's hand
    /// is still on the page beneath it — so a click that lands on the panel before `SaveWhyPolicy.armDelay` has
    /// passed was aimed at what was there before, and chooses nothing (nor closes it). Keys reach the panel only once
    /// a click inside made it key (`SaveWhyNSPanel`). Timers, Esc and the backend never choose.
    func input(_ event: SaveWhyPanelState.Event) {
        let guarded: Bool
        switch event {
        case .tapReason, .dontAskForSite, .clickOutside, .submit: guarded = true
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
        closingEvent = event
        run(effects)
    }

    private func run(_ effects: [SaveWhyPanelState.Effect]) {
        for effect in effects {
            switch effect {
            case .startTimer(let seconds):
                timer?.cancel()
                timer = Task { @MainActor [weak self] in
                    try? await Task.sleep(for: .seconds(seconds))
                    guard !Task.isCancelled, let self else { return }
                    self.send(.timeout)
                }
            case .stopTimer:
                timer?.cancel()
                timer = nil
            case .post(let answer):
                guard !previewing, let state else { continue }
                guard confirmed, let item = state.item else {
                    // G191 v3: not yet confirmed — never posted before the backend agrees. 2026-10-19: an answer about
                    // a link the diff named is held in the outbox at once, awaiting its sync, so neither a missing
                    // confirmation nor a quit loses it.
                    unconfirmedAnswer = (answer, now(), state.channel, state.item?.url)
                    if let item = state.item {
                        outbox.hold(SaveWhyOutbox.Entry(url: item.url, answer: answer, at: now(), addedAt: item.addedAt,
                                                        channel: item.channel, awaiting: true))
                    }
                    continue
                }
                let entry = SaveWhyOutbox.Entry(url: item.url, answer: answer, at: now(), addedAt: item.addedAt,
                                                channel: item.channel)
                posting = Task { @MainActor [weak self] in await self?.deliver(entry) }
            case .edit(let answer, let at):
                guard !previewing, let item = state?.item else { continue }
                let entry = SaveWhyOutbox.Entry(url: item.url, answer: answer, at: now(), addedAt: item.addedAt,
                                                channel: item.channel, editAt: at)
                posting = Task { @MainActor [weak self] in await self?.deliver(entry) }
            case .mute(let host):
                if !previewing { prefs.mute(host) }
            case .close:
                timer?.cancel()
                timer = nil
                if case .closed(let outcome)? = state?.phase { lastOutcome = outcome }
                presenter?.hide(returnFocus: closingEvent != .clickOutside)
            }
        }
    }

    /// Send one answer; a failure that may pass (Sleep writing, the backend away) holds it for `retryHeld`.
    private func deliver(_ entry: SaveWhyOutbox.Entry) async {
        do {
            try await send(entry)
        } catch {
            // 2026-10-19: a 404 is "not saved yet" (its sync has not run), held for the next sync — never dropped.
            if SaveWhyOutbox.verdict(for: error) != .drop { outbox.hold(entry) }
            else { SaveWhyTimings.logger.info("save-why: an answer was refused for good") }
        }
    }

    /// One held answer: an edit of the answer said at `editAt`, else a new answer for that moment of saving.
    private func send(_ entry: SaveWhyOutbox.Entry) async throws {
        if let at = entry.editAt {
            _ = try await api.editSavedWhy(url: entry.url, at: at, answer: entry.answer)
        } else {
            try await api.saveWhy(url: entry.url, answer: entry.answer, at: entry.at, addedAt: entry.addedAt)
        }
    }

    /// Send every held answer again — called when Sleep's writing flag goes false and on launch. One pass at a time;
    /// an answer that fails again with a passing error stays held, one refused for good or over a day old is dropped.
    func retryHeld() async {
        // A call during a pass (a sync landing while a retry runs) asks for one more pass, so an answer released after
        // the pass read the queue is never left waiting for the next signal.
        guard !retrying else { retryAgain = true; return }
        retrying = true
        defer { retrying = false }
        repeat {
            retryAgain = false
            if await retryPass() == .stopped { return }
        } while retryAgain
    }

    private enum PassEnd { case done, stopped }

    private func retryPass() async -> PassEnd {
        for entry in outbox.entries {
            if outbox.expired(entry, now: now()) {
                outbox.remove(entry)
                SaveWhyTimings.logger.info("save-why: a held answer passed a day and was dropped")
                continue
            }
            if entry.isAwaiting { continue }   // no sync of its browser has landed since: never posted before one
            do {
                try await send(entry)
                outbox.remove(entry)
            } catch {
                switch SaveWhyOutbox.verdict(for: error) {
                case .waitForSync: continue   // the link is not saved yet: kept for the next sync
                case .drop: outbox.remove(entry)
                case .hold: return .stopped   // still refused (Sleep again, or away): wait for the next signal
                }
            }
        }
        return .done
    }

    /// Tests: wait for the answer's request to finish.
    func settle() async { await posting?.value }
}
