import Foundation

/// G230 — repositories on the graph: the Sources panel and a repository page's card. Plain words; GitHub is named
/// because it is the source the person connected, never as the one doing a job of Cicada's.
extension Copy {
    enum GitHub {
        // The Sources panel.
        static let addTitle = "Add a repository"
        static let addIntro = "Paste a repository's link. Its page shows its name, link and a preview of its README. "
            + "A public one needs no connection."
        static let linkPrompt = "github.com/owner/name"
        static let add = "Add"
        static let addHelp = "Add this repository to your memory."
        static let notALink = "That isn't a GitHub repository link. Paste one like github.com/owner/name."
        static func added(_ name: String) -> String { "Added \(name)." }
        static func updated(_ name: String) -> String { "\(name) was already in your memory; its page is up to date." }
        static let failed = "Couldn't add that right now. Try again in a moment."
        static let couldNotRead = "Couldn't read your repositories right now."
        static let yoursTitle = "Your repositories"
        static let yoursIntro = "From your last sync. Each stays a suggestion until you add it as a project."
        static let yoursEmpty = "Connect GitHub above and sync to see the repositories you own here."
        static let starredTitle = "In your memory"
        static func starredCount(_ n: Int) -> String {
            n == 1 ? "1 repository page — starred or added." : "\(UsageFormat.count(n)) repository pages — starred or added."
        }
        static let inMemory = "In memory"
        /// One of the person's own repositories has one action (owner 2026-11-03: "i'd rather it said 'Add as a
        /// project'"): this, or `linkTo` when a project already has its name. `add` stays for anyone else's.
        static let addAsProject = "Add as a project"
        static let addAsProjectHelp = "Add this repository of yours as one of your projects, linked to it."
        static func linkTo(_ name: String) -> String { "Link to \(name)" }
        static func linkToHelp(_ name: String) -> String {
            "Your project \(name) has this repository's name. Link them, so the project page shows the repository."
        }
        static func yourProject(_ name: String) -> String { "Your project \(name)" }
        static func linked(_ name: String) -> String { "Linked to your project \(name)." }
        static func started(_ name: String) -> String { "Added \(name) as your project." }
        static func alreadyProject(_ name: String) -> String { "That repository is already your project \(name)." }

        // Flags, as `Tag`s.
        static let isPrivate = "Private"
        static let isArchived = "Archived"
        static let isFork = "Fork"
        static let isPublic = "Public"

        // A repository page's card.
        static let openOnGitHub = "Open on GitHub"
        static let readme = "README"
        static func starredOn(_ day: String) -> String { "You starred it \(day)" }
        static func unstarredOn(_ day: String) -> String { "No longer starred since \(day)" }
        static let youAdded = "You added it"
        static let readmeNone = "This repository has no README."
        static let readmeMissing = "The README hasn't been read yet. Cicada reads it when this page opens, while "
            + "previews from the web are allowed."
        static func readmeCut(_ chars: Int) -> String {
            "The preview stops at \(UsageFormat.count(chars)) characters; the rest is on GitHub."
        }
        static func readmeAsOf(_ day: String) -> String { "Read \(day)" }
        static func moreTopics(_ n: Int) -> String { "+\(n)" }
    }
}
