import Foundation

/// A place on a Settings page that search, a deep link or an in-window pointer
/// can land on (G139, design §2.4). The raw value is a machine key: a bare
/// camelCase name for a static row, the same spelling as its `static let`
/// (`SettingsRowLintTests` relies on that), and `<kind>:<id>` for a row that
/// exists once per catalog item.
struct SettingsRowID: RawRepresentable, Hashable, Codable, Sendable {
    let rawValue: String
    init(rawValue: String) { self.rawValue = rawValue }
    init(_ rawValue: String) { self.rawValue = rawValue }

    // General (Task 1)
    static let appearance = SettingsRowID("appearance")
    static let heroScene = SettingsRowID("heroScene")
    static let textSize = SettingsRowID("textSize")
    static let runSetup = SettingsRowID("runSetup")
    // General → the app's version (G182)
    static let appVersion = SettingsRowID("appVersion")
    // General → In the background (round-4 D3, G143)
    static let openAtLogin = SettingsRowID("openAtLogin")
    // General → Startup → Show in menu bar (round-4 decision 6, R-HO16)
    static let showInMenuBar = SettingsRowID("showInMenuBar")
    static let backgroundService = SettingsRowID("backgroundService")
    // General → Getting to know Cicada (G152, G117 round 4)
    static let guidedTour = SettingsRowID("guidedTour")
    static let demoMemory = SettingsRowID("demoMemory")
    // Sleep (Task 2)
    static let sleepRuns = SettingsRowID("sleepRuns")
    static let sleepTime = SettingsRowID("sleepTime")
    static let sleepInterval = SettingsRowID("sleepInterval")
    static let sleepEngine = SettingsRowID("sleepEngine")
    static let scenerySource = SettingsRowID("scenerySource")
    static let sceneryTime = SettingsRowID("sceneryTime")
    static let sceneryWeather = SettingsRowID("sceneryWeather")
    static let sceneryPreview = SettingsRowID("sceneryPreview")
    static let mascot = SettingsRowID("mascot")
    // Engines (Task 2)
    static let engineChoice = SettingsRowID("engineChoice")
    static let engineModel = SettingsRowID("engineModel")
    static let engineOverage = SettingsRowID("engineOverage")
    static let enginePreview = SettingsRowID("enginePreview")
    static let engineAsk = SettingsRowID("engineAsk")
    static let engineAutoClaude = SettingsRowID("engineAutoClaude")
    // Integrations (round-4 D2)
    static let calendarApp = SettingsRowID("calendarApp")
    // Integrations (round 4, G154)
    static let contactsApp = SettingsRowID("contactsApp")
    // Agents and From anywhere (Task 3)
    static let agentsInstall = SettingsRowID("agentsInstall")
    static let agentsCloud = SettingsRowID("agentsCloud")
    // Agents' pointer to Skills (Task 8)
    static let agentsSkill = SettingsRowID("agentsSkill")
    /// G166 — the pointer from Agents to Reading the web (the reading switch left this page for its own).
    static let agentsReading = SettingsRowID("agentsReading")
    // Agents' Remembers automatically (G149)
    static let agentsAutoRecall = SettingsRowID("agentsAutoRecall")
    // Reading the web (G166): the master switch, the hand-off prompt, how the agent reads, the sites that need a browser
    static let readingAgent = SettingsRowID("readingAgent")
    static let readingPrompt = SettingsRowID("reading:prompt")
    static let readingMethods = SettingsRowID("readingMethods")
    static let watchingMethods = SettingsRowID("watchingMethods")
    static let readingSites = SettingsRowID("readingSites")
    static let readingSitesEmpty = SettingsRowID("reading:sitesEmpty")
    static let remoteSwitch = SettingsRowID("remoteSwitch")
    static let remoteReach = SettingsRowID("remoteReach")
    static let remoteNew = SettingsRowID("remoteNew")
    // You (Task 6)
    static let ownerName = SettingsRowID("ownerName")
    static let ownerHandle = SettingsRowID("ownerHandle")
    static let ownerEmail = SettingsRowID("ownerEmail")
    static let ownerPage = SettingsRowID("ownerPage")
    // Privacy & data (Task 6)
    static let memoryLocation = SettingsRowID("memoryLocation")
    static let banks = SettingsRowID("banks")
    static let bankExport = SettingsRowID("bankExport")
    static let bankDelete = SettingsRowID("bankDelete")
    static let telemetry = SettingsRowID("telemetry")
    static let outboundConnectors = SettingsRowID("outboundConnectors")
    static let outboundFeeds = SettingsRowID("outboundFeeds")
    static let outboundLogos = SettingsRowID("outboundLogos")
    static let credentials = SettingsRowID("credentials")
    static let remoteAccess = SettingsRowID("remoteAccess")
    static let transcripts = SettingsRowID("transcripts")
    // Memory (Task 6)
    static let searchIndex = SettingsRowID("searchIndex")
    static let enrichLinks = SettingsRowID("enrichLinks")
    static let fadePace = SettingsRowID("fadePace")
    // Advanced (Task 6)
    static let backendStatus = SettingsRowID("backendStatus")
    static let mcpCommand = SettingsRowID("mcpCommand")
    static let apiToken = SettingsRowID("apiToken")
    static let envOverrides = SettingsRowID("envOverrides")

    /// Every section's header — what a section-level hit lands on (R-O14).
    static func page(_ section: SettingsSection) -> SettingsRowID { SettingsRowID("page:\(section.rawValue)") }
    static func channel(_ id: String) -> SettingsRowID { SettingsRowID("channel:\(id)") }
    static func harness(_ id: String) -> SettingsRowID { SettingsRowID("harness:\(id)") }
    static func exportOnly(_ id: String) -> SettingsRowID { SettingsRowID("exportOnly:\(id)") }
    static func connection(_ id: String) -> SettingsRowID { SettingsRowID("connection:\(id)") }
    static func agent(_ id: String) -> SettingsRowID { SettingsRowID("agent:\(id)") }
    static func skill(_ id: String) -> SettingsRowID { SettingsRowID("skill:\(id)") }
    static func autoRecall(_ id: String) -> SettingsRowID { SettingsRowID("autoRecall:\(id)") }
    /// G166 — one switch per site Cicada's own reader could not read (a site is listed only once one of its pages hit
    /// a wall), and one radio per way the person's agent may read.
    static func readingSite(_ key: String) -> SettingsRowID { SettingsRowID("readingSite:\(key)") }
    static func readingMethod(_ id: String) -> SettingsRowID { SettingsRowID("readingMethod:\(id)") }
    static func watchingMethod(_ id: String) -> SettingsRowID { SettingsRowID("watchingMethod:\(id)") }
    /// G147 — one row per kind of page under "How things fade" (a suggestion or a chosen pace).
    static func fadeType(_ type: String) -> SettingsRowID { SettingsRowID("fadeType:\(type)") }

    /// The item id after `<kind>:`, when this row is one of that kind.
    func item(of kind: String) -> String? {
        let prefix = kind + ":"
        return rawValue.hasPrefix(prefix) ? String(rawValue.dropFirst(prefix.count)) : nil
    }
}
