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

    /// The story in four plain steps, all on screen at once (a reader who never watches the picture still has it), the
    /// one the picture is at lit while it plays. Round 6: six readers lost at "assistant app" and "Claude Code", so the
    /// AI is introduced by what it is to them (the one they use on this Mac) and the steps say what each one does.
    static func steps(entry: SourceCatalogEntry, app: String, browser: String) -> [String] {
        [Copy.WebReading.stepTurnOn(entry.title),
         Copy.WebReading.stepNote(app: app, list: list(entry.id)),
         Copy.WebReading.stepOpens(app: app, site: entry.title, browser: browser, list: list(entry.id)),
         Copy.WebReading.stepBack(site: entry.title)]
    }

    /// Which step the picture is at: the turn-on, the note, the opening (two lanes: the AI to the browser, the browser
    /// to the site), the way back. `beat` runs -1 (before) ... 4 (finished).
    static func step(atBeat beat: Int) -> Int { [0, 0, 1, 2, 2, 3][min(max(beat, -1), 4) + 1] }

    /// What travels along the lane after node `lane` (0...2): the note out to the AI, the AI's looking, the page seen.
    static let laneGlyphs = ["note.text", "cursorarrow.click.2", "eye"]
    /// What comes back along every lane: the saved items.
    static let backGlyph = "bookmark.fill"

    /// What a node does, under its name, in words that need no vocabulary.
    static func role(node: Int, list: String) -> String {
        switch node {
        case 0: Copy.WebReading.roleCicada
        case 1: Copy.WebReading.roleAI
        case 2: Copy.WebReading.roleBrowser
        default: list
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
