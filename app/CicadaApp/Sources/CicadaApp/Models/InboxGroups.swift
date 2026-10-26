import Foundation

/// The Inbox in groups (owner 2026-10-26: "the inbox looks super dense … I think grouping things would be best").
///
/// Under All the questions fall into one section per kind, each with its count, closed until asked for (UX 4, the way
/// "Settled by a check" is); under a kind's tab there is one section. Inside a section the questions about one page sit
/// together under that page's name, said once. Pure and display-only: nothing is answered, settled or reordered on
/// the server — a group only decides where a question is drawn. The order a group draws is the order ↑/↓ walk and the
/// order the next question opens after an answer (`InboxViewModel.visible`), so the keys never jump around the screen.
///
/// Order: a section sits where its most urgent question would (the G115 order — priority, then newest —
/// `InboxColumns.precedes`); a page's questions sit where their most urgent one would; inside, the G115 order.
enum InboxGroups {
    /// The questions about one page (or one question with no page): drawn under a header only when there are two or
    /// more, so a page asked about once reads as before.
    struct PageGroup: Identifiable {
        let id: String
        let entityId: String
        let name: String
        let items: [InboxItem]

        var hasHeader: Bool { items.count > 1 && !entityId.isEmpty }
    }

    /// One kind's questions (nil: the one section of a kind's tab).
    struct Section: Identifiable {
        let kind: InboxKind?
        let pages: [PageGroup]

        var id: String { kind?.rawValue ?? "all" }
        var items: [InboxItem] { pages.flatMap(\.items) }
        var count: Int { pages.reduce(0) { $0 + $1.items.count } }
    }

    /// `items` as sections: by kind when `byKind` (All), else one. `items` may be in any order.
    static func sections(_ items: [InboxItem], byKind: Bool) -> [Section] {
        let ordered = items.sorted(by: InboxColumns.precedes)
        guard byKind else { return [Section(kind: nil, pages: pages(ordered))] }
        var kinds: [InboxKind] = []
        var byKindItems: [InboxKind: [InboxItem]] = [:]
        for item in ordered {
            if byKindItems[item.kind] == nil { kinds.append(item.kind) }
            byKindItems[item.kind, default: []].append(item)
        }
        return kinds.map { Section(kind: $0, pages: pages(byKindItems[$0] ?? [])) }
    }

    /// The questions in the order the groups draw them — the list's walk.
    static func ordered(_ items: [InboxItem], byKind: Bool) -> [InboxItem] {
        sections(items, byKind: byKind).flatMap(\.items)
    }

    /// `ordered` (already in the G115 order) grouped by page, each page where its first question is.
    private static func pages(_ ordered: [InboxItem]) -> [PageGroup] {
        var keys: [String] = []
        var groups: [String: [InboxItem]] = [:]
        for item in ordered {
            // A question with no page is a group of its own.
            let key = item.entityId.isEmpty ? "item:\(item.id)" : "page:\(item.entityId)"
            if groups[key] == nil { keys.append(key) }
            groups[key, default: []].append(item)
        }
        return keys.map { key in
            let items = groups[key] ?? []
            let first = items[0]
            return PageGroup(id: key, entityId: first.entityId, name: first.displayName, items: items)
        }
    }

    /// Up to this many questions in all, the first group draws open; past it every group starts closed, so a full
    /// inbox reads as its kinds and their counts (UX 4: there when wanted, not pushed).
    static let openFirstUpTo = 12

    /// Which kinds draw open. The person's own choice for a kind wins; otherwise a lone section is open and, with
    /// several, the first is while the whole inbox is small (`openFirstUpTo`). The open question's kind is always
    /// open, so a question opened from ⌘K, Home or the keys is never inside a closed group.
    static func isOpen(_ kind: InboxKind?, sections: [Section], chosen: [InboxKind: Bool], openKind: InboxKind?) -> Bool {
        guard let kind else { return true }
        if kind == openKind { return true }
        if let choice = chosen[kind] { return choice }
        if sections.count == 1 { return true }
        return sections.first?.kind == kind && sections.reduce(0) { $0 + $1.count } <= openFirstUpTo
    }
}

/// One line of the grouped list at full width: a kind's header, a page's header, or a question (or its Undo row).
enum InboxListLine: Identifiable {
    case kind(InboxKind, count: Int, open: Bool, review: ReviewEntries.Entry?)
    case page(id: String, name: String, count: Int)
    case entry(InboxRowEntry, nested: Bool)

    var id: String {
        switch self {
        case .kind(let kind, _, _, _): "kind:\(kind.rawValue)"
        case .page(let id, _, _): "pagehead:\(id)"
        case .entry(let entry, _): entry.id
        }
    }

    /// The lines for `sections`, with the held answer's Undo row in its question's place (DR-42) — inside its group,
    /// which is open while it is held there (its question was just on screen).
    static func lines(_ sections: [InboxGroups.Section], byKind: Bool, held: ResolveGrace?, heldItem: InboxItem?,
                      reviews: [ReviewEntries.Entry], open: (InboxKind?) -> Bool) -> [InboxListLine] {
        var sections = sections
        // The last question of its group was just answered: its group stays, holding only the Undo row.
        if let h = heldItem, !sections.contains(where: { $0.kind == nil || $0.kind == h.kind }) {
            sections.append(InboxGroups.Section(kind: byKind ? h.kind : nil, pages: []))
        }
        var out: [InboxListLine] = []
        for section in sections {
            let heldHere = heldItem.map { h in section.kind == nil || section.kind == h.kind } ?? false
            let isOpen = open(section.kind) || heldHere
            if let kind = section.kind {
                let review = reviews.first { $0.kind.inboxKind == kind }
                out.append(.kind(kind, count: section.count, open: isOpen, review: review))
            }
            guard isOpen else { continue }
            var pages = section.pages
            if heldHere, let heldItem, let held {
                pages = insert(heldItem, into: pages)
                out += pageLines(pages, in: section.id, heldId: held.id) { item in
                    item.id == held.id ? .undo(held, item) : .item(item)
                }
            } else {
                out += pageLines(pages, in: section.id, heldId: nil) { .item($0) }
            }
        }
        return out
    }

    private static func pageLines(_ pages: [InboxGroups.PageGroup], in section: String, heldId: String?,
                                  entry: (InboxItem) -> InboxRowEntry) -> [InboxListLine] {
        var out: [InboxListLine] = []
        for page in pages {
            // The Undo row is not a question still waiting, so a page's header counts the others.
            let waiting = page.items.filter { $0.id != heldId }.count
            let header = page.hasHeader && waiting > 1
            // One page can head a group in two kinds at once (two conflicts and two decay questions): the line's id
            // carries its section, so no two lines in the list share an id (review of #475).
            if header { out.append(.page(id: "\(section):\(page.id)", name: page.name, count: waiting)) }
            out += page.items.map { .entry(entry($0), nested: header) }
        }
        return out
    }

    /// The held question back in its page group, at its G115 place (a new group when its page has none left).
    private static func insert(_ item: InboxItem, into pages: [InboxGroups.PageGroup]) -> [InboxGroups.PageGroup] {
        let regrouped = InboxGroups.sections(pages.flatMap(\.items) + [item], byKind: false)
        return regrouped.first?.pages ?? pages
    }
}
