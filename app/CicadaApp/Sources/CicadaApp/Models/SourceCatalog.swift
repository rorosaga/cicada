import Foundation

/// G217 (ruling 36 D6) — the Sources page's one catalogue: every way information comes into Cicada, each with one status
/// word. It replaces the old Integrations page's list and the "Add a source" sheet's grid (two catalogues of the same
/// things, app-inventory duplicate 12). Pure: the page passes in what it already holds (`/sources/channels`,
/// `/sources/overview`, the browsers on this Mac, the sites an agent may read), so the words and the order are tested
/// without a view. How a source comes in decides the rules (an account's import counts as Connected); the page draws
/// what it is (`SourceCategory`) and what it needs (`SourceGridSection`).
enum SourceCatalogGroup: String, CaseIterable, Identifiable {
    case accounts, thisMac, meetings, reading, exports, feeds, conversations

    var id: String { rawValue }
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
    /// An agent's conversations live on its row of the Agents page.
    case openAgents
}

struct SourceCatalogEntry: Identifiable, Equatable {
    let id: String
    let group: SourceCatalogGroup
    /// What the source is: where its tile sits while it is neither connected nor waiting on the person.
    let category: SourceCategory
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
    /// 2026-11-04 — the app this source reads was removed from this Mac: Off, and the row says why.
    var notInstalled = false
    /// False for a row Connected only through a reader another row holds (`readerHome`): it reads Connected, and the
    /// eyebrow does not count that reader twice.
    var countsAsConnected = true
    /// The reason a read is waiting on the person (macOS took a permission away, the reader's failure), nil when none.
    var waitingOn: String? = nil
    /// Off, and its app is on this Mac: offered above the rest (`SourceGrid.suggested`).
    var suggested = false
    var id: String { entry.id }
}

enum SourceCatalog {
    /// The chat-exports tile takes every assistant's export, so it wears no one company's mark (provider-neutral copy).
    static let chatExportsOrigin = "chat-exports"
    static let folderPrefix = "folder:"
    static let browserPrefix = "browser:"
    /// `LocalSourceWatcher.wisprChannel` (main-actor isolated there).
    static let wisprChannel = "wispr-flow"
    /// Owner 2026-11-04 ("remove wisprflow also from sources for now"): not on offer anywhere, and the app's reader does
    /// not run, for everyone, connected or not. What already came in stays, a turned-on setting and the read cursor too,
    /// so this one line brings the row, the tile, the notch's offer and the reader back, resuming where it stopped.
    static let wisprOffered = false
    /// G218 — activity traces' entry, origin and `localReaders` key: recorded by the app, kept by This Mac's backend.
    static let tracesId = "traces"
    /// G95 (2026-11-03) — Meeting recorders: Hex's own Markdown folder, and any other folder of transcripts. Both are
    /// meeting folders (`FolderRegistration.isMeetings`), told apart by the folder's `recorder`.
    static let hexId = "hex"
    /// G89 — Substack's entry, and the `savedListsOn` key its lists read as.
    static let substackId = "substack"
    static let meetingFoldersId = "meeting-folders"

