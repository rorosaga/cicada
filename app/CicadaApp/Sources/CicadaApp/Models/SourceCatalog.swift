import Foundation

/// G217 (ruling 36 D6) — the Sources page's one catalogue: every way information comes into Cicada, grouped by how it
/// comes in, each with one status word. It replaces the old Integrations page's list and the "Add a source" sheet's grid
/// (two catalogues of the same things, app-inventory duplicate 12). Pure: the page passes in what it already holds
/// (`/sources/channels`, `/sources/overview`, the browsers on this Mac, the sites an agent may read), so the words and
/// the order are tested without a view.
enum SourceCatalogGroup: String, CaseIterable, Identifiable {
    case accounts, thisMac, exports, feeds, conversations

    var id: String { rawValue }

    var title: String {
        switch self {
        case .accounts: Copy.Catalog.accounts
        case .thisMac: Copy.Catalog.thisMac
        case .exports: Copy.Catalog.exports
        case .feeds: Copy.Catalog.feeds
        case .conversations: Copy.Catalog.conversations
        }
    }
}

/// Dot plus one word (ruling 36, the connection model's status words for Sources), and one honest fourth: a list the
/// person turned on that only their own agent can read, while no such agent is connected (tester readiness
/// 2026-10-26 — a fresh setup read "5 connected" with nothing able to read four of them). It is on, it is not
/// connected, and it never counts as connected.
enum SourceCatalogStatus: Equatable {
    case connected, needsSignIn, off
    case waitingForAgent

    var word: String {
        switch self {
        case .connected: Copy.Catalog.connected
        case .needsSignIn: Copy.Catalog.needsSignIn
        case .off: Copy.Catalog.off
        case .waitingForAgent: Copy.Catalog.waitingForAgent
        }
    }
}

/// What a row does when it is off — the one verb on the row (design-refs "Patterns to take" 4–5).
enum SourceCatalogVerb: Equatable {
    /// Open the detail, where the source's own control turns it on.
    case connect(String)
    /// G206 — the per-site permission, and (since #426) the saved list the person's own agent reads in their browser.
    case turnOn
    /// A one-shot import: the export's own walkthrough.
    case importFile
    /// Chat exports live on their agent's row.
    case openAgents
}

struct SourceCatalogEntry: Identifiable, Equatable {
    let id: String
    let group: SourceCatalogGroup
    let title: String
    /// An `OriginIconography` key: the installed app's icon, else the bundled mark, else a symbol.
    let origin: String
    /// The `/sources/channels` ids (and `/sources/overview` ids) this entry speaks for.
    let channels: [String]
    /// The export or connector flow the old sheet held for it, opened straight to its flow.
    var tile: AddSourceTile? = nil
    /// The walled site family (`reading_hosts.WALLED_DOMAINS`: x, instagram, linkedin, reddit, tiktok) an agent reads in
    /// the person's own browser for this entry — the per-site reading control.
    var site: String? = nil
    /// The off verb.
    var verb: SourceCatalogVerb = .connect(Copy.Catalog.connect)
    /// A `/sources/overview` row with no catalogue entry (an agent's conversations, until the Agents page holds them).
    var overviewId: String? = nil
}

/// One entry as the list draws it: status, last sync and the line under the name.
struct SourceCatalogRow: Identifiable, Equatable {
    let entry: SourceCatalogEntry
    let status: SourceCatalogStatus
    let lastSync: Date?
    var id: String { entry.id }
}

enum SourceCatalog {
    static let folderPrefix = "folder:"
    static let browserPrefix = "browser:"
    /// `LocalSourceWatcher.wisprChannel` (main-actor isolated there).
    static let wisprChannel = "wispr-flow"
    /// G218 — activity traces' entry, origin and `localReaders` key: recorded by the app, kept by This Mac's backend.
    static let tracesId = "traces"

