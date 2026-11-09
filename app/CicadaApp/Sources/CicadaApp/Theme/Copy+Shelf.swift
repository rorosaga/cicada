import Foundation

/// ROR-118 — the Sources page's shelves, its add overlay and the website-reading card. Few words on purpose: a shelf
/// is a heading and its sources, an add line is a verb and two names.
extension Copy {
    enum Shelf {
        static let conversations = "Conversations"
        static let documents = "Documents"
        static let events = "Events"
        static let work = "Work"
        static let saved = "Saved"
        static let media = "Media"
        static let addSource = "Add source"
        static let addHelp = "Add a source"
        static let addTitle = "Add a source"
        static let yours = "Yours"
        static let calendarNote = "Includes Google"
        static let close = "Close"
        static let nothingToAdd = "Nothing else to add here"
        static func savedCount(_ n: Int) -> String { n == 1 ? "1 saved" : "\(n.formatted()) saved" }
        static func itemCount(_ n: Int) -> String { n == 1 ? "1 item" : "\(n.formatted()) items" }
        static func conversationCount(_ n: Int) -> String { n == 1 ? "1 conversation" : "\(n.formatted()) conversations" }
        static let nothingYet = "Nothing in yet"
    }

    /// The website-reading card: an animation before the switch, and what a service reads, said plainly. Checked
    /// against `docs/architecture/mcp.md` ("Saved lists on X, Instagram and LinkedIn", Substack) and `network.md`.
    /// Round 6 (six blind readers lost at "assistant app", "Claude Code" and "Off"): no word the person has to know;
    /// the AI is "the AI you use on this Mac" once, then by its name; each node says what it does.
    enum WebReading {
        static let replay = "Replay"
        /// The closed fold over the four steps.
        static let howItWorks = "How it works"
        static let replayHelp = "Watch it again"
        static let yourAI = "your AI"
        static let yourBrowser = "your browser"
        static let cicada = "Cicada"
        /// Under each node, what it does.
        static let roleCicada = "keeps what comes back"
        static let roleAI = "the AI you use here"
        static let roleBrowser = "where you are signed in"
        /// The line above the picture: why a second app is in it at all.
        static func headline(site: String, app: String, list: String) -> String {
            "Cicada can't open \(site) itself. It asks \(app), the AI you use on this Mac, to read \(list) for it."
        }
        static let headlineNoAI = "Cicada can't open the site itself. It needs the AI you use on this Mac to look for it, and none is connected yet."
        static let openAgents = "Connect the AI you use"
        /// The four steps, in order.
        static func stepTurnOn(_ site: String) -> String { "You turn on \(site) here." }
        static func stepNote(app: String, list: String) -> String {
            "Next time you use \(app), Cicada leaves it a note asking it to look at \(list). At most once a day."
        }
        static func stepOpens(app: String, site: String, browser: String, list: String) -> String {
            "\(app) opens \(site) in \(browser), where you are already signed in, and looks only at \(list)."
        }
        static func stepBack(site: String) -> String {
            "It sends each item's link and words back to Cicada, which keeps them. Nothing on \(site) is posted or changed."
        }
        /// The three facts under the steps: whose sign-in, who else sees it, how to stop.
        static let whoseSession = "It uses your own sign-in, in your browser on this Mac. Cicada never sees your password and never opens the browser itself."
        static func whoSees(app: String) -> String {
            "\(app)'s company sees what it reads. No AI reads a saved item unless you mention it."
        }
        static let oneClick = "To stop, turn off \u{201C}\(Copy.SourceLayout.readInBrowser)\u{201D} on this page. What was kept stays until you remove it."
    }

    /// One honest line on a source that reads through the person's own sign-in or key, before its switch. Checked
    /// against `network.md` (ruling 47's table, 47a): Notion and Linear read-only, GitHub's read-only app, Telegram's
    /// ticked one-to-one chats. A source that needs none (a folder, an export) has none.
    enum Honest {
        static let notion = "Read-only: it reads only the pages and databases you choose and can't change anything in Notion."
        static let linear = "Read-only: your issues and their comments. It can't change anything in Linear."
        static let github = "Read-only: your repositories and stars. It can't change anything on GitHub."
        static let telegram = "Reads only the one-to-one chats you tick, through your own Telegram sign-in."
    }
}
