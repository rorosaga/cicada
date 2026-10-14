import Foundation

/// Links show as what they are (owner rulings 2026-10-14) — the link cards' and the view switcher's words (DR-59:
/// sentence case, plain verbs). Provider-neutral (owner 2026-09-30): a card says what Cicada knows and when, never who
/// fetched it.
extension Copy {
    enum Links {
        static let linksOnLine = "Links on this line"
        static let openHint = "Click to open · ⌘-click opens the browser"
        static let openInBrowser = "Open in the browser"
        static let copyLink = "Copy link"
        static let notRead = "Not read yet"
        static let noCapture = "No capture of this page yet"
        static let noCaptures = "No captures of this page yet"
        static let noLook = "No saved look of this page yet"
        static let image = "A picture from the web, not kept by Cicada"
        static let showAs = "Show as"
        static let saving = "Saving…"
        static let couldNotSave = "Couldn't change how this link shows."
        static let busy = "Sleep is updating your memory — try again in a moment."
        static let enlarge = "Enlarge"

        static func howItLooked(_ n: Int) -> String { n == 1 ? "How it looked · 1 capture" : "How it looked · \(n) captures" }
        static func read(_ day: String) -> String { "Read \(day)" }
        static func saved(_ day: String) -> String { "Saved \(day)" }
        static func captured(_ day: String) -> String { "Captured \(day)" }
        static func savedToLooks(_ day: String) -> String { "Saved to Looks \(day)" }
        static func nearest(_ head: String, asked: String) -> String { "\(head) · nearest to \(asked)" }

        static func viewName(_ view: LinkViewKind) -> String {
            switch view {
            case .link: "Link"
            case .raw: "Address"
            case .mention: "Mention"
            case .bookmark: "Bookmark"
            case .screenshot, .embed: "Screenshot"
            case .captures: "Captures"
            case .look: "Look"
            }
        }

        /// The edit's reason — the commit message the page's history shows.
        static func reason(_ view: LinkViewKind) -> String { "Shown as \(article(view)) \(viewName(view).lowercased())." }
        /// The switcher's confirmation line.
        static func savedAs(_ view: LinkViewKind) -> String { "Saved · shown as \(article(view)) \(viewName(view).lowercased())" }

        private static func article(_ view: LinkViewKind) -> String {
            switch view {
            case .captures: "its"
            default: "a"
            }
        }
    }
}
