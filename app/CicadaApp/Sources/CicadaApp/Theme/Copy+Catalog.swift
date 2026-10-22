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
        /// G206 — honest about what exists: the permission is real, the saved-list reader is not built yet.
        static let instagramHonest = "Saved posts through your browser are coming. Today, import a data export."
        static let chatExportsHere = "Each chat export sits on its agent's row."
        static let dropHint = "Drop an export or a bookmarks file here."
        static func eyebrow(_ connected: Int) -> String { "\(connected) connected" }
    }
}
