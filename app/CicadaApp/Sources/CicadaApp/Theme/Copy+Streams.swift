import Foundation

/// G245 (ruling 78) — the words of a source's streams: the definite word a check ends in (plan 3.3), the root card's
/// second line, and the one line a stream says when this Mac cannot read it yet. Few words, no provider named: the AI
/// the person uses is "your AI app" (provider-neutral copy, owner 2026-09-30).
extension Copy {
    enum Streams {
        /// The root's first tab: every source.
        static let all = "All"

        // The six words a check ends in, then the ones a stream rests in.
        static let read = "Read"
        static let signedOut = "Signed out"
        static let couldntRead = "Couldn't read"
        static let needsAccess = "Needs access"
        static let yourAIAppReadsNext = "Your AI app reads it next"
        static let notInstalled = "Not installed"
        static let notReadYet = "Not read yet"
        static let paused = "Paused"
        static let off = "Off"
        static let unavailable = "Unavailable"

        /// The root card's second line, after the streams: "3 folders".
        static func folders(_ n: Int) -> String {
            n == 1 ? "1 folder" : "\(UsageFormat.count(n)) folders"
        }

        // The root (plan 3.1): the header's one button, the one label, the one fix a needs-you card names.
        static let checkConnections = "Check connections"
        static let checkingConnections = "Checking…"
        static func checkedAgo(_ ago: String) -> String { "Checked \(ago)" }
        static let notConnected = "Not connected"
        static let connect = "Connect"
        static let giveAccess = "Give access"
        static let kindsLabel = "Kinds of source"
        static let readingSources = "Reading your sources"
        /// The Connect button's tooltip.
        static func connectHelp(_ name: String) -> String { "Connect \(name)" }

        /// The "Saves you make" row, when macOS has not been given Accessibility (ruling 77: never prompted for).
        static let accessibilityWhy = "Seeing a save needs Accessibility, which Cicada never asks for on its own."
        /// The "Saves you make" row, off because the person turned it off while the source itself is on.
        static let savesTurnedOff = "You turned this off, so saves you make here are not noticed."
        /// The row's hover: which browsers a save is seen in (the ones Cicada reads; others are named on the Browsers page).
        static func savesSeenIn(_ browsers: String) -> String { "Seen in \(browsers), on this Mac." }
        static let openAccessibility = "Open Accessibility settings"
        /// A reader that needs a permission the person can give from Settings.
        static let permissionWhy = "macOS has not given Cicada access to read it."
        static let openSetting = "Open the setting"

        /// A check in progress, and a check the backend could not be asked.
        static let checking = "Checking"
        static let checkFailed = "Couldn't ask Cicada's memory to check. Try again in a moment."
        /// The last result beside "Your AI app reads it next".
        static func lastResult(_ word: String) -> String { "last: \(word.lowercased())" }

        /// "Connect the AI you use": the fix a needs-you card names when no AI app on this Mac can read for it.
        static let openAgents = "Connect the AI you use"

        // A source's page (plan 3.2): the head's one quiet line, then the Reads block.
        static let reads = "Reads"
        static let checkNow = "Check now"
        static let checkNowHelp = "Ask every stream below how it is doing. Nothing is changed or posted."
        static let setUpBelow = "Set up below"
        static func readInBrowser(app: String?) -> String {
            "Read in your browser by \(app ?? "your AI app"), about once a day"
        }
        static let readOnThisMac = "Read on this Mac"
        static let readWithSignIn = "Read with your sign-in"
        static let noticedWhenYouSave = "Noticed when you save, on this Mac"

        /// A row's quiet line: how it is read, then how deep its items go.
        static let lineBrowser = "In your browser, by your AI app"
        static let lineApp = "On this Mac"
        static let lineAccount = "With your sign-in"
        static let lineClick = "When you save, on this Mac"
        /// G245 (plan 7.1 item 8) — the state of the piece in words, where it is not obvious: on, and Accessibility lets
        /// Cicada see the save, so each one asks why.
        static let lineClickAsks = "Asks why when you save, on this Mac"
        /// A connections stream's purpose, when its name does not say: they are kept outside memory, matched by name.
        static let connectionsFor = "Matched to people you already have pages for"
        static let depthIndex = "kept and findable"
        static let depthRead = "read by Sleep"

        /// The browser-reading facts: the head line's hover and the first-use sheet's, never a standing paragraph.
        static let whoseSession = "It uses your own sign-in, in your browser on this Mac. Cicada never sees your password and never opens the browser itself."
        static func whoSees(app: String?) -> String {
            "\(app ?? "Your AI app")'s company sees what it reads. No AI reads a saved item unless you mention it."
        }
        static let neverPosts = "Nothing is posted or changed on the site."
        static let howToStop = "To stop, turn the stream off here. What was kept stays until you remove it."
        /// A browser list's row hover: the newest are read, the rest come with the site's export (the window's drop).
        static let browserReach = "The newest are read. Older ones come with the site's export: drop it on the window. Unsaving on the site does not remove one here."

        // Items (plan 3.2 item 3).
        static let allFolders = "All folders"
        static let folders = "Folders"
        // How deep Cicada went on a kept item (G245 B3): nothing for `kept`, one quiet word or phrase for the rest.
        static let itemRead = "read"
        /// The person talked about it and an ask waits for their own AI app to read or watch it.
        static let itemAsked = "your AI app reads it next"
        static let itemWatched = "watched"
        static func posted(_ day: String) -> String { "posted \(day)" }
        static func kept(_ age: String) -> String { "kept \(age)" }
        static let savesYouMake = "Saves you make"
        static let couldntSwitch = "Couldn't change that. Try again in a moment."
        static let forgetKeptHelp = "People already updated keep what they gained."
        static let noItemsYet = "Nothing kept from this list yet."
        // LinkedIn's Connections (owner 2026-11-24): who the person connected with, newest first, by month.
        static let connectionsLabel = "Connections"
        static let connectionsNoDate = "No date"
        static func connectionsAround(_ when: String) -> String { "around \(when)" }
        static func connectionsWeekHelp(_ day: String) -> String { "LinkedIn said about when: around the week of \(day)." }
        static func connectionsMonthHelp(_ month: String) -> String { "LinkedIn said about when: some time in \(month)." }
        static func connectionsSearch(_ total: Int?) -> String {
            total.map { "Search \(UsageFormat.count($0)) connection\($0 == 1 ? "" : "s")" } ?? "Search connections"
        }
        static let connectionsOff = "Connections is off. Turn it on above and your AI app reads who you have connected with."
        static let connectionsWaiting = "Nothing read yet. Your AI app reads it on its next visit."
        static let connectionsFailed = "Couldn't read the kept connections. Try again in a moment."
        static let connectionsLoading = "Reading your connections"
        static let connectionsMatchHelp = "Open this person's page in your memory"
        static let connectionsPageChip = "Their page"
        static func connectionsOpenProfile(_ name: String) -> String { "Open \(name)'s LinkedIn profile" }
        static let allFoldersHelp = "Show only the items in one of the site's own folders"
    }
}
