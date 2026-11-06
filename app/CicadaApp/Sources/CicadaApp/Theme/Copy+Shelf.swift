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
        static let nothingYet = "Nothing in yet"
        static let onThisMac = "On this Mac"
    }

    /// The website-reading card: an animation before the switch, and what a service reads, said plainly. Checked
    /// against `docs/architecture/mcp.md` ("Saved lists on X, Instagram and LinkedIn", Substack) and `network.md`.
    enum WebReading {
        static let replay = "Replay"
        static let replayHelp = "Watch it again"
        static let noApp = "No assistant app yet"
        static let noAppLine = "Connect one on the Agents page. Until then nothing is read, and the switch waits."
        static let openAgents = "Open Agents"
        static let yourAssistant = "your assistant app"
        static let yourBrowser = "your browser"
        static let cicada = "Cicada"
        static func turnOn(_ site: String) -> String { "You turn on \(site)" }
        static func nextTime(app: String) -> String { "Next time you use \(app), it can look at it" }
        static func opens(app: String, site: String, browser: String) -> String {
            "\(app) opens \(site) in \(browser), where you are signed in"
        }
        static func reads(list: String) -> String { "It reads only \(list), never anything else" }
        static let hands = "It hands what it saw to Cicada, which keeps each as a link"
        /// The honest lines (one each: what is read, whose sign-in, who else sees it, how to stop).
        static func whatIsRead(list: String) -> String { "Reads \(list), at most 10 times a day. Never posts, likes or changes anything." }
        static let whoseSession = "Your own browser and your own sign-in. Cicada never sees a password and never opens a browser."
        static func whoSees(app: String) -> String { "What \(app) reads goes through the company behind it. Cicada keeps what comes back as links, and no model reads one unless you name it." }
        static let oneClick = "One click on the switch turns it off. What is already kept stays until you remove it."
    }
}
