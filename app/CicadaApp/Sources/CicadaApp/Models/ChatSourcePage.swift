import Foundation

// 2026-11-03 — the owner's Sources feedback, the pure half (tested without a view): which page actions a source shows,
// and a chat source's list and panel.

/// The two actions that left the Sources page's top right (owner: "i dont get why these buttons are here if they dont
/// influence whatsapp or some of the other sources at all"): each is drawn only in the settings of the sources it acts
/// on. *Reading in your browser* holds the switches for what the person's agent reads in their browser — the accounts
/// read that way (an entry with a `site`) and YouTube's lists. *Explore saved sites* walks the sites the person saved
/// in a browser — a browser's own page. Import stays on the list itself (DR-75's one labelled add).
enum SourcePageAction: Hashable, Sendable {
    case readingInBrowser, exploreSavedSites
}

enum SourcePageActions {
    static func of(_ entry: SourceCatalogEntry, exploreGone: Bool) -> Set<SourcePageAction> {
        var out: Set<SourcePageAction> = []
        if entry.site != nil || entry.id == "youtube" { out.insert(.readingInBrowser) }
        if entry.id.hasPrefix(SourceCatalog.browserPrefix), !exploreGone { out.insert(.exploreSavedSites) }
        return out
    }
}

/// A settings write's answer, whatever its shape: a pin needs only the status (the list re-reads itself).
struct ChatPinAnswer: Decodable, Sendable {}

/// A chat source's page (owner 2026-11-03: "this infinite scrollable list is shit UX" — the synced chats under a
/// search bar, "in the same order as the apps themselves", right-click → pin, "a green dot for chats that are synced,
/// and a last synced text", and a chat's raw conversation in a panel from the right).
enum ChatSourcePage {
    /// Every chat source's channel → the settings route its pin is written through (`/sources/<source>/settings`).
    static let settingsSource: [String: String] = [
        MessagesWatcher.channel: "messages", WhatsAppWatcher.channel: "whatsapp", TelegramChats.channel: "telegram",
    ]

    static func isChatSource(_ channel: String) -> Bool { settingsSource[channel] != nil }

    /// How many sittings the panel reads at a time: the newest first, "Earlier messages" for the next ones.
    static let sittingsPage = 3

    /// The sittings the panel shows after `pages` reads, oldest first (a chat reads top to bottom, the newest at the
    /// end), from the route's newest-first list.
    static func shownSittings(_ newestFirst: [ChatSitting], pages: Int) -> [ChatSitting] {
        Array(newestFirst.prefix(max(1, pages) * sittingsPage).reversed())
    }

    static func hasEarlier(_ newestFirst: [ChatSitting], pages: Int) -> Bool {
        newestFirst.count > max(1, pages) * sittingsPage
    }

    /// What a row's right side says, as the apps do: the time today, "Yesterday", the weekday within the week, the day
    /// this year, the day and year before. The full date and time in `help` (DR-58: computed when read). Nil when the
    /// chat says no time, or a time ahead (`ChatDates.plausible`).
    static func recency(_ item: ChannelItem, now: Date, locale: Locale = .autoupdatingCurrent,
                        timeZone: TimeZone = .autoupdatingCurrent) -> (text: String, help: String)? {
        guard let at = ChatDates.plausible(instant(item.lastAt) ?? day(item.day, timeZone: timeZone), now: now)
        else { return nil }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        calendar.locale = locale
        func style(_ s: Date.FormatStyle) -> Date.FormatStyle {
            var s = s
            s.locale = locale
            s.timeZone = timeZone
            s.calendar = calendar
            return s
        }
        let help = at.formatted(style(.dateTime.weekday(.wide).day().month(.wide).year().hour().minute()))
        let days = calendar.dateComponents([.day], from: calendar.startOfDay(for: at),
                                           to: calendar.startOfDay(for: now)).day ?? 0
        let text: String
        if days <= 0 {
            text = item.lastAt == nil ? Copy.ChatPage.today : at.formatted(style(.dateTime.hour().minute()))
        } else if days == 1 {
            text = Copy.ChatPage.yesterday
        } else if days < 7 {
            text = at.formatted(style(.dateTime.weekday(.wide)))
        } else if calendar.component(.year, from: at) == calendar.component(.year, from: now) {
            text = at.formatted(style(.dateTime.day().month(.abbreviated)))
        } else {
            text = at.formatted(style(.dateTime.day().month(.abbreviated).year()))
        }
        return (text, help)
    }

    /// The row's second line: a ticked chat is synced (the green dot) and says when Cicada last stored its words or,
    /// for a reader on this Mac, last checked it (`check`), whichever is later; any other chat Cicada holds is not
    /// syncing (a grey dot) — it was unticked, and its stored words stay in memory.
    static func syncLine(_ item: ChannelItem, check: Date?, now: Date,
                         locale: Locale = .autoupdatingCurrent) -> (text: String, synced: Bool) {
        guard item.ticked == true else { return (Copy.ChatPage.notSyncing, false) }
        let at = [instant(item.syncedAt), check].compactMap { $0 }.max()
        guard let at else { return (Copy.ChatPage.synced, true) }
        return (Copy.ChatPage.lastSynced(SourceCatalog.ago(min(at, now), now: now, locale: locale)), true)
    }

    static func instant(_ raw: String?) -> Date? {
        guard let raw, !raw.isEmpty else { return nil }
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: raw) { return d }
        f.formatOptions = [.withInternetDateTime]
        return f.date(from: raw)
    }

    private static func day(_ raw: String?, timeZone: TimeZone) -> Date? {
        guard let raw, raw.count == 10 else { return nil }
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = timeZone
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: raw)
    }
}