    /// The fixed entries. Browsers on this Mac and watched folders are added from what is present (`entries`).
    /// The Obsidian vault entry is gone for now (owner 2026-10-22); a vault is a folder.
    static let fixed: [SourceCatalogEntry] = [
        SourceCatalogEntry(id: "x", group: .accounts, title: "X", origin: "x", channels: ["x"], tile: .x,
                           site: "x"),
        // 2026-10-23 (live test): the overview's own ids too — `youtube-history` (watched days, Takeout or Chrome) first,
        // then `youtube` (saved playlists) — or a Takeout import of thousands of episodes left the row reading Off.
        SourceCatalogEntry(id: "youtube", group: .accounts, title: "YouTube", origin: "youtube-playlist",
                           channels: [WatchHistoryWatcher.channel, "youtube-history", "youtube"], tile: .youtube),
        SourceCatalogEntry(id: "instagram", group: .accounts, title: "Instagram", origin: "instagram-saved",
                           channels: ["instagram"], tile: .instagram, site: "instagram", verb: .turnOn),
        SourceCatalogEntry(id: "linkedin", group: .accounts, title: "LinkedIn", origin: "linkedin-saved",
                           channels: ["linkedin"], tile: .linkedin, site: "linkedin", verb: .importFile),
        SourceCatalogEntry(id: "reddit", group: .accounts, title: "Reddit", origin: "reddit", channels: ["reddit"],
                           tile: .reddit, site: "reddit"),
        SourceCatalogEntry(id: "pinterest", group: .accounts, title: "Pinterest", origin: "pinterest",
                           channels: ["pinterest"], tile: .pinterest),
        // Ruling 47 tier 2: highlights with their sources, through the person's own Readwise token.
        SourceCatalogEntry(id: "readwise", group: .accounts, title: "Readwise", origin: "readwise",
                           channels: ["readwise"]),
        SourceCatalogEntry(id: "tiktok", group: .accounts, title: "TikTok", origin: "tiktok-saved",
                           channels: ["tiktok"], tile: .tiktok, site: "tiktok", verb: .importFile),
        SourceCatalogEntry(id: "calendar-local", group: .thisMac, title: "Calendar", origin: "calendar-local",
                           channels: ["calendar-local"], verb: .connect(Copy.Catalog.connectCalendar)),
        SourceCatalogEntry(id: "contacts-local", group: .thisMac, title: "Contacts", origin: "contacts-local",
                           channels: [ContactsReader.channel], verb: .connect(Copy.Catalog.connectContacts)),
        // G219: the lists the person ticks in Reminders, read by the app (`RemindersReader`), one way.
        SourceCatalogEntry(id: RemindersReader.channel, group: .thisMac, title: Copy.remindersTitle,
                           origin: RemindersReader.channel, channels: [RemindersReader.channel],
                           verb: .connect(Copy.Catalog.connectReminders)),
        SourceCatalogEntry(id: "imessage", group: .thisMac, title: "Messages", origin: "imessage",
                           channels: [MessagesWatcher.channel], verb: .connect(Copy.Catalog.chooseChats)),
        // G179 (2026-10-28): WhatsApp read live from its Mac store, the Messages way (`WhatsAppWatcher`).
        SourceCatalogEntry(id: WhatsAppWatcher.channel, group: .thisMac, title: Copy.Chats.whatsAppTitle,
                           origin: "whatsapp", channels: [WhatsAppWatcher.channel],
                           verb: .connect(Copy.Catalog.chooseChats)),
        // G218 — activity traces: no backend channel; its status is the recorder's (`localReaders[tracesId]`).
        SourceCatalogEntry(id: tracesId, group: .thisMac, title: Copy.Traces.title, origin: tracesId, channels: [],
                           verb: .connect(Copy.Traces.turnOn)),
        SourceCatalogEntry(id: "notes", group: .thisMac, title: "Apple Notes", origin: "apple-notes",
                           channels: ["notes"], tile: .appleNotes, verb: .connect(Copy.Catalog.connectNotes)),
        SourceCatalogEntry(id: "folders", group: .thisMac, title: Copy.Catalog.folders, origin: "folder",
                           channels: [], verb: .connect(Copy.Catalog.addFolder)),
        SourceCatalogEntry(id: "files", group: .exports, title: Copy.Catalog.filesAndLinks, origin: "bookmark",
                           channels: ["files"], tile: .bookmarksFile, verb: .importFile),
        // G219 slice 1: a Notion export (Markdown & CSV) through the one intake; ruling 47 tier 2: or live, through the
        // person's own connection (`notion-api`), on the same row.
        SourceCatalogEntry(id: "notion", group: .exports, title: "Notion", origin: "notion-export",
                           channels: ["notion", "notion-api"], verb: .importFile),
        SourceCatalogEntry(id: "chat-exports", group: .exports, title: Copy.Catalog.chatExports,
                           origin: "claude-export",
                           channels: ["chat-export:claude", "chat-export:chatgpt", "chat-export:gemini"],
                           verb: .openAgents),
        SourceCatalogEntry(id: "rss", group: .feeds, title: "RSS", origin: "rss", channels: ["rss"], tile: .rssFeed,
                           verb: .connect(Copy.Catalog.addFeed)),
        SourceCatalogEntry(id: "calendar", group: .feeds, title: Copy.Catalog.calendarFeeds, origin: "calendar",
                           channels: ["calendar"], tile: .calendar, verb: .connect(Copy.Catalog.addFeed)),
        SourceCatalogEntry(id: "telegram", group: .feeds, title: "Telegram", origin: "telegram",
                           channels: ["telegram"], tile: .telegram),
    ]

