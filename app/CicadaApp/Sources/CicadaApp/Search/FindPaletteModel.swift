import Foundation
import Observation

/// The ⌘K palette's state (G136; round-3 design §3; decision 18: a find
/// palette with Ask as a mode). The views render it; everything a key does is
/// a method here, so the keyboard map is tested without a window.
///
/// One `AskViewModel` lives here for the life of the app (R-SU7): the Ask
/// mode hosts today's answer body, and its per-bank history doubles as the
/// "Asked before" group.
@Observable
@MainActor
final class FindPaletteModel {
    private(set) var query = ""
    private(set) var mode: FindMode = .find
    private(set) var results = FindResults.empty
    private(set) var selection: FindRowKey?
    private(set) var expanded: Set<FindGroupID> = []
    /// True while the overlay is up: page fields stop claiming ⌘F (R-SU9).
    private(set) var isPresented = false
    let ask: AskViewModel

    @ObservationIgnored private(set) var index = QuickIndex.empty
    @ObservationIgnored private(set) var recents: [FindRowKey] = []
    @ObservationIgnored private var loadedBank: String?
    @ObservationIgnored private let store: Store
    /// False for Home's field (R-IB4): recents are the palette's empty state,
    /// Home's empty state is its cards, and two writers of `.quickRecents`
    /// would clobber each other's list.
    @ObservationIgnored private let keepsRecents: Bool

    /// The server tier (G136 S4): where the last pass stands, for the
    /// hairline and the footer's second clause (design §3.6).
    private(set) var serverPhase: FindServerPhase = .idle
    /// The server's `indexState` for the last pass (G136 R11).
    private(set) var indexState: String?
    @ObservationIgnored private let api: any FindSearchAPI
    @ObservationIgnored private let sleeper: FindSleeper
    /// The current text's passes, and a "Show all" re-ask — tests await them.
    @ObservationIgnored private(set) var serverTask: Task<Void, Never>?
    @ObservationIgnored private(set) var expandTask: Task<Void, Never>?

    /// `api` and `sleeper` are injected so every test runs the passes against
    /// a fake with a clock that never waits — no test may reach
    /// `APIClient.shared`, which on a dev machine is the owner's live backend.
    ///
    /// Track I part b (R-IB4) — Home hosts a second instance so a ⌘K on another
    /// page (`present` resets the query) never wipes what was left typed on
    /// Home. It passes the palette's `ask`, so the app keeps one Ask history and
    /// one `.askHistory` writer (R-SU7); `nil` builds the app's one Ask.
    init(store: Store, ask: AskViewModel? = nil, keepsRecents: Bool = true,
         api: any FindSearchAPI = APIClient.shared, sleeper: @escaping FindSleeper = FindSleepers.real) {
        self.store = store
        self.api = api
        self.sleeper = sleeper
        self.ask = ask ?? AskViewModel(store: store)
        self.keepsRecents = keepsRecents
    }

    var sections: [FindSection] { results.sections(expanded: expanded) }

    /// The field shows the search in Find and the question in Ask.
    var fieldText: String { mode == .ask ? ask.question : query }

    // MARK: Typing

    func setFieldText(_ text: String) {
        if mode == .ask { ask.question = text } else { setQuery(text) }
    }

    func setQuery(_ text: String) {
        query = text
        expanded = []
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        results = trimmed.isEmpty ? index.emptyState(recents: recents)
                                  : FindMerge.fresh(query: text, local: index.query(trimmed))
        selection = FindSelection.initial(sections)
        scheduleServer(trimmed)
    }

    /// Find ↔ Ask keeps the text (design §3.1).
    func setMode(_ newMode: FindMode) {
        guard newMode != mode else { return }
        if newMode == .ask {
            ask.question = query
            mode = .ask
            // Ask shows no rows: a search still out would only be dropped by
            // `isCurrent` after it had already asked the backend.
            serverTask?.cancel()
            expandTask?.cancel()
            serverPhase = .idle
        } else {
            mode = .find
            setQuery(ask.question)
        }
    }

