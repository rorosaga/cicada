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
}