    /// The fixed entries. Browsers on this Mac and watched folders are added from what is present (`entries`).
    /// The Obsidian vault entry is gone for now (owner 2026-10-22); a vault is a folder.
    static let fixed: [SourceCatalogEntry] = [
        SourceCatalogEntry(id: "x", group: .accounts, category: .social, title: "X", origin: "x", channels: ["x"],
                           tile: .x, site: "x"),
        // 2026-10-23 (live test): the overview's own ids too — `youtube-history` (watched days, Takeout or Chrome) first,
        // then `youtube` (saved playlists) — or a Takeout import of thousands of episodes left the row reading Off.
        SourceCatalogEntry(id: "youtube", group: .accounts, category: .media, title: "YouTube",
                           origin: "youtube-playlist",
                           channels: [WatchHistoryWatcher.channel, "youtube-history", "youtube"], tile: .youtube),
        SourceCatalogEntry(id: "instagram", group: .accounts, category: .social, title: "Instagram",
                           origin: "instagram-saved", channels: ["instagram"], tile: .instagram, site: "instagram",
                           verb: .turnOn),
        SourceCatalogEntry(id: "linkedin", group: .accounts, category: .social, title: "LinkedIn",
                           origin: "linkedin-saved", channels: ["linkedin"], tile: .linkedin, site: "linkedin",
                           verb: .importFile),
        SourceCatalogEntry(id: "reddit", group: .accounts, category: .social, title: "Reddit", origin: "reddit",
                           channels: ["reddit"], tile: .reddit, site: "reddit"),
        SourceCatalogEntry(id: "pinterest", group: .accounts, category: .social, title: "Pinterest", origin: "pinterest",
                           channels: ["pinterest"], tile: .pinterest),
        // G230: the repositories the person owns and the ones they starred, through their own GitHub token.
        SourceCatalogEntry(id: "github", group: .accounts, category: .notes, title: "GitHub", origin: "github",
                           channels: ["github"]),
        // G32: Spotify is export-only (its terms bar an API connector): the library and the listening, from the
        // person's own download.
        SourceCatalogEntry(id: "spotify", group: .accounts, category: .media, title: "Spotify", origin: "spotify-saved",
                           channels: ["spotify", "spotify-listening"], verb: .importFile),
        SourceCatalogEntry(id: "tiktok", group: .accounts, category: .social, title: "TikTok", origin: "tiktok-saved",
                           channels: ["tiktok"], tile: .tiktok, site: "tiktok", verb: .importFile),
        // G89 (2026-11-04): Substack gives readers no API or export — the person's own agent reads Saved, History and
        // Subscriptions in their browser (the overview's own ids: saves, then reading days).
        SourceCatalogEntry(id: substackId, group: .accounts, category: .reading, title: "Substack",
                           origin: "substack-saved", channels: ["substack", "substack-history"],
                           verb: .connect(Copy.Catalog.turnOn)),
        SourceCatalogEntry(id: "calendar-local", group: .thisMac, category: .calendars, title: "Calendar",
                           origin: "calendar-local", channels: ["calendar-local"],
                           verb: .connect(Copy.Catalog.connectCalendar)),
        SourceCatalogEntry(id: "contacts-local", group: .thisMac, category: .calendars, title: "Contacts",
                           origin: "contacts-local", channels: [ContactsReader.channel],
                           verb: .connect(Copy.Catalog.connectContacts)),
        // G219: the lists the person ticks in Reminders, read by the app (`RemindersReader`), one way.
        SourceCatalogEntry(id: RemindersReader.channel, group: .thisMac, category: .calendars,
                           title: Copy.remindersTitle, origin: RemindersReader.channel,
                           channels: [RemindersReader.channel], verb: .connect(Copy.Catalog.connectReminders)),
        SourceCatalogEntry(id: "imessage", group: .thisMac, category: .messaging, title: "Messages", origin: "imessage",
                           channels: [MessagesWatcher.channel], verb: .connect(Copy.Catalog.chooseChats)),
        // G179 (2026-10-28): WhatsApp read live from its Mac store, the Messages way (`WhatsAppWatcher`).
        SourceCatalogEntry(id: WhatsAppWatcher.channel, group: .thisMac, category: .messaging,
                           title: Copy.Chats.whatsAppTitle, origin: "whatsapp", channels: [WhatsAppWatcher.channel],
                           verb: .connect(Copy.Catalog.chooseChats)),
        // G218 — activity traces: no backend channel; its status is the recorder's (`localReaders[tracesId]`).
        SourceCatalogEntry(id: tracesId, group: .thisMac, category: .files, title: Copy.Traces.title, origin: tracesId,
                           channels: [], verb: .connect(Copy.Traces.turnOn)),
        SourceCatalogEntry(id: "notes", group: .thisMac, category: .notes, title: "Apple Notes", origin: "apple-notes",
                           channels: ["notes"], tile: .appleNotes, verb: .connect(Copy.Catalog.connectNotes)),
        SourceCatalogEntry(id: "folders", group: .thisMac, category: .files, title: Copy.Catalog.folders,
                           origin: "folder", channels: [], verb: .connect(Copy.Catalog.addFolder)),
        // G39 — Apple Books on this Mac, read by the app (`AppleBooksReader`) only after Connect; G233 — a Goodreads
        // export the person chooses.
        SourceCatalogEntry(id: AppleBooksReader.channel, group: .reading, category: .reading,
                           title: Copy.appleBooksTitle, origin: AppleBooksReader.channel,
                           channels: [AppleBooksReader.channel],
                           verb: .connect(Copy.SourceLayout.connect(Copy.appleBooksTitle))),
        SourceCatalogEntry(id: "goodreads", group: .reading, category: .reading, title: Copy.goodreadsTitle,
                           origin: "goodreads", channels: ["goodreads"], verb: .importFile),
        // G233: what the phone scanned. No control here: the scanner is the phone's.
        SourceCatalogEntry(id: "book-scan", group: .reading, category: .reading, title: Copy.bookScansTitle,
                           origin: "book-scan", channels: ["book-scan"]),
        SourceCatalogEntry(id: "files", group: .exports, category: .files, title: Copy.Catalog.filesAndLinks,
                           origin: "bookmark", channels: ["files"], tile: .bookmarksFile, verb: .importFile),
        // G219 slice 1: a Notion export (Markdown & CSV) through the one intake; ruling 47 tier 2: or live, through the
        // person's own connection (`notion-api`), on the same row.
        SourceCatalogEntry(id: "notion", group: .exports, category: .notes, title: "Notion", origin: "notion-export",
                           channels: ["notion", "notion-api"], verb: .importFile),
        SourceCatalogEntry(id: "chat-exports", group: .exports, category: .agents, title: Copy.Catalog.chatExports,
                           origin: chatExportsOrigin,
                           channels: ["chat-export:claude", "chat-export:chatgpt", "chat-export:gemini"],
                           verb: .importFile),
        SourceCatalogEntry(id: "rss", group: .feeds, category: .reading, title: "RSS", origin: "rss", channels: ["rss"],
                           tile: .rssFeed, verb: .connect(Copy.Catalog.addFeed)),
        SourceCatalogEntry(id: "calendar", group: .feeds, category: .calendars, title: Copy.Catalog.calendarFeeds,
                           origin: "calendar", channels: ["calendar"], tile: .calendar,
                           verb: .connect(Copy.Catalog.addFeed)),
        SourceCatalogEntry(id: "telegram", group: .feeds, category: .messaging, title: Copy.Chats.telegramBotTitle,
                           origin: "telegram", channels: ["telegram"], tile: .telegram),
        // Ruling 47a: the person's own Telegram chats, read through their own account by the backend.
        SourceCatalogEntry(id: TelegramChats.channel, group: .accounts, category: .messaging,
                           title: Copy.Chats.telegramTitle, origin: "telegram-chats", channels: [TelegramChats.channel],
                           verb: .connect(Copy.Chats.connect)),
    ]

