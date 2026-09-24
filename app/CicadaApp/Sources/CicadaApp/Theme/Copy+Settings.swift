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
    // Round-4 D4 (G144) — Settings → General → Scene: Home's painting by the clock, never by location.
    static let scene = "Scene"
    static let sceneDetail = "Home's painting follows sunrise and sunset in your Mac's time zone. No location is used."
    static let sceneAutomatic = "Automatic"
    static let sceneAlwaysDay = "Always day"
    static let sceneAlwaysNight = "Always night"
    static let textSize = "Text size"
    static let textSizeDetail = "⌘+ and ⌘− do the same from any page."
    static let actualSize = "Actual size"
    static let setup = "Setup"
    static let runSetupAgain = "Run setup again"
    static let runSetupDetail = "Walk through the first steps for this memory again."

    // MARK: General → In the background (round-4 D3, G143)
    // No price, token or cost words here (the 2026-09-03 ruling, DR-59).
    static let backgroundGroup = "In the background"
    static let openAtLogin = "Open Cicada at login"
    static let loginItemOff = "Cicada opens only when you open it."
    static let loginItemOn = "Cicada opens when you log in, and keeps working with its window closed."
    static let loginItemNeedsApproval = "Almost there — allow Cicada in System Settings → General → Login Items."
    /// R-FA7 — the person asked, macOS did not keep it: an ad-hoc-signed build may never be enabled, and the row
    /// must never pretend it was (D3).
    static let loginItemNotKept = "macOS isn't opening Cicada at login. If you didn't turn it off there, "
        + "this copy of Cicada may need adding by hand in Login Items."
    static func loginItemFailed(_ why: String) -> String { "macOS didn't accept this: \(why)" }
    static let openLoginItems = "Open Login Items"
    static let openLoginItemsHelp = "Opens System Settings → General → Login Items"
    static let keepMemoryWorking = "Keep memory working when Cicada is closed"
    /// R-FA9 — "On" means launchd holds the agent (loaded, KeepAlive on), which is exactly what the sentence says.
    static func backgroundDetail(_ state: BackendAgentState) -> String {
        switch state {
        case .running: "On — Cicada's memory keeps working in the background."
        case .stopped: "Installed, but not running. Install again to restart it."
        case .missing: "Off — memory only updates while Cicada is open."
        case .checking: "Checking…"
        case .installing: "Installing…"
        case .unknown: "Couldn't check the background service."
        case .failed(let why): why
        }
    }
    static let backgroundInstall = "Install"
    static let backgroundInstallHelp = "Runs the command below from your Cicada folder"
    static let backgroundNoPython = "Cicada's Python environment is missing — run the one-time install under Agents first."
    static let backgroundLaunchdRefused = "macOS wouldn't start the background service. The log in your Cicada folder says why."
    static let backgroundRefused = "Cicada only runs its own install script."
    /// Never `Copy.intakeFailed` ("The import didn't finish.") — that is `AgentConnect`'s import sentence.
    static let backgroundInstallFailed = "Cicada couldn't set up the background service. Try again in a moment."

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
    /// Not "in api/.env" (final review): `telemetry.enabled()` reads only the
    /// process environment, pydantic's env_file never reaches `os.environ`, and
    /// the LaunchAgent does not load api/.env — that instruction kept recording.
    static let telemetryHow = "To turn it off, set CICADA_TELEMETRY=off in the backend's environment (its LaunchAgent) and restart it."
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
    /// A privacy promise, and a search result's detail, so it must be true
    /// (final review): each Stop re-reads the whole transcript
    /// (`transcript_capture.capture_transcript`), so "once, never again" was false.
    static let transcriptsFact = "When an agent finishes a reply, Cicada reads that conversation to keep your words and the agent's final answer. It never opens those files for anything else."
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

    // MARK: Skills (G138)
    static let skills = "Skills"
    static let skillsSubtitle = "Abilities your agents can add, with your consent."
    static let settingsSkills = "\(settings) → \(skills)"
    static let cicadasOwnGroup = "Cicada's own"
    static let recommendedGroup = "Recommended"
    static func reviewedOn(_ date: String) -> String { "Reviewed \(date)" }
    static let installedGroup = "Already installed"
    static let skillsFootnote = "Cicada never runs a skill itself. Installing one runs your agent's own installer, after you say yes."
    static let agentsSkillTitle = "Cicada's skill for your agents"
    static let agentsSkillDetail = "Tells an agent when to look things up in Cicada and when to save."
    static let openSkills = "Open Skills"
    static let install = "Install"
    static let update = "Update"
    static let remove = "Remove"
    static let changedByYou = "Changed by you — Cicada won't touch it."
    static let installedByHand = "Installed (not by Cicada)"
    static let differentCopy = "A different copy is installed — Cicada won't touch it."
    static let sourceMissing = "Cicada's skill file isn't on this Mac."
    static let whatItNeeds = "What it needs"
    static let showExactCommand = "Show the exact command"
    static let copyCommand = "Copy command"
    static let understandThirdParty = "I understand this installs someone else's code on this Mac."
    static func installIn(_ agent: String) -> String { "Install in \(agent)…" }
    static func installTitle(_ skill: String, _ agent: String) -> String { "Install \(skill) in \(agent)?" }
    static func installLead(_ agent: String) -> String {
        "This runs \(agent)'s own installer on this Mac. Cicada never runs the skill itself."
    }
    static let installing = "Installing… this can take a minute."
    static func installedStartNew(_ agent: String) -> String { "Installed. Start a new \(agent) session to use it." }
    static let installDidntFinish = "It didn't finish. Here's what the installer said:"
    static func agentMissing(_ program: String) -> String {
        program == "npx"
            ? "This needs Node.js (for npx). Install it from nodejs.org, then try again — or copy the command."
            : "\(program) isn't installed on this Mac. Copy the command to run it where it is."
    }
    static let connectInYourAgent = "Connect it in your agent — it will ask you to sign in."
}