    // MARK: The index

    /// R-SU5 — a new index never reorders rows on screen; it applies on the
    /// next keystroke, or at once when nothing is typed or nothing is shown.
    func install(_ newIndex: QuickIndex) {
        index = newIndex
        if query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || results.rowCount == 0 {
            setQuery(query)
        }
    }

    /// Builds the instant tier off the main actor from the Store's snapshots;
    /// a bank switch reloads that bank's recents and Ask history first.
    func rebuildIndex() async {
        if loadedBank != store.bank {
            loadedBank = store.bank
            await ask.loadHistory()
            recents = await store.cache.load(.quickRecents, bank: store.bank, as: [FindRowKey].self)?.value ?? []
        }
        let inputs = QuickIndexInputs.from(store, askHistory: ask.history)
        let built = await Task.detached(priority: .userInitiated) { QuickIndex.build(inputs) }.value
        // `.task(id:)` cancels this pass when an input moves again, but a
        // detached build runs to its end regardless: an older, slower build
        // (a bank switch mid-build) must never land over the newer one.
        guard !Task.isCancelled else { return }
        install(built)
    }

    // MARK: Presenting

    func present(prefill: String = "", mode newMode: FindMode = .find) {
        isPresented = true
        mode = .find
        setQuery(prefill)
        if newMode == .ask { setMode(.ask) }
    }

    func dismissed() {
        isPresented = false
        mode = .find
        setQuery("")
    }

    // MARK: Keys

    func move(_ step: FindStep) { selection = FindSelection.move(selection, step, in: sections) }
    func select(_ key: FindRowKey) { selection = key }

    /// Esc (design §3.4): Ask → Find with the text kept, then clear, then close. `true` = close.
    func escape() -> Bool {
        if mode == .ask { setMode(.find); return false }
        if !query.isEmpty { setQuery(""); return false }
        return true
    }

    /// ⌘⏎ — ask the current text (design §3.1). Spends: never call from a test.
    func askNow() {
        let text = fieldText.trimmingCharacters(in: .whitespacesAndNewlines)
        setMode(.ask)
        guard !text.isEmpty else { return }
        ask.question = text
        Task { await ask.ask() }
    }

    /// ⏎ — in Ask it asks; in Find it opens the selected row.
    func submit() -> FindDestination? {
        if mode == .ask { askNow(); return nil }
        guard let selection else { return nil }
        return activate(selection)
    }

    /// A row's primary (or ⌥ secondary) action. What the palette owns —
    /// asking, an asked-before answer — happens here and
    /// returns nil; what navigates comes back for the host to run, and is
    /// remembered as a recent (R-SU6).
    func activate(_ key: FindRowKey, secondary: Bool = false) -> FindDestination? {
        guard let row = results.row(for: key) else { return nil }
        selection = key
        guard let destination = secondary ? row.secondary : row.destination else { return nil }
        switch destination {
        case .ask(let text):
            setMode(.ask)
            ask.question = text
            Task { await ask.ask() }
            return nil
        case .askedBefore(let question):
            setMode(.ask)
            ask.question = question
            if let entry = ask.history.first(where: { $0.question == question }) { ask.select(entry) }
            return nil
        default:
            remember(row.key)
            return destination
        }
    }

    /// "Show all" / "More…". A server-fed group re-asks that one kind at the
    /// server's cap (R-SU14); the answer appends like any other pass.
    func toggleExpanded(_ group: FindGroupID) {
        if expanded.contains(group) { expanded.remove(group); return }
        expanded.insert(group)
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let kind = FindServerRows.kind(for: group), SearchTiming.wantsServer(q) else { return }
        expandTask?.cancel()
        expandTask = Task { [weak self] in
            await self?.runPass(q, mode: "prefix", kinds: [kind], perKind: SearchTiming.expandedPerKind)
        }
    }

    // MARK: The server tier (design §3.2 "Tier 2")

