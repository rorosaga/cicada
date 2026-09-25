import Foundation

/// §5.3 — which question is open, pure (DR-27…DR-30; R-DI8…R-DI10, R-DI19). The Reader's own state
/// is `ProvenanceRouter`'s; this only answers what the page does with it. Held by `InboxViewModel`,
/// so a page switch keeps the open question and the tab; a bank switch resets both (ids repeat
/// across banks).
struct InboxColumns: Equatable {
    private(set) var openId: String?
    var kindFilter: InboxKind?
    /// Where the open question sat, so one that vanishes hands the column to its neighbour.
    private(set) var openIndex: Int?

    enum ReaderEffect: Equatable {
        case keep, close
        /// R-DI9 — the same conversation: re-land in place on the new question's span.
        case refocus(ReaderTarget)
    }

    enum Escape: Equatable { case closeReader, closeQuestion, none }

    /// G115 — the inbox's one order: priority, then newest.
    static func precedes(_ a: InboxItem, _ b: InboxItem) -> Bool {
        a.priority != b.priority ? a.priority > b.priority : a.createdDateValue > b.createdDateValue
    }

    static func visible(_ items: [InboxItem], filter: InboxKind?) -> [InboxItem] {
        items.filter { filter == nil || $0.kind == filter }.sorted(by: precedes)
    }

    /// DR-29 — the Reader stays on a swap only when the new question cites its conversation.
    static func readerEffect(for item: InboxItem?, readerEpisode: String?) -> ReaderEffect {
        guard let readerEpisode else { return .keep }
        guard let item, let target = item.cause?.readerTarget(subjectId: item.entityId.isEmpty ? nil : item.entityId),
              target.episode == readerEpisode else { return .close }
        return .refocus(target)
    }

    mutating func select(_ item: InboxItem, in visible: [InboxItem], readerEpisode: String?) -> ReaderEffect {
        openId = item.id
        openIndex = visible.firstIndex { $0.id == item.id }
        return Self.readerEffect(for: item, readerEpisode: readerEpisode)
    }

    mutating func close() {
        openId = nil
        openIndex = nil
    }

    /// DR-68 — ↑/↓ on the list: the neighbour, clamped; from nothing, the first (↓) or the last (↑).
    func neighbour(_ delta: Int, in visible: [InboxItem]) -> InboxItem? {
        guard !visible.isEmpty else { return nil }
        guard let id = openId, let i = visible.firstIndex(where: { $0.id == id }) else {
            return delta >= 0 ? visible.first : visible.last
        }
        return visible[min(max(i + delta, 0), visible.count - 1)]
    }

    /// DR-29 — the next row opens at once: the one now in the answered row's place, else the one
    /// before; the last answer returns the page to STATE 0. An answer made elsewhere moves nothing.
    mutating func afterAnswer(_ id: String, remaining: [InboxItem]) {
        guard openId == id else { return }
        guard !remaining.isEmpty else { return close() }
        let i = min(openIndex ?? 0, remaining.count - 1)
        openId = remaining[i].id
        openIndex = i
    }

    /// DR-42 — Undo reopens its question, clearing a tab that would hide it.
    mutating func undo(_ item: InboxItem) {
        if let k = kindFilter, k != item.kind { kindFilter = nil }
        openId = item.id
        openIndex = nil
    }

    /// A snapshot moved: a vanished question hands over to its neighbour (or STATE 0), and a tab
    /// whose kind emptied returns to All.
    mutating func reconcile(visible: [InboxItem], kinds: Set<InboxKind>) {
        if let k = kindFilter, !kinds.contains(k) { kindFilter = nil }
        guard let id = openId else { return }
        if let i = visible.firstIndex(where: { $0.id == id }) {
            openIndex = i
            return
        }
        guard !visible.isEmpty else { return close() }
        let i = min(openIndex ?? 0, visible.count - 1)
        openId = visible[i].id
        openIndex = i
    }

    /// DR-45 — a tab keeps the open question when it shows it, else opens its first; STATE 0 stays 0.
    mutating func filter(_ kind: InboxKind?, visibleAfter: [InboxItem]) {
        kindFilter = kind
        guard let id = openId, !visibleAfter.contains(where: { $0.id == id }) else { return }
        openId = visibleAfter.first?.id
        openIndex = visibleAfter.isEmpty ? nil : 0
    }