    /// Every entry: the fixed ones, one per browser on this Mac (or one that synced before), the meeting recorders
    /// (Hex once it is here or has a folder, Wispr Flow once it is here, a folder of transcripts always), and — until
    /// the Agents page holds them — one per agent whose conversations the overview lists.
    static func entries(browsers: [BrowserSpec], wisprPresent: Bool, hexPresent: Bool = false,
                        meetingFolders: [FolderRegistration] = [],
                        overview: [SourceOverview]) -> [SourceCatalogEntry] {
        var all = fixed
        let browserEntries = browsers.map { spec in
            SourceCatalogEntry(id: browserPrefix + spec.id, group: .thisMac, category: .browsers, title: spec.name,
                               origin: spec.origin,
                               channels: [spec.bookmarksChannel, spec.tabGroupsChannel,
                                          spec.id == WatchHistoryWatcher.browser ? WatchHistoryWatcher.channel : nil]
                                   .compactMap { $0 } + (spec.id == "safari" ? ["safari-tabs"] : []),
                               verb: .connect(Copy.Catalog.connect))
        }
        // Browsers sit after Messages, before Apple Notes: the Mac's own apps first.
        let at = all.firstIndex { $0.id == "notes" } ?? all.endIndex
        all.insert(contentsOf: browserEntries, at: at)
        // G95 (2026-11-03): Meeting recorders sit after This Mac, before the exports.
        let meetings = meetingFolders.filter(\.isMeetings)
        let hexChannels = meetings.filter { $0.recorder == hexId }.map(\.channelId)
        var recorders: [SourceCatalogEntry] = []
        if hexPresent || !hexChannels.isEmpty {
            recorders.append(SourceCatalogEntry(id: hexId, group: .meetings, category: .meetings, title: "Hex",
                                                origin: hexId, channels: hexChannels,
                                                verb: .connect(Copy.Catalog.addHexFolder)))
        }
        if wisprPresent {
            recorders.append(SourceCatalogEntry(id: wisprChannel, group: .meetings, category: .meetings,
                                                title: "Wispr Flow", origin: "wispr-flow", channels: [wisprChannel]))
        }
        recorders.append(SourceCatalogEntry(id: meetingFoldersId, group: .meetings, category: .meetings,
                                            title: Copy.Catalog.meetingFolders, origin: meetingFoldersId,
                                            channels: meetings.filter { $0.recorder != hexId }.map(\.channelId),
                                            verb: .connect(Copy.Catalog.addFolder)))
        let exports = all.firstIndex { $0.group == .exports } ?? all.endIndex
        all.insert(contentsOf: recorders, at: exports)
        let claimed = Set(all.flatMap(\.channels))
        for row in overview where row.kind == .harness && !claimed.contains(row.id)
            && !claimed.contains(row.channelId ?? "") {
            all.append(SourceCatalogEntry(id: "overview:" + row.id, group: .conversations, category: .agents,
                                          title: row.label, origin: row.mark, channels: [], verb: .openAgents,
                                          overviewId: row.id))
        }
        return all
    }

