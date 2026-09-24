import Foundation

/// Round 4 (R-SR13) — Safari's source page, grouped the way Safari keeps things: the Reading List newest saved first,
/// then Favorites (the `BookmarksBar`, its folders included), then everything else — each item once, none hidden by
/// a cap (DR-38).
enum SafariSections {
    static let readingListRoot = "com.apple.ReadingList"
    static let favoritesRoot = "BookmarksBar"
    static let menuRoot = "BookmarksMenu"

    struct Group: Equatable {
        let title: String
        let items: [MediaFeedItem]
        static func == (a: Group, b: Group) -> Bool { a.title == b.title && a.items.map(\.id) == b.items.map(\.id) }
    }

    static func root(_ folder: String?) -> String {
        (folder ?? "").split(separator: "/", maxSplits: 1).first.map(String.init) ?? ""
    }

    static func groups(_ items: [MediaFeedItem]) -> [Group] {
        // "Recently saved" is Safari's own `DateAdded` (the backend's `content_saved_at`), so `recencyDate` orders it.
        let reading = items.filter { root($0.folder) == readingListRoot }.sorted { $0.recencyDate > $1.recencyDate }
        let favorites = items.filter { root($0.folder) == favoritesRoot }
        let rest = items.filter { ![readingListRoot, favoritesRoot].contains(root($0.folder)) }
        return [Group(title: Copy.safariRecentlySaved, items: reading),
                Group(title: Copy.safariFavorites, items: favorites),
                Group(title: Copy.safariOtherBookmarks, items: rest)].filter { !$0.items.isEmpty }
    }

    /// Safari's internal folder keys as Safari names them (the backend's `SAFARI_FOLDER_LABELS`); any other folder —
    /// every Chrome one — is returned as it is.
    static func displayFolder(_ folder: String) -> String {
        let names = [readingListRoot: "Reading List", favoritesRoot: "Favorites", menuRoot: "Bookmarks Menu"]
        let parts = folder.split(separator: "/", maxSplits: 1).map(String.init)
        guard let first = parts.first, let name = names[first] else { return folder }
        return parts.count > 1 ? "\(name)/\(parts[1])" : name
    }
}
