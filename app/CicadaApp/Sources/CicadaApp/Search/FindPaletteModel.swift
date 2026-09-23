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
    /// One line under the rows — why ⏎ did not open Settings (R-SU12). The next keystroke clears it.
    private(set) var hint: String?
    /// True while the overlay is up: page fields stop claiming ⌘F (R-SU9).
    private(set) var isPresented = false
    let ask: AskViewModel

    @ObservationIgnored private(set) var index = QuickIndex.empty
    @ObservationIgnored private(set) var recents: [FindRowKey] = []
    @ObservationIgnored private var loadedBank: String?
    @ObservationIgnored private let store: Store

    init(store: Store) {
        self.store = store
        self.ask = AskViewModel(store: store)
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
        hint = nil
        expanded = []
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        results = trimmed.isEmpty ? index.emptyState(recents: recents)
                                  : FindMerge.fresh(query: text, local: index.query(trimmed))
        selection = FindSelection.initial(sections)
    }

    /// Find ↔ Ask keeps the text (design §3.1).
    func setMode(_ newMode: FindMode) {
        guard newMode != mode else { return }
        if newMode == .ask {
            ask.question = query
            mode = .ask
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
    /// asking, an asked-before answer, the Settings hint — happens here and
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
        case .settings:
            hint = "Click Open to see this in Settings."
            return nil
        default:
            remember(row.key)
            return destination
        }
    }

    func toggleExpanded(_ group: FindGroupID) {
        if expanded.contains(group) { expanded.remove(group) } else { expanded.insert(group) }
    }

    private func remember(_ key: FindRowKey) {
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
        let n = results.rowCount, g = results.groupCount
        guard n > 0 else { return "Nothing matches “\(trimmed)”." }
        return "\(UsageFormat.count(n)) \(n == 1 ? "result" : "results") in \(g) \(g == 1 ? "group" : "groups")"
    }

    var selectionAnnouncement: String? {
        let rows = FindSelection.flat(sections)
        guard let selection, let position = rows.firstIndex(where: { $0.key == selection }),
              let row = results.row(for: selection) else { return nil }
        return FindRowText.announcement(row, position: position + 1, of: rows.count)
    }
}
