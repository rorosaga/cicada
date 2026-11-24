import Foundation

// G245 (ruling 78, plan 3.2) — what a source's page says about its streams, pure: the head's one quiet line, each Reads
// row's name, quiet line, count · last read or state word and control, and which streams the items section tabs.
// Nothing here draws; `SourcePageStreamsTests` holds the sentences the person reads.

/// The head's one quiet line (plan 3.2 item 1): the account and how the source is read. The browser-reading facts (whose
/// sign-in, who else sees what is read, never posts, how to stop) are its hover and the first-use sheet's, never a
/// standing paragraph (DESIGN_RULES §9 2026-11-04 (1)).
enum SourceHeadLine {
    /// "@handle · Read in your browser by Claude Code, about once a day". `app` is the person's own AI app on this Mac,
    /// named only when one is connected here (it is their own current choice).
    static func text(account: StreamAccount?, streams: [ResolvedStream], app: String?) -> String? {
        var parts: [String] = []
        if let handle = account?.handle?.trimmingCharacters(in: .whitespacesAndNewlines), !handle.isEmpty {
            parts.append(handle.hasPrefix("@") ? handle : "@" + handle)
        }
        let ways = ways(streams)
        if !ways.isEmpty { parts.append(ways.map { phrase($0, app: app) }.joined(separator: ", ")) }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// The hover: the browser-reading facts when a stream is read in the browser, else the account's own honest line.
    static func help(entryId: String, streams: [ResolvedStream], app: String?) -> String? {
        var lines: [String] = []
        if ways(streams).contains(.browser) {
            lines += [Copy.Streams.whoseSession, Copy.Streams.whoSees(app: app), Copy.Streams.neverPosts,
                      Copy.Streams.howToStop]
        }
        if let honest = honestLine(entryId) { lines.append(honest) }
        return lines.isEmpty ? nil : lines.joined(separator: " ")
    }

    /// Read-only, through the person's own sign-in: one line on the sources that connect an account (no standing text).
    static func honestLine(_ entryId: String) -> String? {
        switch entryId {
        case "notion": Copy.Honest.notion
        case "linear": Copy.Honest.linear
        case "github": Copy.Honest.github
        case TelegramChats.channel: Copy.Honest.telegram
        default: nil
        }
    }

    /// The ways in use: those of the streams that are on, else those a source could read (browser first).
    static func ways(_ streams: [ResolvedStream]) -> [StreamHow] {
        let on = streams.filter { $0.stream.state == .on }
        let chosen = (on.isEmpty ? streams.filter { $0.stream.state == .off } : on).map(\.stream.how)
        var seen = Set<StreamHow>()
        let unique = chosen.filter { seen.insert($0).inserted }
        let order: [StreamHow] = [.browser, .account, .app, .click]
        return order.filter(unique.contains)
    }

    static func phrase(_ how: StreamHow, app: String?) -> String {
        switch how {
        case .browser: Copy.Streams.readInBrowser(app: app)
        case .app: Copy.Streams.readOnThisMac
        case .account: Copy.Streams.readWithSignIn
        case .click: Copy.Streams.noticedWhenYouSave
        case .other: ""
        }
    }

    /// The person's own AI app on this Mac: the first connected one, in the Agents page's order. A remote-only
    /// connection (claude.ai, ChatGPT) cannot read a list in a browser on this Mac, so it never stands here.
    static func app(rows: [AgentLiveRow]) -> AgentCatalogEntry? {
        let local = Set(rows.filter(\.connectedLocally).map(\.id))
        guard !local.isEmpty else { return nil }
        return AgentCatalog.all.first { entry in
            if case .remote = entry.kind { return false }
            return local.contains(entry.id) || !local.isDisjoint(with: entry.setupHarnesses)
        }
    }

    /// Whether a source reads a website through the person's own agent: the six saved lists, YouTube's, Substack's.
    static func readsThroughAI(_ entry: SourceCatalogEntry) -> Bool {
        entry.savedListKey != nil || entry.id == "youtube" || entry.id == SourceCatalog.substackId
    }
}

/// One Reads row, as words.
enum SourceStreamRow {
    /// What a row's control is. A switch only where one PUT (or the per-Mac flag) can flip it; every other stream shows
    /// the source's own connect step instead (plan 3.2 item 2).
    enum Control: Equatable {
        case toggle(on: Bool)
        case setup
    }

