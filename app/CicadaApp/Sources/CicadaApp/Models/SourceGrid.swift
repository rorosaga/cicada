import Foundation

/// ROR-7 (G217, G161; owner: "a grid of applications … each source as its app, with its icon") — the Sources root as
/// tiles, pure: which section a tile sits in, what its one line says, what a search finds and what is suggested. Three
/// questions, in the order a person asks them: what is waiting on me, what is connected, what could I add.

/// What a source is, which is how a person looks for it: "my chats", not "the ones on this Mac". `SourceCatalogGroup`
/// (how it comes in) stays the rules' word and is never drawn. Every entry names its category, so a new source without
/// one does not compile.
enum SourceCategory: String, CaseIterable, Identifiable {
    case messaging, calendars, browsers, social, media, reading, notes, meetings, files, agents

    var id: String { rawValue }

    var title: String {
        switch self {
        case .messaging: Copy.Catalog.messaging
        case .calendars: Copy.Catalog.calendarsAndContacts
        case .browsers: Copy.Catalog.browsers
        case .social: Copy.Catalog.social
        case .media: Copy.Catalog.videoAndMusic
        case .reading: Copy.readingGroup
        case .notes: Copy.Catalog.notesAndWork
        case .meetings: Copy.Catalog.meetings
        case .files: Copy.Catalog.filesAndActivity
        case .agents: Copy.Catalog.conversations
        }
    }
}

/// A tile's place on the page. A source sits in exactly one, so the arrow keys and `ForEach` never meet it twice.
enum SourceGridSection: Hashable, Identifiable {
    case needsYou, connected, suggested
    case category(SourceCategory)

    var id: String {
        switch self {
        case .needsYou: "needs-you"
        case .connected: "connected"
        case .suggested: "suggested"
        case .category(let category): category.rawValue
        }
    }

    var title: String {
        switch self {
        case .needsYou: Copy.Catalog.needsYou
        case .connected: Copy.Catalog.connected
        case .suggested: Copy.Catalog.suggested
        case .category(let category): category.title
        }
    }
}

extension SourceCatalogRow {
    /// Waiting on the person: a sign-in, an agent, a permission, or a read their page already calls Needs you.
    var needsYou: Bool {
        !notInstalled && (status == .needsSignIn || status == .waitingForAgent || waitingOn != nil)
    }

    /// What the eyebrow counts, so the Connected section and "6 connected" can never disagree (#619): a row Connected
    /// only through a reader another row holds keeps its green dot in its own category.
    var isConnectedHere: Bool { status == .connected && countsAsConnected && !needsYou }

    var section: SourceGridSection {
        if needsYou { return .needsYou }
        if isConnectedHere { return .connected }
        if suggested, status == .off, !notInstalled { return .suggested }
        return .category(entry.category)
    }

    /// The word and dot for a row or a tile. A permission taken away reads Needs access over Off.
    var word: String {
        if waitingOn == Copy.sourceNeedsAccess { return Copy.Catalog.needsAccess }
        if waitingOn != nil { return Copy.SourcePage.needsYou }
        return status.word
    }

    var tone: StatusWord.Tone { waitingOn != nil ? .attention : status.tone }

    /// What the person sees on hover: the whole reason when there is one.
    var help: String {
        if let waitingOn { return waitingOn }
        return status == .waitingForAgent ? Copy.Catalog.waitingForAgentHelp : entry.title
    }
}

enum SourceGrid {
    /// A tile's narrowest, in units: fits a two-line tile with "Waits for your agent" beside its 36 pt mark.
    static let tileMinWidth: CGFloat = 210
    static let searchMaxWidth: CGFloat = 320

    /// The sections in the page's order; an empty one is not drawn. Inside a section the categories' order, then the
    /// catalogue's, so a tile never moves unless its status did.
    static func sections(_ rows: [SourceCatalogRow]) -> [(section: SourceGridSection, rows: [SourceCatalogRow])] {
        let ordered = SourceCategory.allCases.flatMap { category in rows.filter { $0.entry.category == category } }
        let all: [SourceGridSection] = [.needsYou, .connected, .suggested]
            + SourceCategory.allCases.map(SourceGridSection.category)
        return all.compactMap { section in
            let inSection = ordered.filter { $0.section == section }
            return inSection.isEmpty ? nil : (section, inSection)
        }
    }

    /// The rows in the order the page draws them: what the arrow keys walk.
    static func drawnOrder(_ rows: [SourceCatalogRow]) -> [SourceCatalogRow] { sections(rows).flatMap(\.rows) }

    // MARK: - A tile's line

    struct Line: Equatable {
        let word: String
        let tone: StatusWord.Tone
    }

    /// The one line under a tile's name, only when it says something. The section already says Connected, so a
    /// connected tile says when it last read; an off tile says nothing at all: no dot is the word.
    static func line(_ row: SourceCatalogRow, now: Date, locale: Locale = .autoupdatingCurrent) -> Line? {
        if row.notInstalled { return Line(word: Copy.SourcePage.notInstalledRow, tone: .off) }
        if row.status == .waitingForAgent { return Line(word: Copy.Catalog.waitsForAgent, tone: .off) }
        if row.needsYou { return Line(word: row.word, tone: row.tone) }
        guard row.status == .connected else { return nil }
        return Line(word: row.lastSync.map { SourceCatalog.ago($0, now: now, locale: locale) } ?? row.status.word,
                    tone: .on)
    }

    // MARK: - Search

    /// Whether the field holds words to find, rather than nothing or only spaces.
    static func isSearching(_ text: String) -> Bool { !QuickMatch.tokens(text).isEmpty }