    /// 2026-10-26 — where the file an entry imports comes from, said before its Import a file button. Every entry that
    /// offers a file import has one (Notion says its own in `notionHow`); an
    /// entry with no line imports no file.
    static func exportHow(_ id: String) -> String? {
        switch id {
        case "youtube": Copy.Catalog.howYouTube
        case "instagram": Copy.Catalog.howInstagram
        case "tiktok": Copy.Catalog.howTikTok
        case "spotify": Copy.Catalog.howSpotify
        case "linkedin": Copy.Catalog.howLinkedIn
        case "goodreads": Copy.goodreadsHow
        case "files": Copy.Catalog.howBookmarksFile
        case "chat-exports": Copy.Catalog.howChatExports
        default: nil
        }
    }

    /// CIC8 — the entry a hand-off naming `tile` opens: the entry that owns the tile, else Chat exports for an export
    /// tile (ChatGPT, Claude, Gemini share that one entry). Pure; tested.
    static func entry(for tile: AddSourceTile, in entries: [SourceCatalogEntry]) -> SourceCatalogEntry? {
        if let own = entries.first(where: { $0.tile == tile }) { return own }
        return tile.chatVendor == nil ? nil : entries.first { $0.id == "chat-exports" }
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
    static let signInChannels: Set<String> = ["pinterest", "reddit", "x", "notion-api", "github"]
    /// G206 (#426): the sites whose saved list the person's own agent can keep current from their signed-in browser
    /// (`reading_settings.SAVED_LISTS`).
    static let savedListSites: Set<String> = ["x", "instagram", "linkedin"]
    /// An overview row an import shares with a reader on this Mac → that reader's channel: Takeout's watch history and
    /// Chrome's watched days are both `youtube-history`.
    static let sharedWithReader: [String: String] = ["youtube-history": WatchHistoryWatcher.channel]

    /// ROR-41 ("Sources · 2 connected" with one switch on) — a channel two entries speak for belongs to the entry whose
    /// page holds its switch. Chrome's YouTube history is on Chrome's page and shows on YouTube's: one connection.
    static let readerHome: [String: String] = [WatchHistoryWatcher.channel: browserPrefix + WatchHistoryWatcher.browser]

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
        // 2026-11-04 (owner: "I just pressed sync contacts … it said syncing and then it turned off … now that it finished
        // syncing, it says connected. But I don't get why it wasn't connected from the start") — a reader this Mac runs
        // is Connected while it is on (allowed and turned on), whether or not the bank has recorded a sync yet: the
        // backend's `connected` means "a sync was recorded", which a fresh bank, a first read still running or a read
        // the bank refused (Sleep writing) leaves false. Off here stays Off whatever synced before (2026-10-23).
        if entry.channels.contains(where: { localReaders[$0] == true }) { return .connected }
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
            // G89: and for Substack's lists (`savedListsOn` holds "substack" then).
            || (entry.id == substackId && savedListsOn.contains(substackId))
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

    /// `checked` (2026-11-03): when a chat reader on this Mac last read its ticked chats, by entry id (`ChatCheck`) — a
    /// read that found nothing new is still a sync, so the row's "4 days ago" (the last read that POSTED) never stands
    /// for a reader that checked a minute ago.
    static func rows(entries: [SourceCatalogEntry], channels: [SourceChannel], overview: [SourceOverview],
                     readableSites: Set<String>, localReaders: [String: Bool] = [:],
                     savedListsOn: Set<String> = [], localAgent: Bool = false,
                     checked: [String: Date] = [:], notInstalled: Set<String> = [],
                     waitingOn: [String: String] = [:], suggested: Set<String> = [],
                     watch: (String) -> BrowserWatchState? = { _ in nil }) -> [SourceCatalogRow] {
        entries.map { entry in
            let synced = lastSync(for: entry, channels: channels, overview: overview)
            // 2026-11-04 — an app removed from this Mac (`LocalSourceWatcher.missingApps`) reads Off, whatever the bank's
            // switch says: nothing more can come from it.
            let gone = notInstalled.contains(entry.id)
            func read(_ readers: [String: Bool]) -> SourceCatalogStatus {
                gone ? .off : status(for: entry, channels: channels, overview: overview, readableSites: readableSites,
                                     localReaders: readers, savedListsOn: savedListsOn, localAgent: localAgent)
            }
            // What this row would read with every reader it only borrows switched off.
            let borrowed = entry.channels.filter { readerHome[$0].map { $0 != entry.id } ?? false }
            let own: SourceCatalogStatus? = borrowed.isEmpty ? nil
                : read(localReaders.merging(borrowed.map { ($0, false) }) { _, off in off })
            let current = read(localReaders)
            // ROR-7 — a connected reader that cannot read waits on the person: the same channel, the same words, as the
            // *Needs you* its own page says (`SourcePageStatus`), so the tile and the page never disagree.
            var problem: String?
            if current == .connected, let channel = channelsOf(entry, in: channels).first,
               case .problem(let why) = SourceRowText.status(channel: channel, watch: watch(channel.id), run: nil) {
                problem = why
            }
            return SourceCatalogRow(entry: entry, status: current,
                                    lastSync: [synced, checked[entry.id]].compactMap { $0 }.max(),
                                    notInstalled: gone, countsAsConnected: own.map { $0 == .connected } ?? true,
                                    waitingOn: gone ? nil : (waitingOn[entry.id] ?? problem),
                                    suggested: suggested.contains(entry.id))
        }
    }

    /// "Sources · 6 connected" — the eyebrow counts what the Connected section draws, each reader once (`readerHome`); a
    /// list waiting for an agent, or a read waiting on a permission, is not.
    static func connectedCount(_ rows: [SourceCatalogRow]) -> Int { rows.filter(\.isConnectedHere).count }

    /// The second line, only when it says something: when it last synced ("2 h ago"), else nothing (the status word
    /// on the right says the rest — never a sentence, design-refs pattern 4).
    static func line(_ row: SourceCatalogRow, now: Date, locale: Locale = .autoupdatingCurrent) -> String? {
        if row.notInstalled { return Copy.SourcePage.notInstalledRow }
        guard row.status == .connected || row.status == .needsSignIn, let last = row.lastSync else { return nil }
        return ago(last, now: now, locale: locale)
    }

    /// "just now" under a minute, else the short relative words ("4 days ago", "2 min. ago"), computed when read (DR-58).
    static func ago(_ date: Date, now: Date, locale: Locale = .autoupdatingCurrent) -> String {
        guard now.timeIntervalSince(date) >= 60 else { return Copy.Catalog.justNow }
        let f = RelativeDateTimeFormatter()
        f.unitsStyle = .short
        f.dateTimeStyle = .numeric
        f.locale = locale
        return f.localizedString(for: date, relativeTo: now)
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
