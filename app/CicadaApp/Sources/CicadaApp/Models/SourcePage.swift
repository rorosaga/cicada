import Foundation

/// source-page-v3 (owner 2026-10-29) — the one search a source page offers, pure. The backend narrows the list
/// (`GET /sources/channels/{id}/items?q=`): titles, a chat's name, a saved link's host, and the words behind each row
/// where the words index has them. The field's words are trimmed and cut at the backend's cap (`Q_MAX`).
enum SourceSearch {
    static let maxLength = 200
    /// How long typing settles before the list asks (the palette's server debounce).
    static let debounce: Duration = .milliseconds(180)
    /// A query value keeps only unreserved characters bare (RFC 3986), so `&`, `=`, `+`, `#` and `?` stay words.
    nonisolated static let queryAllowed: CharacterSet = {
        var set = CharacterSet.alphanumerics
        set.insert(charactersIn: "-._~")
        return set
    }()

    nonisolated static func normalized(_ query: String) -> String {
        String(query.trimmingCharacters(in: .whitespacesAndNewlines).prefix(maxLength))
    }
}

/// source-page-v3 — a source's one status, said once at the top of its page (owner 2026-10-29: "a better status for
/// when it's connected"): Connected · last item <day> / Syncing <what> / Needs you: <one action> / Off. Pure: derived
/// from the catalogue row's status, the channel's run state and the day the newest item came in.
enum SourcePageStatus: Equatable {
    /// On; `lastItem` is the day the newest item came in (`latest`), nil when nothing came in yet or unknown.
    case connected(lastItem: String?)
    /// A read is running; `detail` is the reader's own words when it has them ("12 of 40").
    case syncing(detail: String?)
    /// One thing the person must do, in words ("sign in again").
    case needsYou(String)
    /// Not reading now; `lastItem` is the newest thing it brought in before, when it holds any.
    case off(lastItem: String?)

    static func of(row: SourceCatalogStatus, run: SourceRowStatus, latest: String?) -> SourcePageStatus {
        if case .syncing(let detail, _, _) = run { return .syncing(detail: detail) }
        switch row {
        case .needsSignIn: return .needsYou(Copy.SourcePage.signInAgain)
        case .waitingForAgent: return .needsYou(Copy.SourcePage.connectAnAgent)
        case .off: return .off(lastItem: latest)
        case .connected:
            if case .problem(let why) = run {
                return .needsYou(why == Copy.sourceNeedsAccess ? Copy.SourcePage.allowAccess : why)
            }
            return .connected(lastItem: latest)
        }
    }

    var tone: StatusWord.Tone {
        switch self {
        case .connected, .syncing: .on
        case .needsYou: .attention
        case .off: .off
        }
    }

    var word: String {
        switch self {
        case .connected: Copy.SourcePage.connected
        case .syncing: Copy.SourcePage.syncing
        case .needsYou: Copy.SourcePage.needsYou
        case .off: Copy.SourcePage.off
        }
    }

    /// What follows the word on the same line — never a sentence about the source (DR-38): the last item's day, the
    /// run's own progress, or the one action. Off says only what it still holds (the settings below hold the switch).
    func detail(today: ISODay, locale: Locale = .autoupdatingCurrent) -> String? {
        switch self {
        case .connected(let latest):
            guard let day = ISODay(latest) else { return Copy.SourcePage.nothingYet }
            return Copy.SourcePage.lastItem(Self.dayWord(day, today: today, locale: locale))
        case .syncing(let detail): return detail
        case .needsYou(let action): return action
        case .off(let latest):
            return ISODay(latest).map { Copy.SourcePage.lastItem(Self.dayWord($0, today: today, locale: locale)) }
        }
    }

    /// "today", "yesterday", a weekday, "Oct 3" — `RelativeDay`'s phrase, lower-cased where it is a common word mid-line.
    static func dayWord(_ day: ISODay, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        let phrase = RelativeDay.phrase(day, today: today, locale: locale)
        return (-1...0).contains(day - today) ? phrase.lowercased(with: locale) : phrase
    }

    /// The line spoken and shown: "Connected · last item today".
    func line(today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        [word, detail(today: today, locale: locale)].compactMap { $0 }.joined(separator: " · ")
    }
}

/// source-page-v3 — where a source page's column is: the page itself, or one of its lists opened in its place (DR-81:
/// "All N" opens the full list as the column's content; a group opens its items the same way). Esc returns.
enum SourceDrill: Equatable {
    /// Every row the source holds (the capped list's "All N").
    case all(channel: String)
    /// One chat's conversations.
    case chat(ChannelItem)
    /// One watched day's videos.
    case day(ChannelItem)
    /// An agent's every conversation (its capped list's "All N").
    case conversations

    var title: String? {
        switch self {
        case .all, .conversations: nil
        case .chat(let item): item.title
        case .day: nil
        }
    }
}

/// source-page-v3 — the list's pure rules: how many rows the page shows before "All N" (DR-81 — the list is the
/// page's main content, so it shows a screenful rather than DR-81's five; ruling of 2026-10-29 in DESIGN_RULES §9), and
/// which rows open a group in the column rather than a single item.
enum SourceItemsRules {
    static let cap = 12

    static func isGroup(_ item: ChannelItem) -> Bool { item.kind == .chat || item.videos != nil }

    /// A group row's right-hand words: how many it holds ("4 videos", "12 messages", else "3 conversations"). A chat
    /// counts its messages when the backend kept them (#559) — what the apps themselves count — else its sittings.
    static func groupCount(_ item: ChannelItem) -> String? {
        if let videos = item.videos { return Copy.watchedVideos(videos) }
        if let messages = item.messages, messages > 0 { return Copy.SourcePage.messages(messages) }
        if let sittings = item.sittings, sittings > 0 { return Copy.SourcePage.conversations(sittings) }
        return nil
    }
}
