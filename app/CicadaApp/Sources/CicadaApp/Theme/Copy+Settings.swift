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
}
