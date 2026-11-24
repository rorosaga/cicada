import Foundation

/// ROR-118 — the Sources page's kinds (its tabs, G245). Few words on purpose.
extension Copy {
    enum Shelf {
        static let conversations = "Conversations"
        static let documents = "Documents"
        static let events = "Events"
        static let work = "Work"
        static let saved = "Saved"
        static let media = "Media"
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
