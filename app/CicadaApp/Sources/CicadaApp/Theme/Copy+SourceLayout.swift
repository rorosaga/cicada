import Foundation

extension Copy {
    /// The standard source page (`SourcePageLayout`, owner 2026-11-04): the words its slots draw, short and said once.
    enum SourceLayout {
        static let readInBrowser = "Read through your browser"
        static let readInBrowserHelp = "Your own agent reads it in your signed-in browser, only when you ask"
        static let importFile = "Import a file"
        static let choose = "Choose…"
        static let refresh = "Refresh"
        static let refreshHelp = "Read it again now"
        static let disconnect = "Disconnect"
        static func disconnectTitle(_ source: String) -> String { "Disconnect \(source)?" }
        static let disconnectKeeps = "What already came in stays in your memory."
        static func connect(_ source: String) -> String { "Connect \(source)" }
        static let reconnect = "Reconnect"
        static let open = "Open…"
        static let folders = "Folders"
        static let history = "History"
        /// YouTube's ways in, named by what they read; how each reads is its hover.
        static let historyInChrome = "History in Chrome"
        /// A browser's ways in.
        static let bookmarks = "Bookmarks"
        static func bookmarksHelp(_ browser: String) -> String {
            "Cicada reads \(browser)'s bookmarks on this Mac each time they change"
        }
        static let youtubeHere = "YouTube you watch here"
        static func youtubeList(_ list: YouTubeList) -> String {
            list == .watchLater ? "Watch later, in your browser" : "Watch history, in your browser"
        }
        static let saved = "Saved"
        static let chooseChats = "Choose chats…"
        static func requestExport(_ app: String) -> String { "Request your \(app) export" }
        static let browserSettings = "Browser reading…"
        static let browserSettingsHelp = "What your own agent may read in your signed-in browser, and how"
        static func notesRead(new: Int, unchanged: Int) -> String {
            "\(UsageFormat.count(new)) new · \(UsageFormat.count(unchanged)) unchanged"
        }
        /// The drop zone on a source's own page: what to drop, said once (the full how-to is its hover).
        static let dropExport = "Drop the export here"
        static let chooseFile = "Choose a file…"
    }
}
