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
    // General → In the background (round-4 D3, G143)
    static let openAtLogin = SettingsRowID("openAtLogin")
    static let backgroundService = SettingsRowID("backgroundService")
    // Sleep (Task 2)
    static let sleepRuns = SettingsRowID("sleepRuns")
    static let sleepTime = SettingsRowID("sleepTime")
    static let sleepInterval = SettingsRowID("sleepInterval")
    static let sleepEngine = SettingsRowID("sleepEngine")
    // Engines (Task 2)
    static let engineChoice = SettingsRowID("engineChoice")
    static let engineModel = SettingsRowID("engineModel")
    static let engineOverage = SettingsRowID("engineOverage")
    static let enginePreview = SettingsRowID("enginePreview")
    static let engineAsk = SettingsRowID("engineAsk")
    static let engineAutoClaude = SettingsRowID("engineAutoClaude")
    // Integrations (round-4 D2)
    static let calendarApp = SettingsRowID("calendarApp")
    // Agents and From anywhere (Task 3)
    static let agentsInstall = SettingsRowID("agentsInstall")
    static let agentsCloud = SettingsRowID("agentsCloud")
    // Agents' pointer to Skills (Task 8)
    static let agentsSkill = SettingsRowID("agentsSkill")
    // Agents' Remembers automatically (G149)
    static let agentsAutoRecall = SettingsRowID("agentsAutoRecall")
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
    /// G147 — one row per kind of page under "How things fade" (a suggestion or a chosen pace).
    static func fadeType(_ type: String) -> SettingsRowID { SettingsRowID("fadeType:\(type)") }

    /// The item id after `<kind>:`, when this row is one of that kind.
    func item(of kind: String) -> String? {
        let prefix = kind + ":"
        return rawValue.hasPrefix(prefix) ? String(rawValue.dropFirst(prefix.count)) : nil
    }
}