    /// The streams `PUT /reading/settings` flips: a list family's own key.
    static let listFamilies: Set<String> = ["savedLists", "youtubeLists", "substackLists"]

    static func control(_ resolved: ResolvedStream, pending: Bool? = nil) -> Control {
        let stream = resolved.stream
        guard stream.control == .switch, stream.state != .unavailable else { return .setup }
        let flippable = stream.how == .click || (stream.switchRef.map { listFamilies.contains($0.setting) } ?? false)
        guard flippable else { return .setup }
        return .toggle(on: pending ?? (stream.state == .on))
    }

    /// The quiet line under the name: how it is read, how deep its items go ("In your browser, by your AI app · kept
    /// and findable"). An unavailable stream says why instead.
    static func line(_ stream: SourceStream) -> String {
        if stream.state == .unavailable, let why = stream.why, !why.isEmpty { return why }
        var parts: [String] = []
        switch stream.how {
        case .browser: parts.append(Copy.Streams.lineBrowser)
        case .app: parts.append(Copy.Streams.lineApp)
        case .account: parts.append(Copy.Streams.lineAccount)
        case .click: parts.append(Copy.Streams.lineClick)
        case .other: break
        }
        parts.append(stream.depth == .read ? Copy.Streams.depthRead : Copy.Streams.depthIndex)
        return parts.joined(separator: " · ")
    }

    /// The hover: that the newest are read, that older ones come with the site's export (the window's drop), and that
    /// unsaving at the site does not remove one here — said for a list read in the browser, nothing for the rest.
    static func help(_ stream: SourceStream) -> String? {
        if stream.state == .unavailable, let why = stream.why, !why.isEmpty { return why }
        guard stream.how == .browser, stream.kind.isList else { return nil }
        return Copy.Streams.browserReach
    }

    /// What stands at the row's trailing edge before the control: "214 · 2h ago" for a healthy read, else the state word.
    struct Trailing: Equatable {
        var text: String?
        var word: StreamWord?
        /// "last: read" beside "Your AI app reads it next".
        var note: String?
        var help: String?
    }

    static func trailing(_ resolved: ResolvedStream, result: SourceStreamCheckModel.Result?, checking: Bool,
                         now: Date, locale: Locale = .autoupdatingCurrent) -> Trailing {
        let stream = resolved.stream
        let count = stream.count.map { UsageFormat.count($0) }
        if checking { return Trailing(text: count, word: nil, note: Copy.Streams.checking) }
        // A check's answer stands until the stream is read again (a newer read is the fresher word).
        if let result, stream.state == .on, stream.lastReadAt.map({ result.at >= $0 }) ?? true {
            let note = result.word == .yourAIAppReadsNext ? result.previous.map { Copy.Streams.lastResult($0.text) } : nil
            return Trailing(text: count, word: result.word, note: note,
                            help: Copy.Streams.checkedAgo(SourceCatalog.ago(result.at, now: now, locale: locale)))
        }
        switch resolved.word {
        case .read:
            let age = stream.lastReadAt.map { SourceCatalog.ago($0, now: now, locale: locale) }
            return Trailing(text: [count, age].compactMap { $0 }.joined(separator: " · "))
        case .off:
            return Trailing(text: count)
        default:
            return Trailing(text: count, word: resolved.word, help: stream.why)
        }
    }
}

/// The Items section's tabs: one per list stream that holds items (plan 3.2 item 3).
enum SourceStreamItems {
    /// How many cards before "All N" (DR-81; plan 3.2).
    static let cap = 5

    /// The streams whose items are cards under tabs: saved, liked, later and playlists. History stays the source's own
    /// content (a watched day opens to its videos, not to a card), and a stream no read has put an item on has no tab.
    static func tabbed(_ streams: [ResolvedStream]) -> [ResolvedStream] {
        streams.filter {
            let kind = $0.stream.kind
            return kind.isList && kind != .history && $0.stream.state != .unavailable && ($0.stream.count ?? 0) > 0
        }
    }