    /// G136 / DR-30 — a palette or Home hand-off: every kind shown, that question open.
    mutating func land(_ id: String) {
        kindFilter = nil
        openId = id
        openIndex = nil
    }

    /// DR-28 — Esc closes the rightmost open thing. The card has already closed its own field.
    func escape(readerOpen: Bool) -> Escape {
        readerOpen ? .closeReader : (openId == nil ? .none : .closeQuestion)
    }
}

/// One line of the list: a question, or the Undo row that took its place (DR-42). The Undo row keeps
/// the question's id, so the swap is a content change in place — instant, never a transition (DR-61).
enum InboxRowEntry: Identifiable {
    case item(InboxItem)
    case undo(ResolveGrace, InboxItem)

    var id: String {
        switch self {
        case .item(let item): item.id
        case .undo(let held, _): held.id
        }
    }
}

enum InboxRows {
    static func entries(visible: [InboxItem], held: ResolveGrace?, snapshot: [InboxItem],
                        filter: InboxKind?) -> [InboxRowEntry] {
        var rows = visible.map(InboxRowEntry.item)
        guard let held, let item = snapshot.first(where: { $0.id == held.id }),
              filter == nil || filter == item.kind else { return rows }
        let at = visible.firstIndex { !InboxColumns.precedes($0, item) } ?? visible.count
        rows.insert(.undo(held, item), at: at)
        return rows
    }
}

/// R-DI26 / DR-31 — which fixed slots a STATE 0 row can afford. Glyph, gaps, age, chevron and
/// padding take ~132 units and the question needs ~120 to say anything, so the entity (180) goes
/// under 680 units of list and the source (220) under 480. A fixed frame in an `HStack` never
/// shrinks: without this, a list beside a Reader at 1.4× draws its rows under the Reader.
struct InboxRowSlots: Equatable {
    var entity: Bool
    var source: Bool

    static let entityFloor: CGFloat = 680
    static let sourceFloor: CGFloat = 480

    static func of(listUnits: CGFloat) -> InboxRowSlots {
        InboxRowSlots(entity: listUnits >= entityFloor, source: listUnits >= sourceFloor)
    }
}

/// DR-25 — "Inbox · 6 pending", or "Inbox · 1 of 6 · Conflict" while a question is open.
enum InboxEyebrow {
    static func text(visible: [InboxItem], openId: String?) -> String {
        if let id = openId, let i = visible.firstIndex(where: { $0.id == id }) {
            return Eyebrow.text(Copy.Inbox.title, Copy.Inbox.position(i + 1, of: visible.count), visible[i].kind.label)
        }
        return Eyebrow.text(Copy.Inbox.title, visible.isEmpty ? "" : Copy.Inbox.pending(visible.count))
    }
}

/// DR-45 — "All 6 · Decay 1 · Conflict 2 …": the kinds present, in a stable order, never a dot.
enum InboxTabs {
    static let order: [InboxKind] = [.decay, .conflict, .clarification, .followup, .mergeSuggestion,
                                     .removal, .divergence, .normalization]

    static func tabs(_ items: [InboxItem]) -> [TextTab<InboxKind>] {
        let counts = Dictionary(grouping: items, by: \.kind).mapValues(\.count)
        return [TextTab(id: nil, label: Copy.Inbox.all, count: items.count)]
            + order.compactMap { k in counts[k].map { TextTab(id: k, label: k.label, count: $0) } }
    }
}

/// R-DL4 (DR-60, DR-68) — where the Inbox's keys land when the page appears and after an answer: the list, so ↑/↓
/// reach every question and ⏎ steps into the open one. After an answer it is the LIST on purpose: Undo holds exactly
/// one answer (R-DI2 — the next answer sends the held one), so a repeated digit must not sweep the queue past its own
/// Undo. When DR-27 has hidden the list the question takes the keys, so a key is never dropped.
enum InboxFocusPolicy {
    static func afterArrivalOrAnswer(listHidden: Bool, questionOpen: Bool) -> InboxPage.Focus? {
        if !listHidden { return .list }
        return questionOpen ? .question : nil
    }
}
