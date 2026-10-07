import Foundation

/// The Graph page's words (Direction D, DS-3a), in their own file — the `Copy+Inbox.swift` precedent, so
/// tracks appending to `Copy.swift` never edit the same lines. Each later task adds its own
/// `extension Copy.Graph` block below. Plain words for a person who has never heard "node" or "claim".
extension Copy {
    enum Graph {
        // The floating group (R-DG3)
        static let controlsLabel = "Graph controls"
        static let all = "All"
        static let external = "External"
        static let legend = "Legend"
        static let legendFiltered = "Legend · filtered"
        static let legendHelp = "Legend and filters"
        static let zoomIn = "Zoom in"
        static let zoomOut = "Zoom out"
        static let fit = "Fit the whole graph"
        static let panOffHelp = "Pan mode — drag anywhere to move the graph (or hold Shift)"
        static let panOnHelp = "Pan mode is on — click to return to normal (or just hold Shift)"

        // The Legend panel (R-DG4)
        static let whoseBeliefs = "Whose beliefs"
        static let contextHeading = "Context · edge colour"
        static let typeHeading = "Type · node colour"
        static let statusHeading = "Status"
        static let minConfidence = "Minimum confidence"
        static let anyConfidence = "Any"
        static func orMore(_ n: Int) -> String { "\(n) or more" }
        static let showAll = "Show all"
        static let showLogos = "Show logos"
        static let showLogosHelp = "Show entity logos on graph nodes"
        static let dashed = "dashed"
        static let hiddenByDefault = "hidden by default"
        static let keyBigger = "Bigger means more confident"
        static let keyDashed = "Dashed means fading"
        static let keyPulse = "Amber ring: a question waits"

        // Find on the canvas (R-DG5)
        static let findOnCanvas = "Find on the canvas"
        static let closeFind = "Close (Esc)"
        static let noNodeMatches = "No node matches"

        // The Graph's `?` (R-DG6)
        static let helpTitle = "How the graph works"
    }
}

// Task 3 — the entity column's header and tabs (R-DG14 … R-DG16)
extension Copy.Graph {
    static func confidenceOutOf100(_ n: Int) -> String { "Confidence \(n) out of 100" }
    static let fadingReason = " · not mentioned lately, so it is fading"
    /// G194 A2 — an old page's header and its `.help`; the month and day come from `RelativeDay`.
    static func lastMentioned(_ month: String) -> String { "last mentioned \(month)" }
    static func lastMentionedHelp(_ day: String) -> String { " · last mentioned \(day)" }
    /// G117 — the owner's own page.
    static func ownerName(_ name: String) -> String { "\(name) (you)" }
    static func backTo(_ name: String?) -> String { name.map { "‹ Back to \($0)" } ?? "‹ Back" }
    static func backHelp(_ name: String?) -> String { (name.map { "Back to \($0)" } ?? "Back") + " (⌘[)" }
    static func closeHelp(_ name: String) -> String { "Close \(name) (Esc)" }
    static let tabContent = "Content"
    static let tabPerspectives = "Perspectives"
    static let tabHistory = "History"
    static let tabTimeline = "Timeline"
}

// Task 4 — Content (R-DG18 … R-DG22)
extension Copy.Graph {
    static let rendered = "Rendered"
    static let source = "Source"
    static let copyMarkdown = "Copy markdown"
    static let copyPath = "Copy path"
    static let folder = "Folder"
    static let folderNotFound = "This folder isn't on this Mac."
    static let folderNotAllowed = "Cicada isn't allowed to read this folder. Allow it in System Settings → Privacy & Security → Files and Folders → Cicada, then open this page again."
    static let folderEmpty = "Empty folder."
    static let folderTruncated = "…listing truncated"
    static let repository = "Repository"
    static let repositories = "Repositories"
    static func changedFiles(_ n: Int) -> String { "\(UsageFormat.count(n)) changed \(n == 1 ? "file" : "files")" }
    static func ahead(_ n: Int) -> String { "\(UsageFormat.count(n)) ahead" }
    static func behind(_ n: Int) -> String { "\(UsageFormat.count(n)) behind" }