    /// Whether the page draws its items as cards: a source with a tabbed stream (the list kinds).
    static func usesCards(_ streams: [ResolvedStream]) -> Bool { !tabbed(streams).isEmpty }

    /// Tab selection: nil is All. Drawn only when more than one stream holds items (a lone list is the page's list).
    static func tabs(_ streams: [ResolvedStream]) -> [TextTab<String>] {
        let held = tabbed(streams)
        guard held.count > 1 else { return [] }
        return [TextTab<String>(id: nil, label: Copy.Streams.all)]
            + held.map { TextTab<String>(id: $0.id, label: $0.stream.label, count: $0.stream.count) }
    }

    /// The tab that is really selected: a stream that no longer holds items falls back to All.
    static func effective(_ selection: String?, streams: [ResolvedStream]) -> String? {
        guard let selection, tabbed(streams).contains(where: { $0.id == selection }) else { return nil }
        return selection
    }

    /// The folders menu: only for one stream with folders (`folderCount > 0`); All has none (plan 3.2).
    static func folderStream(_ selection: String?, streams: [ResolvedStream]) -> ResolvedStream? {
        let held = tabbed(streams)
        let chosen = effective(selection, streams: streams).flatMap { id in held.first { $0.id == id } }
            ?? (held.count == 1 ? held.first : nil)
        guard let chosen, chosen.stream.folderCount > 0 else { return nil }
        return chosen
    }

    /// The folder names the menu offers: the channel's own collections when the backend files them, else the folders the
    /// rows read so far name. Sorted by how many items they hold when known, then by name.
    static func folderNames(collections: ChannelCollections?, items: [ChannelItem]) -> [String] {
        var names: [String] = []
        var seen = Set<String>()
        for account in collections?.accounts ?? [] {
            for collection in account.collections where !collection.name.isEmpty && seen.insert(collection.name).inserted {
                names.append(collection.name)
            }
        }
        if names.isEmpty {
            for folder in items.flatMap({ $0.folders ?? [] }) where seen.insert(folder).inserted { names.append(folder) }
        }
        return names
    }

    /// The list key the cards read: the channel, narrowed by stream and folder.
    static func key(channel: String, stream: String?, folder: String?) -> String {
        SourceListKey.make(channel, stream: stream, folder: stream == nil ? nil : folder)
    }
}

/// An item card's words (plan 3.2 item 3): two lines of the person's own words, and the footer
/// `[mark] site · kept 2d · Bookmarks · Likes · read` — kept age, the lists it is on, the depth word (nothing for kept).
enum SourceItemCardText {
    /// The depth word: nothing for `kept`; B3 adds `asked` and `watched`.
    static func depth(_ item: ChannelItem) -> String? {
        switch item.depth {
        case "read": Copy.Streams.itemRead
        case "asked": Copy.Streams.itemAsked
        case "watched": Copy.Streams.itemWatched
        default: nil
        }
    }

    /// The footer's words after the mark, in order. The row's own day stays "kept on"; `posted` is the post's own day.
    static func footer(_ item: ChannelItem, today: ISODay, locale: Locale = .autoupdatingCurrent) -> [String] {
        var parts: [String] = []
        if let host = item.host, !host.isEmpty { parts.append(host) }
        if let posted = ISODay(item.posted) {
            parts.append(Copy.Streams.posted(RelativeDay.phrase(posted, today: today, locale: locale)))
        }
        if let age = CapturedItems.age(item, today: today, locale: locale) { parts.append(Copy.Streams.kept(age.text)) }
        if let lists = item.lists, !lists.isEmpty { parts.append(lists.joined(separator: " · ")) }
        if let depth = depth(item) { parts.append(depth) }
        return parts
    }

    /// The card's words: the person's own (why they saved it), else the reasons they tapped.
    static func words(_ item: ChannelItem) -> String? {
        if let words = SavedItemText.words(item) { return words }
        let labels = item.why?.labels ?? []
        return labels.isEmpty ? nil : labels.joined(separator: " · ")
    }
}
