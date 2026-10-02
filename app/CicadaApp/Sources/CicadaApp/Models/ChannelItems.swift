import Foundation

/// G161 — one thing a source brought in, by name: `GET /sources/channels/{id}/items`' row. Titles only — never a
/// body; for Contacts the matched page's name and nothing from the card. `day` is an absolute `YYYY-MM-DD` (DR-58: the
/// relative word is made when read).
struct ChannelItem: Codable, Hashable, Identifiable, Sendable {
    enum Kind: String, Sendable { case episode, media, page, unknown }

    let kind: Kind
    let id: String
    let title: String
    let day: String?

    enum CodingKeys: String, CodingKey { case kind, id, title, day }

    init(kind: Kind, id: String, title: String, day: String? = nil) {
        self.kind = kind; self.id = id; self.title = title; self.day = day
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        kind = Kind(rawValue: (try c.decodeIfPresent(String.self, forKey: .kind)) ?? "") ?? .unknown
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        day = try c.decodeIfPresent(String.self, forKey: .day)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(kind.rawValue, forKey: .kind)
        try c.encode(id, forKey: .id)
        try c.encode(title, forKey: .title)
        try c.encodeIfPresent(day, forKey: .day)
    }
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
        case .unknown: return nil
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
