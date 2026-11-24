import Foundation

/// ROR-7 (G217, G161) — what a source's row says, pure: which section a row sits in, what its one line says, which words
/// a person may also type for it and what is suggested. The root's cards, their order and their find are `SourcesRoot`
/// (G245); the sections here are the catalogue's own and what the narrow rows' tests pin.

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

/// A row's place on the page. A source sits in exactly one, so the arrow keys and `ForEach` never meet it twice.
/// ROR-118 (owner: "group by kind of information, never by vendor"): what waits on the person, then the six shelves.
enum SourceGridSection: Hashable, Identifiable {
    case needsYou
    case shelf(SourceShelf)

    var id: String {
        switch self {
        case .needsYou: "needs-you"
        case .shelf(let shelf): shelf.rawValue
        }
    }

    var title: String {
        switch self {
        case .needsYou: Copy.Catalog.needsYou
        case .shelf(let shelf): shelf.title
        }
    }
}

extension SourceCatalogRow {
    /// Waiting on the person: a sign-in, an agent, a permission, or a read their page already calls Needs you.
    var needsYou: Bool {
        !notInstalled && (status == .needsSignIn || status == .waitingForAgent || waitingOn != nil
            || browser?.state == .signedOut || browser?.state == .couldntRead)
    }

    /// What the eyebrow counts, so the Connected section and "6 connected" can never disagree (#619): a row Connected
    /// only through a reader another row holds keeps its green dot in its own category.
    /// A list the person's own agent reads in their browser is connected once it has read: on with nothing read yet is
    /// turned on, not connected (sources-truth, owner 2026-11-06); one that could not read is Needs you.
    var isConnectedHere: Bool {
        status == .connected && countsAsConnected && !needsYou && browser?.state != .notReadYet
    }

    var section: SourceGridSection { needsYou ? .needsYou : .shelf(entry.shelf) }

    /// The word and dot for a row or a tile. A permission taken away reads Needs access over Off or Connected.
    var word: String {
        if waitingOn == Copy.sourceNeedsAccess { return Copy.Catalog.needsAccess }
        if waitingOn != nil { return Copy.SourcePage.needsYou }
        return browser?.state.word ?? status.word
    }

    /// A source read through the person's own browser has its own colour (ROR-114, DR-5/DR-8): blue when it reads,
    /// grey before the first read, amber when signed out or unreadable. A connection stays green.
    var tone: StatusWord.Tone {
        if waitingOn != nil { return .attention }
        return browser?.state.tone ?? status.tone
    }

    /// What the person sees on hover: the whole reason when there is one.
    var help: String {
        if let waitingOn { return waitingOn }
        return status == .waitingForAgent ? Copy.Catalog.waitingForAgentHelp : entry.title
    }
}

enum SourceGrid {
    static let searchMaxWidth: CGFloat = 320

    /// The sections in the page's order; an empty one is not drawn. Inside a shelf what is connected leads, then the
    /// catalogue's own order (category, then entry), so a row never moves unless its status did.
    static func sections(_ rows: [SourceCatalogRow]) -> [(section: SourceGridSection, rows: [SourceCatalogRow])] {
        let ordered = SourceCategory.allCases.flatMap { category in rows.filter { $0.entry.category == category } }
        let all: [SourceGridSection] = [.needsYou] + SourceShelf.allCases.map(SourceGridSection.shelf)
        return all.compactMap { section in
            let inSection = ordered.filter { $0.section == section }
            let lead = inSection.filter(\.isConnectedHere) + inSection.filter { !$0.isConnectedHere }
            return lead.isEmpty ? nil : (section, lead)
        }
    }

    /// The rows in the order the page draws them: what the arrow keys walk.
    static func drawnOrder(_ rows: [SourceCatalogRow]) -> [SourceCatalogRow] { sections(rows).flatMap(\.rows) }

    // MARK: - A tile's line

    struct Line: Equatable {
        let word: String
        let tone: StatusWord.Tone
    }

    /// The one line under a tile's name, only when it says something. A connected tile says when it last read; an
    /// off tile says nothing at all: no dot is the word.
    static func line(_ row: SourceCatalogRow, now: Date, locale: Locale = .autoupdatingCurrent) -> Line? {
        if row.notInstalled { return Line(word: Copy.SourcePage.notInstalledRow, tone: .off) }
        if row.status == .waitingForAgent { return Line(word: Copy.Catalog.waitsForAgent, tone: .off) }
        if row.needsYou { return Line(word: row.word, tone: row.tone) }
        // The section already says Connected; the colour and these words say how it is read.
        if row.browser != nil, row.status == .connected { return Line(word: row.word, tone: row.tone) }
        guard row.status == .connected else { return nil }
        if let lastSync = row.lastSync { return Line(word: SourceCatalog.ago(lastSync, now: now, locale: locale), tone: .on) }
        return Line(word: row.status.word, tone: .on)
    }

    // MARK: - Search

    /// Whether the field holds words to find, rather than nothing or only spaces.
    static func isSearching(_ text: String) -> Bool { !QuickMatch.tokens(text).isEmpty }

    /// Words a person might type that are not on the card. Never drawn, so naming a company here names nobody as doing
    /// a job. An entry's own name is not repeated.
    static let alsoKnownAs: [String: [String]] = [
        "x": ["Twitter", "bookmarks"],
        "youtube": ["Google", "Takeout", "videos", "watch later"],
        "instagram": ["Meta", "saved posts"],
        "linkedin": ["Microsoft", "connections", "saved posts"],
        "reddit": ["saved posts", "upvoted"],
        "pinterest": ["pins", "boards"],
        "github": ["Microsoft", "repositories", "stars", "code"],
        "linear": ["issues", "tickets", "comments", "projects"],
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
        VoiceMemosReader.channel: ["Apple", "audio", "recordings", "dictation"],
        "book-scan": ["ISBN", "phone", "books"],
        GoogleBooksKeyModel.id: ["Google", "API key", "books", "descriptions"],
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
