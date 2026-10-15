import Foundation

/// The Skills page and onboarding's skills step (owner 2026-10-15) — DR-59: sentence case, plain verbs, no "!", no
/// jargon in the main view (commits, folders and receipts live behind Details). Provider-neutral (owner 2026-09-30):
/// an agent is named only where it is the person's own (which agents have a skill), never as the one doing Cicada's job.
extension Copy {
    enum Skills {
        static let page = "Skills"
        static let discover = "Discover"
        static let drafts = "Drafts"
        static let skillColumn = "Skill"
        static let agentsColumn = "Agents"
        static let statusColumn = "Status"
        static let noAgents = "None"
        static let local = "Local"
        static let notChecked = "Not checked"
        static let addHelp = "Add a skill from a GitHub link, owner/repo or an npx skills add line (⌘N)"
        static let closeHelp = "Close (Esc)"
        static let versionLabel = "Version"
        /// The owner (2026-10-15): the check runs from Cicada, so it says so.
        static let checkedForCicada = "Checked for Cicada"
        static let otherAppsDiffer = "An agent running in another app may have different permissions."
        static let instructions = "Instructions"
        static let refreshInstructions = "Refresh instructions"
        static let removeEllipsis = "Remove…"
        static func removeTitle(_ name: String) -> String { "Remove \(name) from every agent?" }
        static func olderLine(tool: String?, text: String?) -> String {
            if let tool, let text { return "The tool is \(tool) but its instructions are from \(text)." }
            return "Its instructions are older than the tool it uses."
        }
        static func changesTitle(from: String?, to: String?) -> String {
            switch (from, to) {
            case let (from?, to?): "\(from) → \(to)"
            case let (nil, to?): to
            default: whatChanged
            }
        }
        static func eyebrowCount(_ n: Int) -> String { n == 1 ? "1 installed" : "\(UsageFormat.count(n)) installed" }
        static let check = "Check for updates"
        static let checking = "Checking…"
        static let checkHelp = "Ask each skill's source whether there's a newer version. Nothing installs."
        static let updateAll = "Update all"
        static func updateAllHelp(_ n: Int) -> String { n == 1 ? "Install the 1 update found" : "Install the \(n) updates found" }
        static let add = "Add a skill"
        static let loading = "Looking at your agents' skills…"
        static let loadFailedTitle = "Couldn't read your skills"
        static let unreachable = "Cicada's backend isn't answering. Open Cicada and try again."
        static let somethingWrong = "Something went wrong. Nothing was changed."
        static func checkedAgo(_ text: String) -> String { "Last checked \(text)" }
        static let neverChecked = "Not checked for updates yet"

        // Sections
        static let waiting = "Your agents asked"
        static let installed = "Installed"
        static let suggested = "Suggested"
        static let made = "Made by your agents"
        static let emptyInstalledTitle = "No skills yet"
        static let emptyInstalledMessage = "Skills teach your agents to do something new. Add one below, or start with "
            + "a suggestion."

        // A row
        static let updateAvailable = "Update available"
        static let upToDate = "Up to date"
        static let update = "Update"
        static let whatChanged = "What changed"
        static let releaseNotes = "Release notes"
        static let olderText = "Its instructions are older than the tool it uses"
        static let refresh = "Refresh"
        static let refreshHelp = "Take the instructions from the tool installed now. The old ones are kept."
        static let toolMissing = "The tool it uses isn't installed"
        static let details = "Details"
        static let hideDetails = "Hide details"
        static let remove = "Remove"
        static let removeHelp = "Remove it from every agent. Anything Cicada didn't write is kept aside."
        static let madeByCicada = "Made by Cicada"
        static let onThisMac = "On this Mac"
        static func agentHelp(_ agent: String, on: Bool) -> String {
            on ? "Take it away from \(agent)" : "Give it to \(agent)"
        }
        static let foldersLabel = "Folders"
        static let commitLabel = "Commit"
        static let installedLabel = "Installed"
        static let licenceLabel = "Licence"
        static let linkedFolder = "linked"
        static let byCicada = "written by Cicada"
        static let toolLabel = "Tool"
        static func toolLine(_ version: String?, from: String?) -> String {
            var parts = [version.map { "v\($0)" } ?? "not installed"]
            if let from { parts.append("from \(from)") }
            return parts.joined(separator: " · ")
        }

        // Requests
        static func asked(_ who: String, _ what: String) -> String { "\(who) wants to \(what)" }
        static func askInstall(_ source: String) -> String { "add \(source)" }
        static func askUpdate(_ name: String) -> String { "update \(name)" }
        static func askOn(_ name: String, _ agent: String) -> String { "give \(name) to \(agent)" }
        static func askOff(_ name: String, _ agent: String) -> String { "take \(name) away from \(agent)" }
        static func askRefresh(_ name: String) -> String { "refresh \(name)'s instructions" }
        static let review = "Review"
        static let approve = "Do it"
        static let dismiss = "Dismiss"

        // Suggested
        static let install = "Install"
        static let installing = "Installing…"
        static let needsUv = "Needs uv, a small installer for command-line tools."
        static let getUv = "How to install uv"
        static let setUpInAgent = "Your agent sets this one up"
        static let copyForAgent = "Copy for your agent"
        static let copied = "Copied"

        // Made by your agents
        static func madeBy(_ agent: String) -> String { "Drafted by \(agent)" }
        static let held = "Waiting for you"
        static let publish = "Publish"
        static let publishHelp = "Give it to the agents you pick"
        static let discard = "Discard"
        static let readIt = "Read it"
        static let noticedTitle = "Noticed by Sleep"
        static let noticedLine = "Habits Sleep noticed in your conversations. Turning one into a skill comes later."
        static func noticedState(_ state: String, _ n: Int) -> String {
            state == "held" ? "Seen in one conversation so far" : (n == 1 ? "Seen in 1 conversation" : "Seen in \(n) conversations")
        }
        static let madeEmpty = "When an agent writes a skill for something you do often, it waits here until you publish it."

        // Add a skill
        static let addTitle = "Add a skill"
        static let addLead = "Paste a GitHub link, owner/repo, or an npx skills add line. Cicada shows you what's "
            + "inside before anything installs."
        static let addPlaceholder = "Add from GitHub, or paste npx skills add…"
        static let look = "Look"
        static let looking = "Looking…"
        static let chooseOne = "This holds several skills. Pick one:"
        static func fromRepo(_ repo: String, _ commit: String) -> String { "From \(repo) at \(commit)" }
        static let files = "Files"
        static let scriptsWarning = "It includes scripts your agents can run on this Mac. Read them before you install."
        static let giveTo = "Give it to"
        static let installPinned = "Install"
        static let installPinnedHelp = "Installs exactly what is shown, fixed to this version."
        static let cancel = "Cancel"
        static let close = "Close"
        static let cutNote = "Shown in part; the whole file installs."

        // Jobs
        static func jobRunning(_ label: String) -> String { "Installing \(label)…" }
        static func jobFailed(_ message: String) -> String { message }

        // Onboarding's step
        static let onboardingTitle = "Give Cicada eyes and hands"
        static let onboardingLead = "Skills that let your agents look at websites and use the apps on this Mac. "
            + "Continue installs what's on."
        static let skip = "Skip"
        static let onboardingFoot = "You can change these on the Skills page."
        static let onboardingNoUv = "These need uv, a small installer for command-line tools. Install it, then "
            + "press Check again, or skip for now."
        static let checkAgain = "Check again"
        static let alreadyInstalled = "Installed"
        static let offByDefault = "Not tried yet"
    }
}