    /// Every entry: the fixed ones, one per browser on this Mac (or one that synced before), Wispr Flow once it is
    /// here, and — until the Agents page holds them — one per agent whose conversations the overview lists.
    static func entries(browsers: [BrowserSpec], wisprPresent: Bool,
                        overview: [SourceOverview]) -> [SourceCatalogEntry] {
        var all = fixed
        let browserEntries = browsers.map { spec in
            SourceCatalogEntry(id: browserPrefix + spec.id, group: .thisMac, title: spec.name, origin: spec.origin,
                               channels: [spec.bookmarksChannel, spec.tabGroupsChannel,
                                          spec.id == WatchHistoryWatcher.browser ? WatchHistoryWatcher.channel : nil]
                                   .compactMap { $0 } + (spec.id == "safari" ? ["safari-tabs"] : []),
                               verb: .connect(Copy.Catalog.connect))
        }
        // Browsers sit after Messages, before Apple Notes: the Mac's own apps first.
        let at = all.firstIndex { $0.id == "notes" } ?? all.endIndex
        all.insert(contentsOf: browserEntries, at: at)
        if wisprPresent {
            let folders = all.firstIndex { $0.id == "folders" } ?? all.endIndex
            all.insert(SourceCatalogEntry(id: wisprChannel, group: .thisMac, title: "Wispr Flow",
                                          origin: "wispr-flow", channels: [wisprChannel]),
                       at: folders + 1)
        }
        let claimed = Set(all.flatMap(\.channels))
        for row in overview where row.kind == .harness && !claimed.contains(row.id)
            && !claimed.contains(row.channelId ?? "") {
            all.append(SourceCatalogEntry(id: "overview:" + row.id, group: .conversations, title: row.label,
                                          origin: row.mark, channels: [], verb: .openAgents, overviewId: row.id))
        }
        return all
    }

    /// 2026-10-26 — where the file an entry imports comes from, said before its Import a file button. Every entry that
    /// offers a file import has one (Notion says its own in `notionHow`; chat exports live on the Agents page); an
    /// entry with no line imports no file.
    static func exportHow(_ id: String) -> String? {
        switch id {
        case "youtube": Copy.Catalog.howYouTube
        case "instagram": Copy.Catalog.howInstagram
        case "tiktok": Copy.Catalog.howTikTok
        case "linkedin": Copy.Catalog.howLinkedIn
        case "files": Copy.Catalog.howBookmarksFile
        default: nil
        }
    }

