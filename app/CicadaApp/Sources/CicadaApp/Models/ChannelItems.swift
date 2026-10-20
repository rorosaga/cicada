import Foundation

/// G161 — one thing a source brought in, by name: `GET /sources/channels/{id}/items`' row. Titles only — never a
/// body; for Contacts the matched page's name and nothing from the card. `day` is an absolute `YYYY-MM-DD` (DR-58: the
/// relative word is made when read).
struct ChannelItem: Codable, Hashable, Identifiable, Sendable {
    enum Kind: String, Sendable { case episode, media, page, chat, unknown }

    let kind: Kind
    let id: String
    let title: String
    let day: String?
    /// G191 v4 — a bookmark channel's link that left the browser: when a sync first saw it gone (aware ISO). Nil for
    /// every other row and from an older backend.
    var left: String? = nil
    /// Sources v3 — a saved link's bare host ("example.com"), for the row's line; never the URL. Nil for other rows.
    var host: String? = nil
    /// Sources v3 — the key the site's mark is asked under (`SiteIcon`; a walled family's name, else the domain).
    var site: String? = nil
    /// Sources v3 — the newest answer to "What made you save this?" (G191), when the person gave one.
    var why: ChannelItemWhy? = nil
    /// Sources v4 — a Messages sitting's chat: who it is with and its photo's hash (the row's face). Nil elsewhere.
    var chat: ChannelItemChat? = nil
    /// Sources v4 — a watched day's video count (the row opens to that day's videos). Nil for every other row.
    var videos: Int? = nil
    /// Sources v4 (review of #358) — a Messages chat's sitting count (the row opens to its sittings).
    var sittings: Int? = nil

    enum CodingKeys: String, CodingKey { case kind, id, title, day, left, host, site, why, chat, videos, sittings }

    init(kind: Kind, id: String, title: String, day: String? = nil, left: String? = nil, host: String? = nil,
         site: String? = nil, why: ChannelItemWhy? = nil, chat: ChannelItemChat? = nil, videos: Int? = nil) {
        self.kind = kind; self.id = id; self.title = title; self.day = day; self.left = left
        self.host = host; self.site = site; self.why = why; self.chat = chat; self.videos = videos
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        kind = Kind(rawValue: (try c.decodeIfPresent(String.self, forKey: .kind)) ?? "") ?? .unknown
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        day = try c.decodeIfPresent(String.self, forKey: .day)
        left = try? c.decodeIfPresent(String.self, forKey: .left)
        // Lenient: an older backend sends none of these, and a malformed one drops the field, never the row.
        host = try? c.decodeIfPresent(String.self, forKey: .host)
        site = try? c.decodeIfPresent(String.self, forKey: .site)
        why = try? c.decodeIfPresent(ChannelItemWhy.self, forKey: .why)
        chat = try? c.decodeIfPresent(ChannelItemChat.self, forKey: .chat)
        videos = try? c.decodeIfPresent(Int.self, forKey: .videos)
        sittings = try? c.decodeIfPresent(Int.self, forKey: .sittings)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(kind.rawValue, forKey: .kind)
        try c.encode(id, forKey: .id)
        try c.encode(title, forKey: .title)
        try c.encodeIfPresent(day, forKey: .day)
        try c.encodeIfPresent(left, forKey: .left)
        try c.encodeIfPresent(host, forKey: .host)
        try c.encodeIfPresent(site, forKey: .site)
        try c.encodeIfPresent(why, forKey: .why)
        try c.encodeIfPresent(chat, forKey: .chat)
        try c.encodeIfPresent(videos, forKey: .videos)
        try c.encodeIfPresent(sittings, forKey: .sittings)
    }
}

/// Sources v4 — the chat a Messages row came from: the app's conversation hash, who it is with, and the stored
/// photo's hash when the chat shares one (`GET /sources/messages/chats/{id}/photo?v=`).
struct ChannelItemChat: Codable, Hashable, Sendable {
    let id: String
    let label: String
    var photo: String? = nil
}

/// Sources v3 — why the person saved a link, as a row shows it: the reasons they tapped ("The design") and their own
/// words, one line (`channel_items._why`; the whole answer lives on the item's page).
struct ChannelItemWhy: Codable, Hashable, Sendable {
    var labels: [String] = []
    var text: String? = nil

    init(labels: [String] = [], text: String? = nil) { self.labels = labels; self.text = text }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        labels = (try? c.decodeIfPresent([String].self, forKey: .labels)) ?? []
        text = try? c.decodeIfPresent(String.self, forKey: .text)
    }

    enum CodingKeys: String, CodingKey { case labels, text }
}

/// One page of a channel's items, newest first. `total` is the list's own count — the server never promises it
/// equals the row's number (a notes index keeps deleted notes; a calendar keeps events that left the window).
struct ChannelItemsPage: Codable, Hashable, Sendable {
    let channel: String
    let total: Int
    let offset: Int
    let items: [ChannelItem]

    enum CodingKeys: String, CodingKey { case channel, total, offset, items }

    init(channel: String, total: Int, offset: Int = 0, items: [ChannelItem]) {
        self.channel = channel; self.total = total; self.offset = offset; self.items = items
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        channel = try c.decodeIfPresent(String.self, forKey: .channel) ?? ""
        items = try c.decodeIfPresent([ChannelItem].self, forKey: .items) ?? []
        total = try c.decodeIfPresent(Int.self, forKey: .total) ?? items.count
        offset = try c.decodeIfPresent(Int.self, forKey: .offset) ?? 0
    }
}

