import Foundation

extension Copy {
    /// G245 (plan 5) — the words of a notes page laid out the way Notes lays its own (`NoteGroups`): its date groups, the
    /// folder tree's lines, and the one quiet line when pins could not be read.
    enum NoteGroups {
        static let today = "Today"
        static let yesterday = "Yesterday"
        static let previous7 = "Previous 7 Days"
        static let previous30 = "Previous 30 Days"
        static let earlier = "Earlier"

        /// A folder's count: how many notes it holds with everything under it.
        static func folderCount(_ n: Int) -> String { n == 1 ? "1" : UsageFormat.count(n) }
        static func folderHelp(_ name: String, notes: Int) -> String {
            "Open \(name), \(notes) \(notes == 1 ? "note" : "notes")"
        }
        /// Pins are kept where Cicada can only see them with Full Disk Access; one line says so, with the button that
        /// opens the setting (never a prompt).
        static let pinsUnread = "Pins are not shown: Notes keeps them where Cicada needs Full Disk Access to see."
        static let openSetting = "Open the setting"
        static let pinsHelp = "Notes does not share which notes are pinned. Cicada can read that only with Full Disk Access, which it never asks for on its own."
        static let emptyFolder = "Nothing in this folder yet."
        /// A Notion workspace's tree.
        static let unfiled = "Unfiled"
        static let notionPages = "Pages"
    }
}