    /// Debounced and cancellable: each keystroke cancels the passes in flight;
    /// under two characters nothing is asked (R-SU2); Pass A (prefix, FTS
    /// only) after the debounce, Pass B (hybrid) once the typing has settled.
    private func scheduleServer(_ q: String) {
        serverTask?.cancel()
        expandTask?.cancel()
        indexState = nil
        guard SearchTiming.wantsServer(q) else {
            serverTask = nil
            serverPhase = .idle
            return
        }
        serverPhase = .searching
        let sleeper = self.sleeper
        serverTask = Task { [weak self] in
            do { try await sleeper(SearchTiming.serverDebounce) } catch { return }
            await self?.runPass(q, mode: "prefix")
            do { try await sleeper(SearchTiming.semanticIdle - SearchTiming.serverDebounce) } catch { return }
            await self?.runPass(q, mode: "hybrid")
        }
    }

    /// One pass, merged by the rule that never moves a shown row (design
    /// §3.2). A stale answer — cancelled, or for text that has changed — is dropped.
    func runPass(_ q: String, mode passMode: String, kinds: [String] = FindServerRows.kinds,
                 perKind: Int = SearchTiming.perKind) async {
        do {
            let response = try await api.searchMemory(q, kinds: kinds, mode: passMode, perKind: perKind)
            guard !Task.isCancelled, isCurrent(q) else { return }
            let feed = store.sources.value ?? []
            var context = FindServerRows.Context()
            context.mediaURL = { id in feed.first { $0.mediaEntityId == id }?.url }
            let rows = FindServerRows.rows(response, query: q, context: context)
            let totals = FindServerRows.totals(response, rows: rows, kinds: kinds, perKind: perKind)
            results = FindMerge.append(rows, totals: totals, to: results)
            if selection.flatMap({ results.row(for: $0) }) == nil { selection = FindSelection.initial(sections) }
            indexState = response.indexState
            serverPhase = .done
        } catch {
            guard !Task.isCancelled, isCurrent(q) else { return }
            serverPhase = FindServerPhase.isUnreachable(error) ? .unreachable : .done
        }
    }

    private func isCurrent(_ q: String) -> Bool {
        mode == .find && query.trimmingCharacters(in: .whitespacesAndNewlines) == q
    }

    /// "Search deeper" (design §3.6): the hybrid pass, now.
    func searchDeeper() {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard SearchTiming.wantsServer(q) else { return }
        serverTask?.cancel()
        serverPhase = .searching
        serverTask = Task { [weak self] in await self?.runPass(q, mode: "hybrid") }
    }

    /// Offered once a pass has answered and fewer than three rows stand.
    var offersSearchDeeper: Bool {
        mode == .find && serverPhase == .done && results.rowCount < 3
            && SearchTiming.wantsServer(query.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    /// Design §3.6's states, as the footer's second clause (the live region).
    var serverNote: String? {
        switch serverPhase {
        case .searching: return "Searching conversations…"
        case .unreachable: return "Conversations and beliefs need the Cicada backend. It isn't answering."
        case .done where indexState == "building" || indexState == "unavailable":
            return "Cicada is still reading your conversations — try again in a moment."
        default: return nil
        }
    }

    private func remember(_ key: FindRowKey) {
        guard keepsRecents else { return }
        let next = FindRecents.push(key, into: recents)
        guard next != recents else { return }
        recents = next
        let bank = store.bank
        let cache = store.cache
        Task { await cache.save(next, etag: nil, domain: .quickRecents, bank: bank) }
    }

    // MARK: What the footer and VoiceOver say

    var footerText: String {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard mode == .find, !trimmed.isEmpty else { return "" }
        return [FindRowText.footer(query: trimmed, results: results), serverNote]
            .compactMap { $0 }.joined(separator: " · ")
    }

    var selectionAnnouncement: String? {
        let rows = FindSelection.flat(sections)
        guard let selection, let position = rows.firstIndex(where: { $0.key == selection }),
              let row = results.row(for: selection) else { return nil }
        return FindRowText.announcement(row, position: position + 1, of: rows.count)
    }
}