    /// The overview row an entry's "what came in" reads, when there is one.
    static func overviewRow(for entry: SourceCatalogEntry, in overview: [SourceOverview]) -> SourceOverview? {
        if let id = entry.overviewId { return overview.first { $0.id == id } }
        if entry.id == "folders" {
            return overview.first { ($0.channelId ?? $0.id).hasPrefix(folderPrefix) }
        }
        return overview.first { row in
            entry.channels.contains(row.id) || entry.channels.contains(row.channelId ?? "")
        }
    }

    /// A failure that reads as a lapsed sign-in: the row's one action becomes "Sign in" (design-refs pattern 5).
    static func readsAsSignIn(_ error: String?) -> Bool {
        guard let error = error?.lowercased(), !error.isEmpty else { return false }
        return ["sign in", "signed in", "log in", "login", "reconnect", "expired", "unauthor", "401", "403",
                "token", "auth"].contains { error.contains($0) }
    }

    /// The channels a person signs in to (`ChannelActions.connectorChannels`). Only these can need a sign-in: a reader
    /// on this Mac whose failure happens to say "not authorized" or "token" needs a permission or a retry, never an
    /// account (2026-10-23).
    static let signInChannels: Set<String> = ["pinterest", "reddit", "x", "readwise", "notion-api"]
    /// G206 (#426): the sites whose saved list the person's own agent can keep current from their signed-in browser
    /// (`reading_settings.SAVED_LISTS`).
    static let savedListSites: Set<String> = ["x", "instagram", "linkedin"]
    /// An overview row an import shares with a reader on this Mac → that reader's channel: Takeout's watch history and
    /// Chrome's watched days are both `youtube-history`.
    static let sharedWithReader: [String: String] = ["youtube-history": WatchHistoryWatcher.channel]

    /// One entry's status: Needs sign-in when a connector's last failure says so; Connected when a channel is connected
    /// and, for a reader this Mac runs, that reader is still on (`localReaders`: channel id → on; 2026-10-23 — a
    /// Calendar disconnected here kept reading Connected, because the backend only knows it synced once); also a
    /// folder channel for Folders, an allowed site for an account read in the browser, any conversation for an agent's
    /// row; Off otherwise. A site an agent reads in the person's browser (an allowed site, a saved list kept current)
    /// is Connected only while a local agent that can read it is connected (`localAgent`: one on this Mac, through
    /// stdio and hooks — the reading tools are stdio only); turned on with none, it waits for one, and says so.
    static func status(for entry: SourceCatalogEntry, channels: [SourceChannel], overview: [SourceOverview],
                       readableSites: Set<String>, localReaders: [String: Bool] = [:],
                       savedListsOn: Set<String> = [], localAgent: Bool = false) -> SourceCatalogStatus {
        // G218 — traces read Connected only while the recorder records here; paused, off or on a server they read Off
        // (ruling 36's three words; the detail's own line says "Paused until …").
        if entry.id == tracesId { return localReaders[tracesId] == true ? .connected : .off }
        let mine = channelsOf(entry, in: channels)
        if mine.contains(where: { signInChannels.contains($0.id) && readsAsSignIn($0.lastError) }) {
            return .needsSignIn
        }
        if mine.contains(where: { $0.connected && localReaders[$0.id] != false }) { return .connected }
        if entry.overviewId != nil, overviewRow(for: entry, in: overview) != nil { return .connected }
        if entry.id == "chat-exports", mine.contains(where: { $0.count > 0 }) { return .connected }
        // An account's import that fed memory counts, as a chat export does (2026-10-23, live test: YouTube read Off
        // over a Takeout's thousands of episodes). Only an overview row no channel speaks for — an import — and not one a
        // reader on this Mac also writes while that reader is off (`youtube-history` holds Chrome's watched days too),
        // so a reader turned off never comes back as Connected through its own episodes (review of #448).
        if entry.group == .accounts, overview.contains(where: { row in
            row.channelId == nil && row.episodes > 0 && entry.channels.contains(row.id)
                && !(sharedWithReader[row.id].map { localReaders[$0] == false } ?? false)
        }) {
            return .connected
        }
        let agentReads = entry.site.map { site in
            (entry.verb == .turnOn && readableSites.contains(site))
                // G206: the person's agent keeps this site's saved list current (agent reading on, the list's switch on).
                || savedListsOn.contains(site)
        } ?? false
            // 2026-10-26: the same for YouTube's Watch later and history (`savedListsOn` holds "youtube" then).
            || (entry.id == "youtube" && savedListsOn.contains("youtube"))
        if agentReads { return localAgent ? .connected : .waitingForAgent }
        return .off
    }

