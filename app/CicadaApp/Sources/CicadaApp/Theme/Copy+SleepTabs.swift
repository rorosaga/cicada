import Foundation

extension Copy {
    /// The Sleep redesign (2026-10-16) — the page's eyebrow and its four lists. Provider-neutral (owner, 2026-09-30):
    /// nothing here names who reads.
    enum SleepTabs {
        static let page = "Sleep"
        static let waiting = "Waiting"
        static let saved = "Saved"
        static let videos = "Videos"
        static let pastReads = "Past reads"
        static let tabsLabel = "Sleep's lists"
        /// The Saved tab's View menu: the Feed's sort and kind filter in one place (DR-38 — never a second tab row).
        static let view = "View"
        static let sortTitle = "Sort"
        static let kindTitle = "Show"
        static func waitingCount(_ n: Int) -> String { "\(UsageFormat.count(n)) waiting" }
        static let nothingWaiting = "nothing waiting"
        static func lastRead(_ ago: String) -> String { "last read \(ago)" }
        static let justNow = "just now"
        static func minutesAgo(_ n: Int) -> String { "\(UsageFormat.count(n)) min ago" }
        static func hoursAgo(_ n: Int) -> String { "\(UsageFormat.count(n)) h ago" }
        /// The Saved list's empty state (DESIGN §3.5): both doors, the room and ⌘N.
        static let savedEmpty = "Drop a file on the room, or press ⌘N."
    }

    /// ⌘ map A (owner, 2026-10-16) — the one-time line the first time ⌘4 lands on Skills.
    static let feedMovedHint = "The Feed is now part of Sleep (⌘5) → Saved."
    /// Where a saved item lives now, for the lines that used to say "the Feed".
    static let savedPlace = "Sleep › Saved"
}