/// What the list shows for one channel: every row loaded so far and the list's total.
struct ChannelItemsList: Equatable, Sendable {
    var items: [ChannelItem]
    var total: Int

    var hasMore: Bool { items.count < total }
}

/// Where a row opens (G161). Pure, so the mapping is tested without a view: a captured document opens in the Reader,
/// a saved item in the Feed's detail column, a person's page as its card. Nothing opens where the list is only a
/// preview (onboarding's Import page: the Reader would open hidden under the onboarding layer).
enum CapturedItemRoute: Equatable {
    case reader(episode: String, title: String)
    case feed(mediaEntityId: String)
    case entity(String)

    static func of(_ item: ChannelItem, interactive: Bool) -> CapturedItemRoute? {
        guard interactive, !item.id.isEmpty else { return nil }
        switch item.kind {
        case .episode: return .reader(episode: item.id, title: item.title)
        case .media: return .feed(mediaEntityId: item.id)
        case .page: return .entity(item.id)
        case .chat, .unknown: return nil   // a chat opens in place to its sittings (`ChatSittingsRow`)
        }
    }
}

/// The list's pure rules (DR-39, DR-58).
enum CapturedItems {
    /// Rows a page brings: the first twenty, then twenty more per "Show more".
    static let pageSize = 20

    /// DR-39 — collapsed by default, remembered per viewer per channel.
    static func openKey(_ channel: String) -> String { "cicada.sources.capturedOpen.\(channel)" }

    /// The row's compact age ("9d", "4w"), or the date for a day still ahead (a calendar event); the full date is its
    /// `.help`. Nil with no day — the row then shows no age rather than a guess.
    static func age(_ item: ChannelItem, today: ISODay, locale: Locale = .autoupdatingCurrent)
        -> (text: String, help: String)? {
        guard let day = ISODay(item.day) else { return nil }
        let text = day > today ? RelativeDay.absolute(day, today: today, locale: locale)
                               : RelativeDay.compactAge(day, today: today)
        return (text, RelativeDay.full(day, locale: locale))
    }

    /// How many rows the next refresh asks for, so a revalidation covers every row already shown (the server caps a
    /// page at 200).
    /// G191 v4 — "No longer in Chrome since Oct 15" for a bookmark row that left its browser, nil otherwise.
    static func leftLine(_ item: ChannelItem, channel: String) -> String? {
        guard let since = item.left else { return nil }
        let browser = BrowserInventory.spec(forBookmarksChannel: channel)?.name ?? "the browser"
        return Copy.Bookmarks.noLongerIn([BookmarkLeft(browser: browser, channel: channel, since: since)])
    }

    static func refreshLimit(shown: Int) -> Int {
        let pages = max(1, (shown + pageSize - 1) / pageSize)
        return min(pages * pageSize, maxLimit)
    }

    static let maxLimit = 200

    /// What the list's rows are, in the row's own unit where that is what they are ("note", "bookmark") and in the
    /// list's where the row counts something else: Contacts counts cards but lists people, a feed or calendar
    /// subscription counts subscriptions but lists what they brought.
    static func noun(channel: String, countNoun: String?) -> (one: String, many: String) {
        switch channel {
        case "contacts-local": return ("person", "people")
        case "calendar": return ("event", "events")
        case "rss": return ("item", "items")
        default:
            guard let countNoun, !countNoun.isEmpty else { return ("item", "items") }
            return (countNoun, countNoun + "s")   // every registry noun is regular (`SourceChannel.countNoun`)
        }
    }
}

/// Sources v3 (owner 2026-10-19: "in two clicks … I can see all the things that I've saved in Chrome. Instead of
/// putting the Chrome logo maybe put the website's logo") — a saved row's words and mark, pure.
enum SavedItemText {
    /// The second line: the person's own words first (the reason the row exists, and the part a narrow column must not
    /// cut), then the reasons they tapped, then the site. Nil when the row has none of them.
    static func line(_ item: ChannelItem) -> String? {
        var parts: [String] = []
        if let words = words(item) { parts.append("“\(words)”") }
        parts += item.why?.labels ?? []
        if let host = item.host, !host.isEmpty { parts.append(host) }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// The why as it is spoken (VoiceOver): the words, then the reasons.
    static func whySpoken(_ item: ChannelItem) -> String? {
        let parts = (words(item).map { [$0] } ?? []) + (item.why?.labels ?? [])
        return parts.isEmpty ? nil : parts.joined(separator: ", ")
    }

    static func words(_ item: ChannelItem) -> String? {
        let text = (item.why?.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? nil : text
    }

    /// Which mark the row draws — the shared rule (`SavedLinkMarkModel`, owner 2026-10-20): the site's own key when
    /// the row has one, asked by the media page's id; else a monogram of the host or the title. Never the browser's
    /// mark: the row is the site, not where it was saved from.
    static func mark(_ item: ChannelItem) -> SavedLinkMarkModel.Mark {
        SavedLinkMarkModel.mark(site: item.site, host: item.host, title: item.title,
                                door: item.kind == .media ? .media(item.id) : nil)
    }

    /// The row's day — "Today", "Yesterday", a weekday this week, else "Oct 3" — with the full date as its `.help`
    /// (DR-58: computed when read). Nil with no day.
    static func day(_ item: ChannelItem, today: ISODay, locale: Locale = .autoupdatingCurrent)
        -> (text: String, help: String)? {
        guard let day = ISODay(item.day) else { return nil }
        return (RelativeDay.phrase(day, today: today, locale: locale), RelativeDay.full(day, locale: locale))
    }
}
