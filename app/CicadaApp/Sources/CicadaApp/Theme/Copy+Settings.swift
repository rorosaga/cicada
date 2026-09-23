import Foundation

/// Settings v3 and recommended skills (G139, G138). An extension so this
/// track's strings stay out of `Copy.swift`'s busy tail (R-O30); the two
/// `Copy` rules still hold — pointers are built from their parts, subtitles
/// are one sentence of at most 60 characters that never repeat their title.
extension Copy {
    // MARK: Groups (spec decision 17)
    static let groupCicada = "Cicada"
    static let groupCustomize = "Customize"
    static let groupEnginesAndKeys = "Engines & keys"

    // MARK: General
    static let appearance = "Appearance"
    static let appearanceSystem = "System"
    static let appearanceLight = "Light"
    static let appearanceDark = "Dark"
    static let textSize = "Text size"
    static let textSizeDetail = "⌘+ and ⌘− do the same from any page."
    static let actualSize = "Actual size"
    static let setup = "Setup"
    static let runSetupAgain = "Run setup again"
    static let runSetupDetail = "Walk through the first steps for this memory again."

    // MARK: Engines (A3, R-O8)
    static let engines = "Engines"
    static let enginesSubtitle = "Which model does Cicada's thinking."
    static let settingsEngines = "\(settings) → \(engines)"
    static let enginesChooseGroup = "Engine"
    /// The heading over the one switch that only matters on the API key card.
    static let apiKeyGroup = "API key"
    /// Was "Use for Sleep" on the Claude plan card — same pref, same endpoint.
    /// Not "Auto may use my Claude plan" (A3's first wording): Auto always
    /// tries the plan first, so the switch only ever changes the API key card
    /// (`engine_select.resolve_llm_mode`; G139 final review).
    static let useClaudePlanWhenIStart = "Use my Claude plan when I start a cycle"
    static let askGroup = "Ask"
    static let askTitle = "Ask"
    static let askFollowsEngine = "Answers your questions with the same engine as a cycle you start."

    // MARK: Sleep (R-O10)
    static let runsGroup = "Runs"
    static let runsTitle = "Runs"
    static let runsAt = "At"
    static let runsEvery = "Every"
    static let sleepEngineGroup = "Engine"
    static let sleepEngineRowTitle = "Engine"
    static let whenYouStart = "When you start one"
    static let onTheSchedule = "On the schedule"
    static let changeInEngines = "Change in Engines"

    // MARK: Customize (A1, R-O11)
    static let remoteSubtitle = "Let AI apps outside this Mac use your memory."
    static let settingsFromAnywhere = "\(settings) → \(fromAnywhere)"
    static let agentsInstallGroup = "One-time install"
    static let agentsInstallTitle = "Install Cicada on this Mac"
    static let agentsInstallDetail = "Sets up Python, the background service and the nightly schedule. Skip it if you've done it."
    static func agentsHomeCaption(_ home: String) -> String {
        "The commands below use \(home). Change it if your copy of Cicada lives somewhere else."
    }
    static let agentsOnThisMacGroup = "Agents on this Mac"
    static let agentsCloudTitle = "claude.ai, ChatGPT and your phone"
    static let agentsCloudDetail = "Cloud apps can't start a program on your Mac, so they reach Cicada through a link. You can also bring web chats in from the Feed."

    // MARK: Search (design §2.4)
    static let searchSettings = "Search settings"
    static func noSettingsMatch(_ query: String) -> String { "No settings match \u{201C}\(query)\u{201D}" }
    static func resultsFor(_ query: String) -> String { "Results for \u{201C}\(query)\u{201D}" }
    static func settingsCount(_ n: Int) -> String { n == 1 ? "1 setting" : "\(UsageFormat.count(n)) settings" }
    static func matchingSettings(_ n: Int) -> String { n == 1 ? "1 matching setting" : "\(UsageFormat.count(n)) matching settings" }
    /// Index titles for rows whose on-page words live inside another track's
    /// view (Track R's From anywhere, Track E's chooser) — the same words the
    /// page shows, so a result reads like the row it lands on.
    static let remoteReachTitle = "How apps reach this Mac"
    static let remoteNewConnectorTitle = "New connector"
    static let engineModelTitle = "Model"
    static let enginePreviewTitle = "What runs"
    /// A result's live value for a Plans & keys row — the state, never the
    /// account line (an email is not something to show beside a search hit).
    static let settingsConnected = "Connected"
    static let settingsNotConnected = "Not connected"
    static let settingsNotInstalled = "Not installed"

    // MARK: You
    static let youSection = "You"
    static let youSubtitle = "Who this memory belongs to."
    static let ownerNameTitle = "Your name"
    static let ownerNameBlank = "Your name can't be empty."
    static let ownerHandleTitle = "GitHub handle"
    static let ownerHandleDetail = "Shows your picture next to what you wrote."
    static let ownerEmailTitle = "Email"
    static let ownerPageTitle = "Your page"
    static let showOnGraph = "Show on graph"

