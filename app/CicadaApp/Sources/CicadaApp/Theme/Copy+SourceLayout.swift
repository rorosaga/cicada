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
    }
}
