import Foundation

/// R-DL13 (DR-45) — what a saved item is, for the kind tabs and the row's glyph. A paper says so (G133); a video is one
/// `VideoRef` resolves — a provider's player or a direct file (Track V); a bookmark came from a bookmarks file or a
/// browser; everything else is a link.
enum FeedKind: String, CaseIterable, Hashable {
    case link, video, paper, bookmark

    static func of(_ item: MediaFeedItem) -> FeedKind {
        if item.isPaper { return .paper }
        if item.mediaType == "youtube" || item.mediaType == "video" || VideoRef.resolve(item.url) != nil { return .video }
        if item.mediaType == "bookmark" || (item.origin ?? "").hasSuffix("bookmark") { return .bookmark }
        return .link
    }

    var label: String {
        switch self {
        case .link: "Links"
        case .video: "Videos"
        case .paper: "Papers"
        case .bookmark: "Bookmarks"
        }
    }

    var singular: String {
        switch self {
        case .link: "Link"
        case .video: "Video"
        case .paper: "Paper"
        case .bookmark: "Bookmark"
        }
    }

    /// DR-53 — outline symbols; only where no real mark exists (DR-48: a glyph or a mark, never both).
    var glyph: String {
        switch self {
        case .link: "link"
        case .video: "play.rectangle"
        case .paper: "doc.text"
        case .bookmark: "bookmark"
        }
    }

    static func tabs(_ items: [MediaFeedItem]) -> [TextTab<FeedKind>] {
        let counts = Dictionary(grouping: items, by: FeedKind.of).mapValues(\.count)
        return [TextTab(id: nil, label: Copy.Lists.all, count: items.count)]
            + allCases.compactMap { k in counts[k].map { TextTab(id: k, label: k.label, count: $0) } }
    }
}

/// DR-25 — "Feed · 160 saved" / "Feed · Videos · 2 saved" / "Feed · 3 of 160" / "Feed · 4 matches"; plain "Feed" when
/// nothing is indexed (R-DL18 — never "0 items").
enum FeedEyebrow {
    static func text(total: Int, kind: FeedKind?, visible: [MediaFeedItem], openId: String?, searching: Bool) -> String {
        if searching { return Eyebrow.text(Copy.feed, Copy.Lists.matches(visible.count)) }
        if let openId, let i = visible.firstIndex(where: { $0.id == openId }) {
            return Eyebrow.text(Copy.feed, kind?.label ?? "", Copy.Inbox.position(i + 1, of: visible.count))
        }
        if let kind { return Eyebrow.text(Copy.feed, kind.label, Copy.Lists.saved(visible.count)) }
        return Eyebrow.text(Copy.feed, total == 0 ? "" : Copy.Lists.saved(total))
    }
}

/// DR-58 — the day an item was saved: the true save date when the export kept one (G99d), else when Cicada took it
/// in; computed at read, never stored.
enum FeedDates {
    static func day(_ item: MediaFeedItem, locale: Locale = .autoupdatingCurrent,
                    timeZone: TimeZone = .autoupdatingCurrent, withYear: Bool = false) -> String? {
        let date = item.recencyDate
        guard date != .distantPast else { return nil }
        var style = withYear ? Date.FormatStyle().day().month(.abbreviated).year()
                             : Date.FormatStyle().day().month(.abbreviated)
        style.locale = locale
        style.timeZone = timeZone
        return date.formatted(style)
    }

    static func age(_ item: MediaFeedItem, now: Date) -> String? {
        let date = item.recencyDate
        guard date != .distantPast else { return nil }
        return InboxAge.compact(days: max(0, Int(now.timeIntervalSince(date) / 86_400)))
    }
}

/// DR-54 / DR-55 — where an item came from in a person's words: the app's name, the folder, the day; the origin id only
/// in `.help`; `[ no source recorded ]` when the page names none.
enum FeedSourceLine {
    static func markOrigin(_ item: MediaFeedItem) -> String? {
        guard let o = item.origin?.trimmingCharacters(in: .whitespaces), !o.isEmpty, o != "unknown" else { return nil }
        return o
    }

    static func text(_ item: MediaFeedItem, locale: Locale = .autoupdatingCurrent,
                     timeZone: TimeZone = .autoupdatingCurrent) -> String {
        var parts: [String] = []
        if let origin = markOrigin(item) { parts.append(OriginIconography.label(for: origin)) }
        if let folder = item.folder?.trimmingCharacters(in: .whitespaces), !folder.isEmpty { parts.append(folder) }
        guard !parts.isEmpty else { return InboxSourceLine.noSource }
        if let day = FeedDates.day(item, locale: locale, timeZone: timeZone) { parts.append(day) }
        return parts.joined(separator: " · ")
    }

    static func help(_ item: MediaFeedItem) -> String? { markOrigin(item).map(Copy.Lists.sourceHelp) }
}

/// R-DL15 — "Why it's saved", from what the page carries and nothing Cicada made up: the person's own words
/// (`personal_relevance`), then the pages it is about — only ids the graph holds, by their names (R-DL5).
enum FeedWhy {
    static func ownWords(_ item: MediaFeedItem) -> String? {
        guard let words = item.personalRelevance?.trimmingCharacters(in: .whitespacesAndNewlines), !words.isEmpty else {
            return nil
        }
        return words
    }

    static func about(_ item: MediaFeedItem, names: EntityNames) -> [(id: String, name: String)] {
        (item.about ?? []).compactMap { id in names.name(for: id).map { (id: id, name: $0) } }
    }
}

/// A row's second line: "Link · example.com · saved Sep 13" — a paper shows its byline where a link shows its site, and
/// a video its duration when the provider reported one ("Video · vimeo.com · 3:12 · saved Sep 13"; R17 — never an
/// estimate, so no duration means no duration). The retired `FeedRow` drew that duration as a pill.
enum FeedRowText {
    static func detail(_ item: MediaFeedItem, locale: Locale = .autoupdatingCurrent,
                       timeZone: TimeZone = .autoupdatingCurrent) -> String {
        var parts = [FeedKind.of(item).singular]
        if let byline = item.paper.flatMap(PaperCardText.feedLine) {
            parts.append(byline)
        } else if let site = item.site, !site.isEmpty {
            parts.append(site)
        }
        if let duration = VideoRef.durationLabel(item.durationS) { parts.append(duration) }
        if let day = FeedDates.day(item, locale: locale, timeZone: timeZone) { parts.append(Copy.Lists.savedRow(day)) }
        return parts.joined(separator: " · ")
    }
}

/// What the list column says before rows, in precedence order: error first (a failed fetch leaves nothing and would
/// read as "nothing saved"), loading second, and never blank over good data (§5.5).
enum FeedPageState: Equatable {
    case loading, failed(String), empty, noMatch, list

    static func of(isLoading: Bool, error: String?, hasItems: Bool, visibleEmpty: Bool, searching: Bool) -> FeedPageState {
        if !hasItems, let error { return .failed(error) }
        if !hasItems, isLoading { return .loading }
        if !hasItems { return .empty }
        if visibleEmpty && searching { return .noMatch }
        return .list
    }
}