    // MARK: Privacy & data
    static let privacyAndData = "Privacy & data"
    static let privacySubtitle = "What stays on this Mac, and how to take it with you."
    static let settingsPrivacy = "\(settings) → \(privacyAndData)"
    static let memoryLocationTitle = "Where your memory lives"
    static let showInFinder = "Show in Finder"
    static let banksTitle = "Memory banks"
    static let banksDetail = "Each bank is its own memory, with its own history. Switch or copy one from the Graph page."
    static let bankExportTitle = "Export a bank"
    static let bankExportDetail = "A zip of the bank's pages and full history. You choose where it goes."
    static let bankDeleteTitle = "Delete a bank"
    static let bankDeleteDetail = "The bank you're using, and the one that is your memory folder itself, can't be deleted here."
    static func bankDeleteSheetBody(_ name: String) -> String {
        "\u{201C}\(name)\u{201D} moves to the .trash folder inside your memory folder. Nothing is erased yet — you can move it back by hand."
    }
    static func bankDeleteTypeToConfirm(_ name: String) -> String { "Type \(name) to confirm" }
    static let telemetryTitle = "Usage ledger"
    static let telemetryOn = "On — ids and counts only, never your words."
    static let telemetryOff = "Off."
    static let telemetryHow = "Turn it off with CICADA_TELEMETRY=off in api/.env."
    static let reachingTheInternet = "Reaching the internet"
    static let outboundConnectorsTitle = "Nightly connector check"
    static let outboundConnectorsDetail = "Checks your connected apps for new saves while Sleep runs."
    static let outboundFeedsTitle = "Feeds and calendars"
    static let outboundFeedsDetail = "Checks your RSS feeds and calendar links."
    static let outboundLogosTitle = "Logos"
    static let outboundLogosDetail = "Fetches a logo for a page that names a website."
    static let credentialsTitle = "API keys"
    static let credentialsDetail = "Stored in ~/.cicada/secrets.env, readable only by you."
    static let removeAllKeys = "Remove all keys…"
    static let remoteAccessTitle = "Access from other apps"
    static let transcriptsTitle = "Agent conversations"
    static let transcriptsFact = "Cicada reads a finished turn once to capture it, and never again."
    static let bankActive = "Active"
    static func bankCounts(entities: Int, episodes: Int) -> String {
        "\(UsageFormat.count(entities)) \(entities == 1 ? "entity" : "entities") · \(UsageFormat.count(episodes)) \(episodes == 1 ? "episode" : "episodes")"
    }
    static let exportMenu = "Export…"
    static func exportingBank(_ name: String) -> String { "Exporting \(name)…" }
    static func exportedBank(_ name: String) -> String { "Exported \(name)." }
    static let deleteMenu = "Delete…"
    static func bankDeleteSheetTitle(_ name: String) -> String { "Delete \u{201C}\(name)\u{201D}?" }
    static let cancelAction = "Cancel"
    static let deleteAction = "Delete"
    /// A gate's value; `—` until `/status` says (a value, never a guess).
    static let gateOn = "On"
    static let gateOff = "Off"
    static let notKnownYet = "—"
    static func remoteOn(_ live: Int) -> String {
        "On · \(UsageFormat.count(live)) \(live == 1 ? "connection" : "connections")"
    }
    static let remoteOff = "Off"

    // MARK: Memory
    static let memorySection = "Memory"
    static let memorySubtitle = "How Cicada finds and tidies what it knows."
    static let searchIndexTitle = "Search index"
    static let rebuildNow = "Rebuild now"
    static let enrichLinksTitle = "Fetch link previews"
    static let enrichLinksDetail = "Reads each saved link's page — 4 seconds at most, never behind a login — and writes a short description with your engine."
    static let fetchNow = "Fetch now"
    static let sleepIsRunning = "Sleep is running — try again when it finishes."
    static let alreadyRunning = "Already running — try again when it finishes."

    // MARK: Advanced
    static let advanced = "Advanced"
    static let advancedSubtitle = "The backend, paths and environment switches."
    static let backendTitle = "Backend"
    static let mcpCommandTitle = "MCP server"
    static let mcpCommandDetail = "The command every agent on this Mac runs to reach Cicada."
    static let apiTokenTitle = "API token"
    static let apiTokenDetail = "Kept in ~/.cicada/api_token. It is never shown here."
    static let apiTokenOverridden = "Replaced by CICADA_API_TOKEN in the environment."
    static let envOverridesTitle = "Set in api/.env or the environment"
    static let envOverridesNone = "None — Cicada is using its own settings."
    static let backendNotAnswering = "Not answering."
    static func backendLine(version: String?, entities: Int?, episodes: Int?) -> String {
        var parts = ["Connected"]
        if let version { parts.append("version \(version)") }
        if let entities { parts.append("\(UsageFormat.count(entities)) \(entities == 1 ? "entity" : "entities")") }
        if let episodes { parts.append("\(UsageFormat.count(episodes)) \(episodes == 1 ? "episode" : "episodes")") }
        return parts.joined(separator: " · ")
    }
}