    static func channelsOf(_ entry: SourceCatalogEntry, in channels: [SourceChannel]) -> [SourceChannel] {
        if entry.id == "folders" { return channels.filter { $0.id.hasPrefix(folderPrefix) } }
        return channels.filter { entry.channels.contains($0.id) }
    }

    /// The newest sync among an entry's channels, else the overview's last activity.
    static func lastSync(for entry: SourceCatalogEntry, channels: [SourceChannel],
                         overview: [SourceOverview]) -> Date? {
        let synced = channelsOf(entry, in: channels).compactMap { $0.lastSync.flatMap(ISODate.parse) }
        if let newest = synced.max() { return newest }
        return overviewRow(for: entry, in: overview)?.lastActivityDate
    }

    static func rows(entries: [SourceCatalogEntry], channels: [SourceChannel], overview: [SourceOverview],
                     readableSites: Set<String>, localReaders: [String: Bool] = [:],
                     savedListsOn: Set<String> = [], localAgent: Bool = false) -> [SourceCatalogRow] {
        entries.map { entry in
            SourceCatalogRow(entry: entry,
                             status: status(for: entry, channels: channels, overview: overview,
                                            readableSites: readableSites, localReaders: localReaders,
                                            savedListsOn: savedListsOn, localAgent: localAgent),
                             lastSync: lastSync(for: entry, channels: channels, overview: overview))
        }
    }

    /// The groups in their fixed order, each in the catalogue's order; an empty group is not drawn.
    static func grouped(_ rows: [SourceCatalogRow]) -> [(group: SourceCatalogGroup, rows: [SourceCatalogRow])] {
        SourceCatalogGroup.allCases.compactMap { group in
            let inGroup = rows.filter { $0.entry.group == group }
            return inGroup.isEmpty ? nil : (group, inGroup)
        }
    }

    /// "Sources · 6 connected" — the eyebrow counts what is connected; a list waiting for an agent is not.
    static func connectedCount(_ rows: [SourceCatalogRow]) -> Int {
        rows.filter { $0.status == .connected }.count
    }

    /// The second line, only when it says something: when it last synced ("2 h ago"), else nothing (the status word
    /// on the right says the rest — never a sentence, design-refs pattern 4).
    static func line(_ row: SourceCatalogRow, now: Date, locale: Locale = .autoupdatingCurrent) -> String? {
        guard row.status == .connected || row.status == .needsSignIn, let last = row.lastSync else { return nil }
        guard now.timeIntervalSince(last) >= 60 else { return Copy.Catalog.justNow }
        let f = RelativeDateTimeFormatter()
        f.unitsStyle = .short
        f.dateTimeStyle = .numeric
        f.locale = locale
        return f.localizedString(for: last, relativeTo: now)
    }
}

/// ISO-8601 with or without fractional seconds, as the backend writes it.
enum ISODate {
    static func parse(_ text: String) -> Date? {
        let plain = ISO8601DateFormatter()
        if let d = plain.date(from: text) { return d }
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = fractional.date(from: text) { return d }
        let day = DateFormatter()
        day.locale = Locale(identifier: "en_US_POSIX")
        day.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        day.timeZone = TimeZone(identifier: "UTC")
        return day.date(from: String(text.prefix(19)))
    }
}
