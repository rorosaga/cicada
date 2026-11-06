import Foundation

/// ROR-118 (owner, Sources round 1) — what the website-reading card shows, pure. All six blind readers got lost on the
/// first screen because "assistant app" and "Claude Code" meant nothing to them: the card names the person's own app
/// and browser and draws their own icons, so the first screen is about things they already know. Checked against
/// `docs/architecture/mcp.md` (saved lists, Substack): Cicada never opens a browser, never signs in and never fetches
/// the page; the person's own agent, on this Mac, reads the one list in their signed-in browser, at most 10 reads a day.
enum WebReadingScene {
    /// The four beats, in order: the person turns it on, the app is used, the browser opens the site, what it saw
    /// comes back. `rest` is the whole picture at once (reduced motion, a replay's end).
    static let beats = 4

    /// Which sources read a website through the person's own agent: the six saved lists, YouTube's lists, Substack's.
    static func applies(_ entry: SourceCatalogEntry) -> Bool {
        entry.savedListKey != nil || entry.id == "youtube" || entry.id == SourceCatalog.substackId
    }

    /// The person's own assistant app on this Mac: the first connected one, in the Agents page's order. A remote-only
    /// connection (claude.ai, ChatGPT) cannot read a list in a browser on this Mac, so it never stands here.
    static func app(rows: [AgentLiveRow]) -> AgentCatalogEntry? {
        let local = Set(rows.filter(\.connectedLocally).map(\.id))
        guard !local.isEmpty else { return nil }
        return AgentCatalog.all.first { entry in
            if case .remote = entry.kind { return false }
            return local.contains(entry.id) || !local.isDisjoint(with: entry.setupHarnesses)
        }
    }

    /// The list a person's agent reads, in the site's own word (`saved_lists.PLATFORMS`, `substack_lists.LISTS`).
    static func list(_ entryId: String) -> String {
        switch entryId {
        case "x": "your Bookmarks"
        case "instagram", "reddit": "your Saved posts"
        case "linkedin": "your Saved posts"
        case "pinterest": "your Saved Pins"
        case "tiktok": "your Favorites"
        case "youtube": "your Watch later and history"
        case SourceCatalog.substackId: "your Saved, History and Subscriptions"
        default: "your saved list"
        }
    }

    /// The caption under the picture while it plays: one sentence a beat (0 is the first).
    static func caption(beat: Int, entry: SourceCatalogEntry, app: String, browser: String) -> String {
        switch beat {
        case 0: Copy.WebReading.turnOn(entry.title)
        case 1: Copy.WebReading.nextTime(app: app)
        case 2: Copy.WebReading.opens(app: app, site: entry.title, browser: browser)
        case 3: Copy.WebReading.reads(list: list(entry.id))
        default: Copy.WebReading.hands
        }
    }

    /// Whether the picture plays by itself: the first time on this Mac, never again (the Replay button is the way
    /// back), and never with no app to play it for or with Reduce Motion on.
    static func autoplays(seen: Bool, hasApp: Bool, reduceMotion: Bool) -> Bool { !seen && hasApp && !reduceMotion }

    /// How many of the four nodes are lit at a beat: Cicada alone, then the app, then the browser, then the site. The
    /// last beat hands back, so all stay lit.
    static func litNodes(atBeat beat: Int) -> Int { min(max(beat, 0), 3) + 1 }

    /// The one honest line on a source that reads through the person's own sign-in (not a website read by their agent):
    /// nil for a source that needs none.
    static func honestLine(_ entryId: String) -> String? {
        switch entryId {
        case "notion": Copy.Honest.notion
        case "linear": Copy.Honest.linear
        case "github": Copy.Honest.github
        case TelegramChats.channel: Copy.Honest.telegram
        default: nil
        }
    }
}
