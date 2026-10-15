import Foundation

/// G191 v3 — the bookmark history in the menu bar (owner 2026-10-15, after Maccy's clipboard history: "one of the
/// options in the Cicada taskbar is bookmarks, and it shows the history of the websites bookmarked with the icon or a
/// screenshot of the site, and the reasons we saved it. If we click, the app opens quickly to the page of that site").
///
/// Pure: the rows come from the Store's `sources` snapshot (`GET /sources`, already warm, hydrated from disk and kept
/// current over SSE — no second fetch, no new domain), so the list opens at once and works offline with what the app
/// last saw. A bookmark is a saved item a browser's bookmark file brought in (`origin` `<browser>-bookmark`).
///
/// **Pictures follow the picture rails** — the app loads no picture a page names from the web. A row shows, in order:
/// the site capture's thumbnail when Cicada holds one (ruling 25, served from the bank by
/// `/explore/captures/…/thumb`), else the page's stored preview (`/entities/{id}/preview`, fetched once by the backend
/// under its gates and served from Cicada's store), else a monogram of the site. Both paths are Cicada's own API,
/// loaded with the bearer through `PictureStore` (`StoredPreview`). No logo: a logo comes only from a trusted
/// `website` source on an entity page, which a bookmark's media page does not carry.
struct BookmarkHistoryRow: Identifiable, Equatable {
    enum Picture: Equatable {
        case capture(String)
        case preview(String)
        case monogram(String)
    }

    let id: String
    let mediaEntityId: String
    let url: String
    let title: String
    let host: String
    /// The browser it came from, by name ("Chrome", "Safari"), when known.
    let browser: String?
    /// The newest moment it was saved, as far as Cicada knows.
    let when: Date?
    /// The newest answer's reasons as their labels, then "For <project>".
    let reasons: [String]
    /// The newest answer's own words.
    let words: String?
    /// How many answers it holds (a bookmark saved again keeps one per save).
    let answers: Int
    let picture: Picture

    /// What the search reads, folded once.
    let haystack: String
}

enum BookmarkHistory {
    /// The list's length: the newest first, the rest one search away.
    static let shown = 300

    static func isBookmark(_ item: MediaFeedItem) -> Bool {
        (item.origin ?? "").hasSuffix("-bookmark") || item.mediaType == "bookmark"
    }

    /// Every bookmark, newest saved first (ties by title, so the order is stable).
    static func rows(_ items: [MediaFeedItem], projectNames: [String: String] = [:]) -> [BookmarkHistoryRow] {
        items.filter(isBookmark).map { row($0, projectNames: projectNames) }.sorted { a, b in
            switch (a.when, b.when) {
            case let (x?, y?) where x != y: return x > y
            case (_?, nil): return true
            case (nil, _?): return false
            default: return a.title.localizedCaseInsensitiveCompare(b.title) == .orderedAscending
            }
        }
    }

    static func row(_ item: MediaFeedItem, projectNames: [String: String] = [:]) -> BookmarkHistoryRow {
        let host = Self.host(item.url) ?? item.site ?? ""
        let title = item.title.trimmingCharacters(in: .whitespacesAndNewlines)
        let newest = item.savedWhyAnswers.last
        var reasons = newest?.labels ?? []
        if let project = newest?.project { reasons.append("For \(projectNames[project] ?? project)") }
        let words = newest?.text?.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty
        let browserId = (item.origin ?? "").replacingOccurrences(of: "-bookmark", with: "")
        let browser = BrowserInventory.spec(id: browserId)?.name
        let shownTitle = title.isEmpty ? (host.isEmpty ? item.url : host) : title
        let haystack = fold(([shownTitle, host, item.url, words ?? ""] + reasons).joined(separator: " "))
        return BookmarkHistoryRow(
            id: item.id, mediaEntityId: item.mediaEntityId, url: item.url, title: shownTitle, host: host,
            browser: browser, when: when(item), reasons: reasons, words: words, answers: item.savedWhyAnswers.count,
            picture: picture(item, host: host), haystack: haystack)
    }

    /// The newest moment it was saved: the browser's own instant (the record's `lastSavedAt`), else the save date.
    static func when(_ item: MediaFeedItem) -> Date? {
        if let last = item.lastSavedAt, let date = ISO8601DateFormatter().date(from: last) { return date }
        let recency = item.recencyDate
        return recency == .distantPast ? nil : recency
    }

    /// The row's picture (see the type's note): capture, then stored preview, then a monogram — never a web URL.
    static func picture(_ item: MediaFeedItem, host: String) -> BookmarkHistoryRow.Picture {
        if let capture = item.captureThumb, StoredPreviewPath.loads(capture) { return .capture(capture) }
        if let preview = item.preview, StoredPreviewPath.loads(preview) { return .preview(preview) }
        return .monogram(monogram(host.isEmpty ? item.title : host))
    }

    static func monogram(_ text: String) -> String {
        text.first(where: { $0.isLetter || $0.isNumber }).map { String($0).uppercased() } ?? "•"
    }

    static func host(_ url: String) -> String? {
        guard let host = URL(string: url)?.host?.lowercased(), !host.isEmpty else { return nil }
        return host.hasPrefix("www.") ? String(host.dropFirst(4)) : host
    }

    /// Every word of the query must appear (in any order) in the title, the site, the link, the reasons or the
    /// words — case and accents folded. An empty query is the whole list.
    static func search(_ rows: [BookmarkHistoryRow], query: String) -> [BookmarkHistoryRow] {
        let terms = fold(query).split(whereSeparator: \.isWhitespace).map(String.init)
        guard !terms.isEmpty else { return rows }
        return rows.filter { row in terms.allSatisfy { row.haystack.contains($0) } }
    }

    static func fold(_ text: String) -> String {
        text.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: nil)
    }

    /// The row a ⌘1…⌘9 opens: the n-th of what is shown (1-based), when there is one.
    static func shortcut(_ n: Int, in rows: [BookmarkHistoryRow]) -> BookmarkHistoryRow? {
        (1...9).contains(n) && n <= rows.count ? rows[n - 1] : nil
    }

    /// Short relative time for a row ("now", "5 min", "3 h", "Tue", "12 Oct").
    static func age(_ date: Date?, now: Date = Date(), calendar: Calendar = .current) -> String {
        guard let date else { return "" }
        let seconds = now.timeIntervalSince(date)
        if seconds < 60 { return "now" }
        if seconds < 3600 { return "\(Int(seconds / 60)) min" }
        if seconds < 86_400 { return "\(Int(seconds / 3600)) h" }
        if seconds < 6 * 86_400 {
            return date.formatted(.dateTime.weekday(.abbreviated))
        }
        return date.formatted(.dateTime.day().month(.abbreviated))
    }
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
