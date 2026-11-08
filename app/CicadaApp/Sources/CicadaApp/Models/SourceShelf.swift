import Foundation

/// ROR-118 (owner, Sources round 1: "group by kind of information, never by vendor; each kind shows its items in its
/// own way") — the six shelves the Sources page and its add overlay sort every source into. What a source *is* to the
/// person, not who makes it: Apple Notes and Notion sit together as documents, Calendar and a calendar feed as events.
/// Pure and total: every catalogue entry names its shelf here, so a new source without one reads as saved until it is
/// placed (`SourceShelfTests` fails on an unplaced id).
enum SourceShelf: String, CaseIterable, Identifiable {
    case conversations, documents, events, work, saved, media

    var id: String { rawValue }

    var title: String {
        switch self {
        case .conversations: Copy.Shelf.conversations
        case .documents: Copy.Shelf.documents
        case .events: Copy.Shelf.events
        case .work: Copy.Shelf.work
        case .saved: Copy.Shelf.saved
        case .media: Copy.Shelf.media
        }
    }

    /// The glyph on an empty shelf's add line and on the overlay's tab; a symbol, never a vendor's mark (DR-52).
    var symbol: String {
        switch self {
        case .conversations: "bubble.left.and.bubble.right"
        case .documents: "doc.text"
        case .events: "calendar"
        case .work: "hammer"
        case .saved: "bookmark"
        case .media: "play.rectangle"
        }
    }

    static func of(_ entry: SourceCatalogEntry) -> SourceShelf {
        switch entry.id {
        case VoiceMemosReader.channel, AppleBooksReader.channel, "goodreads", "book-scan",
             GoogleBooksKeyModel.id: return .media
        case "contacts-local": return .documents
        case SourceCatalog.tracesId, "github", "linear": return .work
        case "files", "rss", SourceCatalog.substackId: return .saved
        default: break
        }
        switch entry.category {
        case .agents, .messaging, .meetings: return .conversations
        case .calendars: return .events
        case .notes, .files: return .documents
        case .browsers, .social, .reading: return .saved
        case .media: return .media
        }
    }
}

extension SourceCatalogEntry {
    var shelf: SourceShelf { SourceShelf.of(self) }
}

/// What a shelf draws, pure: the connected sources of one shelf, and what could still be added.
enum SourceShelves {
    struct Shelf: Equatable {
        let shelf: SourceShelf
        /// Connected and not waiting on the person, in the page's order.
        let connected: [SourceCatalogRow]
        /// What could still be added here, suggested first (an app already on this Mac), then the catalogue's order.
        let addable: [SourceCatalogRow]
    }

    static func shelves(_ rows: [SourceCatalogRow]) -> [Shelf] {
        let ordered = SourceCategory.allCases.flatMap { category in rows.filter { $0.entry.category == category } }
        return SourceShelf.allCases.map { shelf in
            let mine = ordered.filter { $0.entry.shelf == shelf }
            // A list turned on that has not read yet is still to be added, in its own words ("Not read yet").
            let addable = mine.filter { !$0.needsYou && !$0.notInstalled
                && ($0.status == .off || $0.browser?.state == .notReadYet) }
            return Shelf(shelf: shelf, connected: mine.filter(\.isConnectedHere),
                         addable: addable.filter(\.suggested) + addable.filter { !$0.suggested })
        }
    }

    /// The connected sources the person has, in shelf order: the overlay's *Yours* strip.
    static func yours(_ rows: [SourceCatalogRow]) -> [SourceCatalogRow] {
        shelves(rows).flatMap(\.connected)
    }

    /// What the overlay lists below *Yours*: every source not connected (a waiting one stays on the page, under *Needs
    /// you*), narrowed to one shelf and to the words typed, grouped by shelf.
    static func addGroups(_ rows: [SourceCatalogRow], shelf: SourceShelf?, query: String) -> [Shelf] {
        let words = SourceGrid.isSearching(query) ? Set(SourceGrid.results(rows, query: query).map(\.id)) : nil
        return shelves(rows).compactMap { group in
            guard shelf == nil || group.shelf == shelf else { return nil }
            let addable = group.addable.filter { words?.contains($0.id) ?? true }
            return addable.isEmpty ? nil : Shelf(shelf: group.shelf, connected: [], addable: addable)
        }
    }
}
