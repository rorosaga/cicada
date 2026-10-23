import Foundation

/// G217 (ruling 36 D6) — the Sources catalogue's words. Few on purpose: a row is a mark, a name and one status word.
extension Copy {
    enum Catalog {
        static let accounts = "Accounts and browser"
        static let thisMac = "This Mac"
        static let exports = "Exports"
        static let feeds = "Feeds"
        static let conversations = "Agents' conversations"

        static let connected = "Connected"
        static let needsSignIn = "Needs sign-in"
        static let off = "Off"
        static let justNow = "just now"

        static let connect = "Connect"
        static let connectCalendar = "Connect the calendar"
        static let connectContacts = "Connect Contacts"
        static let connectNotes = "Connect Notes"
        static let chooseChats = "Choose chats"
        static let addFolder = "Add a folder"
        static let addFeed = "Add a feed"
        static let turnOn = "Turn on"
        static let importFile = "Import a file"
        static let openAgents = "Open Agents"
        static let signIn = "Sign in"
        static let manage = "Manage"
        static let refresh = "Refresh"

        static let folders = "Folders"
        static let filesAndLinks = "Files and links"
        static let chatExports = "Chat exports"
        static let calendarFeeds = "Calendar feeds"

        static let whatCameIn = "What came in"
        static let reading = "Reading"
        static func readSite(_ name: String) -> String { "Your agent may read \(name) in your browser" }
        /// G206 (#426) — what exists: the person's own agent on this Mac reads the saved list in their signed-in browser
        /// once its switch is on, at most 10 reads a day; or an export. (2026-10-23: it said "coming".)
        static let instagramHonest = "Your own agent on this Mac can read your Saved posts in your signed-in browser — "
            + "turn on the list below. Or import a data export."
        static let savedListOff = "Your own agent reads this list in your signed-in browser, at most 10 times a day. "
            + "Saved posts are kept for lookup, never read."
        static func readSavedList(_ site: String) -> String {
            switch site {
            case "x": "Read my Bookmarks in my browser"
            case "linkedin": "Read my Saved posts in my browser"
            default: "Read my Saved in my browser"
            }
        }
        static let chatExportsHere = "Each chat export sits on its agent's row."
        static let dropHint = "Drop an export or a bookmarks file here."
        static func eyebrow(_ connected: Int) -> String { "\(connected) connected" }

        // 2026-10-23 — connectors that work, said as they work.
        static let disconnect = "Disconnect"
        static let howToSetUp = "How to set it up"
        /// Apple Notes keeps up once read, and only while Notes is open (`AppleNotesWatcher`).
        static let notesOff = "Cicada reads every folder once when you connect, then every two hours while Notes is "
            + "open. macOS asks once whether Cicada may read Notes."
        static let notesOn = "Reads new and edited notes every two hours while Notes is open."
        /// Telegram reaches Cicada only through a webhook on a public address (`POST /capture/telegram`).
        static let telegramHonest = "Telegram needs a public web address that reaches this Mac, and Cicada doesn't "
            + "open one. A developer setup for now."
    }
}