    // Look it up at (G61)
    static let forAnyFact = "For any fact"
    static func forFact(_ fact: String) -> String { "For \(fact)" }
    static let publicPage = "Public page"
    static let needsSignIn = "Needs sign-in"
    static let fileOnThisMac = "A file on this Mac"
    static let anApp = "An app"
    static let addedByYou = "Added by you"
    static let foundByCicada = "Found by Cicada"
    static let foundByAnAgent = "Found by an agent"
    static func addedBy(_ app: String) -> String { "Added by \(app)" }
    static func addedByRaw(_ id: String) -> String { "Added by \(id)" }
    static let onlyYouKnow = "Only you know this"
    static let youChoseThis = "You chose to use this"
    static let addSourcePlaceholder = "Add a URL, a path, or a note…"
    static let add = "Add"
    static func openSource(_ ref: String) -> String { "Open \(ref)" }
    static let removeSource = "Remove source"
    // Sources as a living set (G61 S3-a)
    static let sourcesAnything = "Anything"
    static let sourcesOfficialSite = "Official site"
    static let sourceMenu = "Manage this source"
    static let siteConfirmed = "Confirmed"
    static func siteConfirmedOn(_ day: String) -> String { "Confirmed \(day)" }
    static let siteProposed = "Proposed, not confirmed yet"
    static let siteReadNotConfirmed = "Read, but not confirmed yet"
    static let useThisSite = "Use this site"
    static let useThisSiteHelpNoMark = "Trust this as the page's own site"
    static let useThisSiteHelp = "Trust this as the page's own site and draw its mark from it"
    static let sourcePlaceholderSite = "The official website"
    static let sourcePlaceholderProfile = "A profile page: LinkedIn, GitHub, your site…"
    static let useThisSource = "Use this source"
    static let changeFact = "Change what it is for…"
    static let readAsPublic = "Anyone can open it"
    static let readAsSignedIn = "Needs sign-in"
    static let linkToPage = "Link to a page…"
    static let unlinkPage = "Unlink page"
    static let openLinkedPage = "Open page ›"
    static func openLinkedPageHelp(_ name: String) -> String { "Open \(name), the page that knows more about this source" }
    static let linkSearchPrompt = "Find a page"
    static let linkNoMatch = "No page by that name."
    static let factPrompt = "What is it for? (works at, lives in …)"
    static let apply = "Apply"
    static let cancel = "Cancel"
    static let sourceRemoved = "Removed. Cicada won't suggest it again."
    static let sourceSaveFailed = "That change wasn't saved. Try again."
    static let sourceBackendDown = "Cicada can't reach its backend, so that change wasn't saved."
    static let openInInbox = "Open in Inbox"
    static let openInInboxHelp = "Open this question in the Inbox (⌘6)"

    // Details
    static let details = "Details"
    /// A whole word run, not an interpolation: Task 5 puts `Views/Graph/` under `CountLiteralLintTests`.
    static let detailsSummary = "· tags, related, dates, how it fades"
    static let tags = "Tags"
    static let related = "Related"
    static let firstNoted = "First noted"
    static let lastMentioned = "Last mentioned"
    static let fades = "Fades"
    static let fadesHelp = "How fast this fades when it stops coming up — the more weeks it came up in, the slower"
    static let fadesNotChanged = "Couldn't change how this fades — try again"

    // Beliefs
    static let beliefTimelineHelp = "How this belief changed over time"
    static func writtenBy(_ author: String, confidence: Double) -> String {
        "\(author) at \(String(format: "%.2f", confidence))"
    }
    static func trueSince(_ day: String) -> String { "True since \(day)" }
    static func notedOn(_ day: String) -> String { "; noted \(day)" }
}

// Task 5 — Perspectives, History, Timeline (R-DG22 … R-DG24)
extension Copy.Graph {
    static let noBeliefsYet = "No beliefs are recorded on this page yet."
    static func observersDisagree(_ predicate: String) -> String { "Observers disagree on \(predicate)" }
    static let readingHistory = "Reading git history…"
    static let noCommitsTitle = "No commits touch this page yet"
    static let noCommitsDetail = "It appears here once a Sleep cycle writes to it."
    static let historyFailed = "Couldn't load history"
    static let retry = "Retry"
    static let showInConversation = "Show in conversation"
    static let showInConversationHelp = "Open the conversation this change came from"
    static let whatChanged = "What changed"
    static let whatChangedHelp = "Show what changed in this commit"
    static let contestedBeliefs = "Contested beliefs"
    static let thisBelief = "This belief"
    static let noContested = "No contested beliefs yet."
    static let noContestedDetail = "A belief becomes contested when what Cicada holds about it changes over time."
    static func beliefsSince(_ n: Int, _ day: String?) -> String {
        let count = "\(UsageFormat.count(n)) \(n == 1 ? "belief" : "beliefs")"
        return day.map { "\(count) since \($0)" } ?? count
    }
    static let supersededByNewer = "Superseded by a newer belief"
}
