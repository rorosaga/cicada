import Foundation

/// G230 — repositories on the graph: connecting GitHub, the Sources panel, a repository page's card and a project's
/// repositories. Plain words; GitHub is named because it is the source the person connects, never as the one doing a
/// job of Cicada's.
extension Copy {
    enum GitHub {
        // Connecting (owner 2026-11-03: "cant we just do oauth? like a connect?").
        static let connect = "Connect GitHub"
        static let connectHelp = "Shows a code to enter on GitHub. Nothing to make or paste."
        static let reads = "Read-only: your repositories, each with its README, and the ones you starred."
        static let notSetUp = "Connecting with GitHub isn't set up in this build yet."
        static let useToken = "Use a token instead"
        static let hideToken = "Hide the token field"
        static let enterCode = "Enter this code on GitHub"
        static let openGitHub = "Open GitHub"
        static let copyCode = "Copy code"
        static let copied = "Copied"
        static let waiting = "Waiting for you to approve on GitHub…"
        static let cancel = "Cancel"
        static func expiresIn(_ minutes: Int) -> String {
            minutes <= 1 ? "The code works for about a minute more." : "The code works for \(minutes) more minutes."
        }
        static let connected = "Connected"
        static let signedOut = "GitHub signed Cicada out"
        static let signedOutWhy = "Its sign-in lapsed or was removed on GitHub. Connect again to keep your repositories "
            + "in sync; nothing in your memory changes."
        static let reconnect = "Reconnect"
        static let connectedByToken = "Connected with a token"
        static let installTitle = "One more step: install Cicada on your GitHub account"
        static let installWhy = "It lets Cicada read your own repositories — all of them, or the ones you pick — "
            + "read-only. Your stars already come in."
        static let install = "Install on GitHub"
        static let installedCheck = "I installed it"
        static let notInstalledYet = "GitHub doesn't show Cicada installed on your account yet."
        static let refresh = "Refresh"
        static let disconnect = "Disconnect"
        static let disconnected = "Disconnected. Cicada forgot its access; your repository pages stay."
        static let revokeOnGitHub = "To remove the approval on GitHub too, open your GitHub applications."
        static let openApplications = "Your GitHub applications"
        static let couldNotConnect = "Couldn't reach Cicada's backend to connect. Try again in a moment."

        // The Sources panel.
        static let couldNotRead = "Couldn't read your repositories right now."
        static let yoursTitle = "Your repositories"
        static let yoursIntro = "Each has its page, made on sync."
        static let yoursEmpty = "Connect GitHub above to bring in your repositories, each as a page."
        static let starredTitle = "Starred"
        static func starredCount(_ n: Int) -> String {
            n == 1 ? "1 starred repository, kept as a page." : "\(UsageFormat.count(n)) starred repositories, kept as pages."
        }
        static let open = "Open"
        static func inProject(_ name: String) -> String { "In \(name)" }
        static func moreProjects(_ n: Int) -> String { "+\(n)" }

        // A repository's projects, from either page (owner 2026-11-03: "a project might reference several repos").
        static let projectsTitle = "Projects"
        static let linkToProject = "Link to a project"
        static let linkToProjectHelp = "Say which of your projects this repository is part of."
        static func suggested(_ name: String) -> String { "\(name) — has its name" }
        static func sameCheckout(_ name: String) -> String { "\(name) — its checkout" }
        static let newProject = "New project from this repository"
        static let unlink = "Unlink"
        static func linked(_ name: String) -> String { "Linked to \(name)." }
        static func unlinked(_ name: String) -> String { "Unlinked from \(name). Nothing links it back on its own." }
        static func started(_ name: String) -> String { "Started your project \(name)." }
        static let failed = "Couldn't do that right now. Try again in a moment."
        static let byCheckout = "Linked by the checkout you work in"
        static let byAgent = "Linked by an agent"
        static let repositoriesTitle = "Repositories"
        static let repositoriesEmpty = "No repository linked yet."
        static let linkRepository = "Link a repository"
        static let linkRepositoryHelp = "Add one of your repositories to this project."

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
        static let yours = "Your repository"
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
