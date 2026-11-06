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
        /// An empty shelf's one line, and a shelf with sources' add line: "Add Notion, Folders".
        static func add(_ names: [String]) -> String { "Add " + names.joined(separator: ", ") }
        static let addSource = "Add source"
        static let addHelp = "Add a source: what you already have, then everything else"
        static let addTitle = "Add a source"
        static let yours = "Yours"
        static let all = "All"
        static let close = "Close"
        static let nothingToAdd = "Nothing else to add here"
        static func savedCount(_ n: Int) -> String { n == 1 ? "1 saved" : "\(n.formatted()) saved" }
        static func itemCount(_ n: Int) -> String { n == 1 ? "1 item" : "\(n.formatted()) items" }
        static func conversationCount(_ n: Int) -> String { n == 1 ? "1 conversation" : "\(n.formatted()) conversations" }
        static let nothingYet = "Nothing in yet"
    }

    /// The website-reading card: an animation before the switch, and what a service reads, said plainly. Checked
    /// against `docs/architecture/mcp.md` ("Saved lists on X, Instagram and LinkedIn", Substack) and `network.md`.
    enum WebReading {
        static let replay = "Replay"
        static let replayHelp = "Watch it again"
        static let noApp = "No AI app connected yet"
        static let noAppLine = "Cicada asks an AI app on this Mac to open your list in your browser. The app does the reading, not Cicada."
        static let openAgents = "Connect an AI app"
        static let yourAssistant = "your AI app"
        static let yourBrowser = "your browser"
        static let cicada = "Cicada"
        static func turnOn(_ site: String) -> String { "You turn on \(site)" }
        static func nextTime(app: String) -> String { "Next time you use \(app), it can look at it" }
        static func opens(app: String, site: String, browser: String) -> String {
            "\(app) opens \(site) in \(browser), where you are signed in"
        }
        static func reads(list: String) -> String { "It reads only \(list), never anything else" }
        static let hands = "It hands each item's link and words to Cicada, which keeps them"
        /// The honest lines (one each: what is read, whose sign-in, who else sees it, how to stop).
        static func whatIsRead(list: String, app: String) -> String {
            "On this Mac, in your browser, while you use \(app): reads \(list) about once a day. Never posts or changes anything."
        }
        static let whoseSession = "Your browser, your sign-in. Cicada never sees a password."
        static func whoSees(app: String) -> String { "\(app)'s company sees what it reads. No model reads a saved item unless you name it." }
        static let oneClick = "One click on the switch turns it off. What was kept stays until you remove it."
    }

    /// One honest line on a source that reads through the person's own sign-in or key, before its switch. Checked
    /// against `network.md` (ruling 47's table, 47a): Notion and Linear read-only, GitHub's read-only app, Telegram's
    /// ticked one-to-one chats. A source that needs none (a folder, an export) has none.
    enum Honest {
        static let notion = "Read-only: it reads the pages you share and can't change anything in Notion."
        static let linear = "Read-only: your issues and their comments. It can't change anything in Linear."
        static let github = "Read-only: your repositories and stars. It can't change anything on GitHub."
        static let telegram = "Reads only the one-to-one chats you tick, through your own Telegram sign-in."
    }
}
