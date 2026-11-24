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
        // One sentence of phrases: a phrase after the first is joined by a comma, so it starts in lower case.
        if !ways.isEmpty {
            parts.append(ways.enumerated().map { index, how in
                let words = phrase(how, app: app)
                return index == 0 ? words : words.prefix(1).lowercased() + words.dropFirst()
            }.joined(separator: ", "))
        }
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
    static func ways(_ streams: [ResolvedStream]) -> [StreamHow] { ways(streams.map(\.stream)) }

    static func ways(_ streams: [SourceStream]) -> [StreamHow] {
        let streams = streams.filter { !$0.isDerived }   // a place posts go says nothing about how the source is read
        let on = streams.filter { $0.state == .on }
        let chosen = (on.isEmpty ? streams.filter { $0.state == .off } : on).map(\.how)
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
            // "Another agent" is the generic row, not a name: the line says "your AI app" for it (found in the real app).
            if case .remote = entry.kind { return false }
            if entry.id == "other" { return false }
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

    /// The quiet line under the name, only what is specific to THIS stream (DR-38: the head already says how the source
    /// is read, so a row never repeats it): its folders, the click stream's own way ("When you save, on this Mac"), how it
    /// is read when that differs from the head's, what it is for when its name does not say (connections), and how deep
    /// it goes when the source's streams differ in that. Nil says nothing; an unavailable stream says why instead.
    static func line(_ stream: SourceStream, among streams: [SourceStream] = []) -> String? {
        if stream.state == .unavailable, let why = stream.why, !why.isEmpty { return why }
        // "Saves you make", off by the person's own word while the source is on: the row says that is why.
        if stream.how == .click, stream.state == .off, let why = stream.why, !why.isEmpty { return why }
        var parts: [String] = []
        if stream.folderCount > 0 { parts.append(Copy.Streams.folders(stream.folderCount)) }
        if stream.how == .click {
            // On, and nothing in the way (Accessibility's own sentence replaces this one when it is missing).
            parts.append(stream.state == .on && stream.why == nil ? Copy.Streams.lineClickAsks : Copy.Streams.lineClick)
        } else if let word = howWord(stream, among: streams) {
            parts.append(word)
        }
        if stream.kind == .connections { parts.append(Copy.Streams.connectionsFor) }
        if stream.kind == .following { parts.append(Copy.Streams.followingFor) }
        if let depth = depthWord(stream, among: streams) { parts.append(depth) }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// How the stream is read, when the head's line does not already say it: the ways of the streams that are on (else
    /// those a source could read), as `SourceHeadLine.ways` counts them.
    private static func howWord(_ stream: SourceStream, among streams: [SourceStream]) -> String? {
        let headWays = SourceHeadLine.ways(streams)
        guard !headWays.isEmpty, !headWays.contains(stream.how) else { return nil }
        switch stream.how {
        case .browser: return Copy.Streams.lineBrowser
        case .app: return Copy.Streams.lineApp
        case .account: return Copy.Streams.lineAccount
        case .click, .other: return nil
        }
    }

    /// "read by Sleep" / "kept, never read: you did not save it", only where a source's streams go to different depths; a source whose
    /// streams all go to one says it nowhere (it is the same on every row).
    private static func depthWord(_ stream: SourceStream, among streams: [SourceStream]) -> String? {
        guard Set(streams.map(\.depth)).count > 1 else { return nil }
        return stream.depth == .read ? Copy.Streams.depthRead : Copy.Streams.depthIndex
    }

    /// The browsers a save inside a site is seen in: the ones Cicada reads (`SiteSaveWatcher.browsers`).
    static var supportedBrowserNames: String {
        BrowserInventory.catalog.filter(\.supported).map(\.name).joined(separator: ", ")
    }

    /// The hover: that the newest are read, that older ones come with the site's export (the window's drop), and that
    /// unsaving at the site does not remove one here — said for a list read in the browser, nothing for the rest.
    static func help(_ stream: SourceStream) -> String? {
        if stream.state == .unavailable, let why = stream.why, !why.isEmpty { return why }
        if stream.how == .click { return Copy.Streams.savesSeenIn(supportedBrowserNames) }
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

    /// The stream of the people the person has met (LinkedIn's connections) or follows (X's Following, ruling 79 (b)): drawn
    /// as its own tab beside the saved list, never as cards of posts (`LinkedInConnectionsView`, `FollowedAccountsView`). A
    /// source has one or the other, never both.
    static func connections(_ streams: [ResolvedStream]) -> ResolvedStream? {
        streams.first { ($0.stream.kind == .connections || $0.stream.kind == .following) && $0.stream.state != .unavailable }
    }

    /// The tabs of a page that has a connections stream: the saved lists under their own stream's name (one list) or
    /// "Saved" (several), then Connections. A list stream with nothing in it has no tab. Empty with no connections stream.
    static func peopleTabs(_ streams: [ResolvedStream]) -> [TextTab<String>] {
        guard let people = connections(streams) else { return [] }
        let held = tabbed(streams)
        var tabs: [TextTab<String>] = []
        if !held.isEmpty {
            let label = held.count == 1 ? held[0].stream.label : Copy.SourceLayout.saved
            tabs.append(TextTab<String>(id: listsTab, label: label, count: held.reduce(0) { $0 + ($1.stream.count ?? 0) }))
        }
        tabs.append(TextTab<String>(id: people.id, label: people.stream.label, count: people.stream.count))
        return tabs
    }

    /// The people tab's id for the saved lists.
    static let listsTab = "lists"

    /// The tab a page of people opens on: the one named, else Connections (what the person came for) when it holds
    /// anything or nothing else does, else the saved lists.
    static func peopleSelection(_ choice: String?, streams: [ResolvedStream]) -> String? {
        guard let people = connections(streams) else { return nil }
        let held = tabbed(streams)
        if let choice, choice == people.id || (choice == listsTab && !held.isEmpty) { return choice }
        if let choice, held.contains(where: { $0.id == choice }) { return listsTab }
        return (people.stream.count ?? 0) > 0 || held.isEmpty ? people.id : listsTab
    }

    /// Whether the page draws its items as cards: a source with a tabbed stream (the list kinds).
    static func usesCards(_ streams: [ResolvedStream]) -> Bool { !tabbed(streams).isEmpty }

    /// A watched history that holds days (YouTube's): its own tab beside the lists, its days drawn in the page's items area
    /// (the source's own rows, not cards). Nil when the source keeps none or none was read.
    static func historyStream(_ streams: [ResolvedStream]) -> ResolvedStream? {
        streams.first { $0.stream.kind == .history && $0.stream.state != .unavailable && ($0.stream.count ?? 0) > 0 }
    }

    /// Tab selection: nil is the cards (All the lists, or the one list there is). Drawn only when more than one thing holds
    /// items: several lists (All first, then each), or a list and the watched history.
    static func tabs(_ streams: [ResolvedStream]) -> [TextTab<String>] {
        let held = tabbed(streams)
        let history = historyStream(streams)
        guard held.count + (history == nil ? 0 : 1) > 1 else { return [] }
        var tabs: [TextTab<String>] = []
        if held.count > 1 {
            tabs.append(TextTab<String>(id: nil, label: Copy.Streams.all))
            tabs += held.map { TextTab<String>(id: $0.id, label: $0.stream.label, count: $0.stream.count) }
        } else if let only = held.first {
            tabs.append(TextTab<String>(id: nil, label: only.stream.label, count: only.stream.count))
        }
        if let history { tabs.append(TextTab<String>(id: history.id, label: history.stream.label, count: history.stream.count)) }
        return tabs
    }

    /// The tab that is really selected: a stream that no longer holds items falls back to the cards (nil); the watched
    /// history is the page's when it is the only thing that holds items.
    static func effective(_ selection: String?, streams: [ResolvedStream]) -> String? {
        if let history = historyStream(streams), selection == history.id || (selection == nil && tabbed(streams).isEmpty) {
            return history.id
        }
        guard let selection, tabbed(streams).contains(where: { $0.id == selection }) else { return nil }
        return selection
    }

    /// Whether the selected tab is the watched history (its days, not cards).
    static func showsHistory(_ selection: String?, streams: [ResolvedStream]) -> Bool {
        guard let history = historyStream(streams) else { return false }
        return effective(selection, streams: streams) == history.id
    }

    /// The folders menu: only for one stream with folders (`folderCount > 0`); All has none (plan 3.2).
    static func folderStream(_ selection: String?, streams: [ResolvedStream]) -> ResolvedStream? {
        if showsHistory(selection, streams: streams) { return nil }
        let held = tabbed(streams)
        let chosen = effective(selection, streams: streams).flatMap { id in held.first { $0.id == id } }
            ?? (held.count == 1 ? held.first : nil)
        guard let chosen, chosen.stream.folderCount > 0 else { return nil }
        return chosen
    }

    /// G246 (ruling 81) — the page that stands for what the selection shows: the chosen folder's own page, else the list's.
    /// The backend names it (`SourceStream.page`, `folderPages`) only once it exists, so while the posts-as-rows switch is
    /// off, for a list of works, a stream with nothing in it or a folder with no page, there is none and no link is drawn.
    /// `folder` is meaningful only on a stream that keeps folders. All, the watched history and a stream-less page: nil.
    struct PageLink: Equatable {
        let id: String
        let isFolder: Bool
        var title: String { isFolder ? Copy.Lists.openFolderPage : Copy.Lists.openListPage }
        var help: String { isFolder ? Copy.Lists.openFolderPageHelp : Copy.Lists.openListPageHelp }
    }

    static func pageLink(_ selection: String?, folder: String?, streams: [ResolvedStream]) -> PageLink? {
        if showsHistory(selection, streams: streams) { return nil }
        let held = tabbed(streams)
        let chosen = effective(selection, streams: streams).flatMap { id in held.first { $0.id == id } }
            ?? (held.count == 1 ? held.first : nil)
        guard let stream = chosen?.stream else { return nil }
        if let folder, !folder.isEmpty {
            return stream.folderPages[folder].map { PageLink(id: $0, isFolder: true) }
        }
        return stream.page.map { PageLink(id: $0, isFolder: false) }
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
/// `author · posted Sunday · Bookmarks · Likes · read` — one date, the lists it is on, the depth word (nothing for kept).
enum SourceItemCardText {
    /// The depth word, said for every state a saved item can be in (ruling 80): `read`, `kept` (not read yet), `empty`
    /// (nothing to read yet), `record` (kept, never read), `asked` and `watched`; nothing for a value this build does not
    /// know. Said in the footer's own style, never a badge.
    static func depth(_ item: ChannelItem) -> String? {
        switch item.depth {
        case "read": Copy.Streams.itemRead
        case "kept": Copy.Streams.itemNotRead
        case "empty": Copy.Streams.itemNothing
        case "record": Copy.Streams.itemRecord
        case "asked": Copy.Streams.itemAsked
        case "watched": Copy.Streams.itemWatched
        default: nil
        }
    }

    /// The footer's words, in order: the author when the row has one, ONE date (the post's own day when the list showed
    /// it, else when Cicada kept it), the lists it is on, and the depth word (nothing for `kept`). `showsSite` is for a
    /// card away from its source's own page: on the page every item is from that site, so the site and its mark are left
    /// out there (DR-38) and put first here.
    /// `omitting` is the list whose tab is open: every card on it is on that list, so it is not said again (DR-38).
    static func footer(_ item: ChannelItem, today: ISODay, showsSite: Bool = false, omitting list: String? = nil,
                       locale: Locale = .autoupdatingCurrent) -> [String] {
        var parts: [String] = []
        if showsSite, let host = item.host, !host.isEmpty { parts.append(host) }
        if let author = item.author?.trimmingCharacters(in: .whitespacesAndNewlines), !author.isEmpty { parts.append(author) }
        if let posted = ISODay(item.posted) {
            parts.append(Copy.Streams.posted(RelativeDay.phrase(posted, today: today, locale: locale)))
        } else if let age = CapturedItems.age(item, today: today, locale: locale) {
            parts.append(Copy.Streams.kept(age.text))
        }
        let lists = (item.lists ?? []).filter { $0 != list }
        if !lists.isEmpty { parts.append(lists.joined(separator: " · ")) }
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