    /// What the typed words find, best first, through the app's one ranker: no network, no model. A source's own name
    /// leads; the words it also goes by (`alsoKnownAs`: its company, an old name, what it holds) and its category follow.
    /// A company's apps each appear as themselves, wherever they sit on the page.
    static func results(_ rows: [SourceCatalogRow], query: String) -> [SourceCatalogRow] {
        let order = drawnOrder(rows)
        let place = Dictionary(uniqueKeysWithValues: order.enumerated().map { ($0.element.id, Double($0.offset)) })
        return QuickMatch.rank(order, query: query, fields: fields, tieBreak: { -(place[$0.id] ?? 0) },
                               name: \.entry.title).map(\.item)
    }

    private static func fields(_ row: SourceCatalogRow) -> [QuickMatch.Field] {
        [QuickMatch.Field(row.entry.title, weight: QuickMatch.Weight.name)]
            + (alsoKnownAs[row.id] ?? []).map { QuickMatch.Field($0, weight: QuickMatch.Weight.intent) }
            + [QuickMatch.Field(row.entry.category.title, weight: QuickMatch.Weight.keyword),
               QuickMatch.Field(row.section.title, weight: QuickMatch.Weight.keyword)]
    }

    /// The tile a key press lands on: the one the arrows moved to while it is still found, else the best result.
    static func highlighted(_ results: [SourceCatalogRow], cursor: String?) -> String? {
        if let cursor, results.contains(where: { $0.id == cursor }) { return cursor }
        return results.first?.id
    }

    /// One step along the results, stopping at either end.
    static func moved(_ delta: Int, in results: [SourceCatalogRow], cursor: String?) -> String? {
        let ids = results.map(\.id)
        guard let current = highlighted(results, cursor: cursor), let at = ids.firstIndex(of: current) else { return nil }
        return ids[min(max(at + delta, 0), ids.count - 1)]
    }

    /// Words a person might type that are not on the tile. Never drawn, so naming a company here names nobody as doing
    /// a job. An entry's own name is not repeated.
    static let alsoKnownAs: [String: [String]] = [
        "x": ["Twitter", "bookmarks"],
        "youtube": ["Google", "Takeout", "videos", "watch later"],
        "instagram": ["Meta", "saved posts"],
        "linkedin": ["Microsoft", "connections", "saved posts"],
        "reddit": ["saved posts", "upvoted"],
        "pinterest": ["pins", "boards"],
        "github": ["Microsoft", "repositories", "stars", "code"],
        "spotify": ["podcasts", "liked songs", "listening"],
        "tiktok": ["ByteDance", "favorites", "videos"],
        SourceCatalog.substackId: ["newsletters"],
        "calendar-local": ["Apple", "iCal", "events"],
        "contacts-local": ["Apple", "people", "address book"],
        RemindersReader.channel: ["Apple", "tasks", "to-do"],
        "imessage": ["Apple", "iMessage", "SMS", "texts"],
        WhatsAppWatcher.channel: ["Meta", "chats"],
        SourceCatalog.tracesId: ["screen", "screenshots", "activity"],
        "notes": ["Apple", "iCloud"],
        "folders": ["Obsidian", "vault", "Markdown", "Finder"],
        AppleBooksReader.channel: ["Apple", "iBooks", "highlights"],
        "goodreads": ["Amazon", "books"],
        "book-scan": ["ISBN", "phone", "books"],
        "files": ["bookmarks", "HTML", "zip", "import", "export"],
        "notion": ["pages", "databases"],
        "chat-exports": ["ChatGPT", "OpenAI", "Claude", "Anthropic", "Gemini", "Google"],
        "rss": ["feeds", "Atom", "blogs", "news"],
        "calendar": ["Google", "Google Calendar", "Outlook", "Microsoft", "ICS", "iCal", "events"],
        "telegram": ["bot", "chats"],
        TelegramChats.channel: ["chats"],
        SourceCatalog.hexId: ["recorder", "transcripts"],
        SourceCatalog.meetingFoldersId: ["recorder", "recordings", "Otter", "MacWhisper", "subtitles"],
        SourceCatalog.browserPrefix + "chrome": ["Google", "bookmarks", "tab groups"],
        SourceCatalog.browserPrefix + "safari": ["Apple", "bookmarks", "reading list"],
        SourceCatalog.browserPrefix + "brave": ["bookmarks"],
        SourceCatalog.browserPrefix + "vivaldi": ["bookmarks"],
        SourceCatalog.browserPrefix + "comet": ["Perplexity", "bookmarks"],
        SourceCatalog.browserPrefix + "dia": ["The Browser Company", "bookmarks"],
    ]

    // MARK: - Suggested

    /// The bundle ids that can suggest a source: the notch's own list (`ConnectSuggestApps`), so the two can never
    /// disagree about what Cicada reads. An Apple app comes with every Mac, so having it says nothing about the person.
    static func suggestableApps() -> [String: String] {
        var apps = ConnectSuggestApps.fixed.filter { ConnectSuggestApps.offered($0.value.entryId) }
            .mapValues(\.entryId)
        for spec in BrowserInventory.catalog where spec.supported {
            apps[spec.bundleId] = SourceCatalog.browserPrefix + spec.id
        }
        return apps.filter { !$0.key.hasPrefix("com.apple.") }
    }

    /// Off sources whose app the person chose to install here, minus any they said No to on the notch: No is never again
    /// (`ConnectSuggestPolicy`). Launch Services only, the same question a tile's icon asks; nothing inside the app is read.
    static func suggested(installed: (String) -> Bool, declined: Set<String>) -> Set<String> {
        Set(suggestableApps().filter { installed($0.key) && !declined.contains($0.value) }.values)
    }
}
