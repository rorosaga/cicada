// SwiftUI, not just Foundation: `attributedTitle` sets SwiftUI's `Font`
// attribute on an `AttributedString`, which needs SwiftUI's attribute scope.
import SwiftUI

/// Everything Settings search can find (G139, design §2.4). Static entries are
/// every row on every page, in page order (ties break by this order); page
/// entries make each section a hit (R-O14); dynamic entries are built from
/// the snapshots the Settings window already holds — never a fetch of its own,
/// and never an account, a token or a command (only names and ids).
struct SettingsEntry: Identifiable, Hashable {
    let id: SettingsRowID
    let section: SettingsSection
    let title: String
    let keywords: [String]
    let detail: String?
    /// Where landing scrolls and washes — the row itself unless the row lives
    /// in a view that carries no anchors (From anywhere, R-O12).
    let anchor: SettingsRowID
    let fields: [QuickMatch.Field]

    init(_ id: SettingsRowID, _ section: SettingsSection, _ title: String,
         keywords: [String] = [], detail: String? = nil, anchor: SettingsRowID? = nil) {
        self.id = id
        self.section = section
        self.title = title
        self.keywords = keywords
        self.detail = detail
        self.anchor = anchor ?? id
        var fields = [QuickMatch.Field(title, weight: QuickMatch.Weight.name)]
        fields += keywords.map { QuickMatch.Field($0, weight: QuickMatch.Weight.keyword) }
        if let detail { fields.append(QuickMatch.Field(detail, weight: QuickMatch.Weight.body)) }
        // R-O14 — rows also match their section's title, at low weight, so
        // "sleep" finds Sleep's rows beneath the section itself.
        fields.append(QuickMatch.Field(section.title, weight: QuickMatch.Weight.body))
        self.fields = fields
    }

    // `fields` is folded from the other stored properties, so equality and
    // hashing over those is equality over the entry (`QuickMatch.Field` is
    // not `Hashable`, and need not be).
    static func == (lhs: SettingsEntry, rhs: SettingsEntry) -> Bool {
        lhs.id == rhs.id && lhs.section == rhs.section && lhs.title == rhs.title
            && lhs.keywords == rhs.keywords && lhs.detail == rhs.detail && lhs.anchor == rhs.anchor
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(id)
        hasher.combine(section)
        hasher.combine(title)
        hasher.combine(keywords)
        hasher.combine(detail)
        hasher.combine(anchor)
    }
}

struct SettingsHit: Identifiable, Hashable {
    let entry: SettingsEntry
    let score: Double
    /// `[start, end)` runs in the title's ORIGINAL Unicode scalars —
    /// `QuickMatch.Match.ranges(inField: 0)`, the unit every other surface bolds in.
    let titleRanges: [[Int]]
    let order: Int
    var id: SettingsRowID { entry.id }
}

enum SettingsIndex {
    /// Every static row id a page renders. `SettingsIndexTests` holds this
    /// list and `staticEntries` to one another, and `SettingsRowLintTests`
    /// holds the entries to the pages — a task that adds a row adds it here
    /// in the same commit (R-O1).
    static let staticIDs: [SettingsRowID] = [
        .appearance, .textSize, .runSetup,
        .ownerName, .ownerHandle, .ownerEmail, .ownerPage,
        .memoryLocation, .banks, .bankExport, .bankDelete, .telemetry,
        .outboundConnectors, .outboundFeeds, .outboundLogos, .credentials, .remoteAccess, .transcripts,
        .searchIndex, .enrichLinks,
        .sleepRuns, .sleepTime, .sleepInterval, .sleepEngine,
        .agentsInstall, .agentsCloud, .agentsSkill,
        // Cicada's own skills — per-item ids (a `:`), so outside the bare-name lint
        .skill(CicadaSkillBundle.cicada.rawValue), .skill(CicadaSkillBundle.cicadaLibrarian.rawValue),
        .remoteSwitch, .remoteReach, .remoteNew,
        .engineChoice, .engineModel, .engineOverage, .enginePreview, .engineAsk, .engineAutoClaude,
        .backendStatus, .mcpCommand, .apiToken, .envOverrides,
    ]

    static let staticEntries: [SettingsEntry] = [
        // General
        SettingsEntry(.appearance, .general, Copy.appearance, keywords: ["dark", "light", "theme", "mode", "system", "night"]),
        SettingsEntry(.textSize, .general, Copy.textSize, keywords: ["zoom", "font", "bigger", "smaller", "larger", "scale"], detail: Copy.textSizeDetail),
        SettingsEntry(.runSetup, .general, Copy.setup, keywords: ["onboarding", "first run", "welcome", "start over"], detail: Copy.runSetupDetail),
        // You
        SettingsEntry(.ownerName, .you, Copy.ownerNameTitle, keywords: ["name", "me", "owner", "who"]),
        SettingsEntry(.ownerHandle, .you, Copy.ownerHandleTitle, keywords: ["github", "avatar", "picture", "username"], detail: Copy.ownerHandleDetail),
        SettingsEntry(.ownerEmail, .you, Copy.ownerEmailTitle, keywords: ["email", "mail", "address"]),
        SettingsEntry(.ownerPage, .you, Copy.ownerPageTitle, keywords: ["my page", "profile", "graph"]),
        // Privacy & data
        SettingsEntry(.memoryLocation, .privacy, Copy.memoryLocationTitle, keywords: ["folder", "path", "where", "finder", "CICADA_MEMORY_PATH"]),
        SettingsEntry(.banks, .privacy, Copy.banksTitle, keywords: ["bank", "memories", "workspaces"]),
        SettingsEntry(.bankExport, .privacy, Copy.bankExportTitle, keywords: ["backup", "download", "zip", "take out", "copy"]),
        SettingsEntry(.bankDelete, .privacy, Copy.bankDeleteTitle, keywords: ["remove", "erase", "trash"]),
        SettingsEntry(.telemetry, .privacy, Copy.telemetryTitle, keywords: ["telemetry", "analytics", "tracking", "ledger", "CICADA_TELEMETRY"]),
        SettingsEntry(.outboundConnectors, .privacy, Copy.outboundConnectorsTitle, keywords: ["network", "internet", "fetch", "CICADA_ALLOW_CONNECTOR_FETCH"]),
        SettingsEntry(.outboundFeeds, .privacy, Copy.outboundFeedsTitle, keywords: ["rss", "calendar", "network", "CICADA_ALLOW_FEED_FETCH"]),
        SettingsEntry(.outboundLogos, .privacy, Copy.outboundLogosTitle, keywords: ["logos", "icons", "network", "CICADA_ALLOW_LOGO_FETCH"]),
        SettingsEntry(.credentials, .privacy, Copy.credentialsTitle, keywords: ["api keys", "secrets", "remove keys", "secrets.env"]),
        SettingsEntry(.remoteAccess, .privacy, Copy.remoteAccessTitle, keywords: ["remote", "outside", "from anywhere"]),
        SettingsEntry(.transcripts, .privacy, Copy.transcriptsTitle, keywords: ["transcripts", "conversations", "claude code"], detail: Copy.transcriptsFact),
        // Memory
        SettingsEntry(.searchIndex, .memory, Copy.searchIndexTitle, keywords: ["search", "index", "rebuild", "find"]),
        SettingsEntry(.enrichLinks, .memory, Copy.enrichLinksTitle, keywords: ["links", "previews", "descriptions", "bookmarks"], detail: Copy.enrichLinksDetail),
        // Sleep
        SettingsEntry(.sleepRuns, .sleep, Copy.runsTitle, keywords: ["schedule", "nightly", "daily", "interval", "automatic", "consolidate", "when"]),
        SettingsEntry(.sleepTime, .sleep, Copy.runsAt, keywords: ["time", "hour", "clock"]),
        SettingsEntry(.sleepInterval, .sleep, Copy.runsEvery, keywords: ["hours", "how often", "interval"]),
        SettingsEntry(.sleepEngine, .sleep, Copy.sleepEngineRowTitle, keywords: ["model", "who runs"]),
        // Agents
        SettingsEntry(.agentsInstall, .agents, Copy.agentsInstallTitle, keywords: ["make install", "setup", "python", "service"]),
        SettingsEntry(.agentsCloud, .agents, Copy.agentsCloudTitle, keywords: ["web", "cloud", "mobile", "claude.ai", "chatgpt"]),
        SettingsEntry(.agentsSkill, .agents, Copy.agentsSkillTitle, keywords: ["skill", "SKILL.md", "claude code"]),
        // Cicada's own skills (G138) — per-item ids, so outside the bare-name lint
        SettingsEntry(.skill(CicadaSkillBundle.cicada.rawValue), .skills, CicadaSkillBundle.cicada.title,
                      keywords: ["cicada skill", "recall", "save"], detail: CicadaSkillBundle.cicada.summary),
        SettingsEntry(.skill(CicadaSkillBundle.cicadaLibrarian.rawValue), .skills, CicadaSkillBundle.cicadaLibrarian.title,
                      keywords: ["librarian", "consolidate"], detail: CicadaSkillBundle.cicadaLibrarian.summary),
        // From anywhere — landing on its header (R-O12)
        SettingsEntry(.remoteSwitch, .remote, Copy.remoteSwitchTitle,
                      keywords: ["phone", "claude.ai", "chatgpt", "perplexity", "connector", "remote", "mobile"], anchor: .page(.remote)),
        SettingsEntry(.remoteReach, .remote, Copy.remoteReachTitle,
                      keywords: ["tailscale", "funnel", "ngrok", "tunnel", "public address", "https"], anchor: .page(.remote)),
        SettingsEntry(.remoteNew, .remote, Copy.remoteNewConnectorTitle,
                      keywords: ["token", "link", "connect an app", "revoke"], anchor: .page(.remote)),
        // Engines
        SettingsEntry(.engineChoice, .engines, Copy.enginesChooseGroup,
                      keywords: ["model", "llm", "claude", "chatgpt", "codex", "ollama", "api key", "plan", "auto"]),
        SettingsEntry(.engineModel, .engines, Copy.engineModelTitle, keywords: ["sonnet", "haiku", "opus", "gpt", "llama", "model id"]),
        SettingsEntry(.engineOverage, .engines, Copy.keepGoingOnExtraUsage, keywords: ["extra usage", "overage", "limit"]),
        SettingsEntry(.enginePreview, .engines, Copy.enginePreviewTitle, keywords: ["schedule", "nightly", "which engine"]),
        SettingsEntry(.engineAsk, .engines, Copy.askTitle, keywords: ["questions", "answers"], detail: Copy.askFollowsEngine),
        // The switch was A3's "Auto may use my Claude plan"; the final review
        // renamed it to what it does (shown only under the API key card).
        SettingsEntry(.engineAutoClaude, .engines, Copy.useClaudePlanWhenIStart,
                      keywords: ["claude plan", "subscription", "use for sleep", "api key"]),
        // Advanced
        SettingsEntry(.backendStatus, .advanced, Copy.backendTitle, keywords: ["server", "version", "status"]),
        SettingsEntry(.mcpCommand, .advanced, Copy.mcpCommandTitle, keywords: ["mcp", "command", "python"]),
        SettingsEntry(.apiToken, .advanced, Copy.apiTokenTitle, keywords: ["token", "bearer", "CICADA_API_TOKEN"]),
        SettingsEntry(.envOverrides, .advanced, Copy.envOverridesTitle, keywords: ["env", ".env", "environment", "variables", "CICADA_LLM_MODE"]),
    ]

    static let pageEntries: [SettingsEntry] = SettingsSection.allCases.map {
        SettingsEntry(.page($0), $0, $0.title, detail: $0.subtitle)
    }

    /// Names and ids only: a connection's account line, an agent's install
    /// command (which carries this machine's paths) and any token stay out,
    /// so typing in Settings never matches — or displays — a secret.
    static func dynamicEntries(channels: [SourceChannel], harnessRows: [SourceOverview],
                               exportOnly: [AddSourceTile], connections: [ConnectionStatus],
                               agents: [AgentSetup], skills: [RecommendedSkill] = []) -> [SettingsEntry] {
        var out: [SettingsEntry] = []
        out += channels.map { SettingsEntry(.channel($0.id), .integrations, $0.label,
                                            keywords: [$0.id, IntegrationCategory.of(channelId: $0.id).title]) }
        out += harnessRows.map { SettingsEntry(.harness($0.harness ?? $0.id), .integrations, $0.label,
                                               keywords: ["agent", "conversations"]) }
        out += exportOnly.map { SettingsEntry(.exportOnly($0.id), .integrations, $0.title, keywords: ["import", "export"]) }
        out += connections.map { SettingsEntry(.connection($0.id), .plansAndKeys, $0.label,
                                               keywords: [$0.planLabel ?? "", "sign in", "key", "plan"].filter { !$0.isEmpty }) }
        out += agents.map { SettingsEntry(.agent($0.id), .agents, $0.name, keywords: ["mcp", "connect", "register"]) }
        // G138 — the recommended and installed skills the window already
        // fetched; a title, a publisher and an id, never an install command.
        out += skills.map { SettingsEntry(.skill($0.id), .skills, $0.title,
                                          keywords: [$0.publisher, $0.id].filter { !$0.isEmpty }, detail: $0.summary) }
        return out
    }

    /// Best score first; a tie keeps index order (pages, then rows in page
    /// order), so equal matches read the way the pages do.
    static func search(_ query: String, in entries: [SettingsEntry]) -> [SettingsHit] {
        let tokens = QuickMatch.tokens(query)
        guard !tokens.isEmpty else { return [] }
        return entries.enumerated()
            .compactMap { index, entry in
                QuickMatch.match(tokens, fields: entry.fields).map {
                    SettingsHit(entry: entry, score: $0.score, titleRanges: $0.ranges(inField: 0), order: index)
                }
            }
            .sorted { $0.score != $1.score ? $0.score > $1.score : $0.order < $1.order }
    }

    /// The sidebar's per-section badges.
    static func counts(_ hits: [SettingsHit]) -> [SettingsSection: Int] {
        hits.reduce(into: [:]) { $0[$1.entry.section, default: 0] += 1 }
    }

    /// Results read in sidebar order; within a section, best first.
    static func grouped(_ hits: [SettingsHit]) -> [(section: SettingsSection, hits: [SettingsHit])] {
        SettingsSection.allCases.compactMap { section in
            let inSection = hits.filter { $0.entry.section == section }
            return inSection.isEmpty ? nil : (section, inSection)
        }
    }

    static func entry(for id: SettingsRowID, in entries: [SettingsEntry]) -> SettingsEntry? {
        entries.first { $0.id == id || $0.anchor == id }
    }

    /// The result's title with the matched letters in semibold (design §2.4).
    /// `ranges` are `[start, end)` Unicode-scalar offsets (`QuickMatch`'s unit,
    /// as in `ExcerptText.attributed`); a range past the end is skipped
    /// rather than trusted.
    static func attributedTitle(_ title: String, ranges: [[Int]]) -> AttributedString {
        var out = AttributedString(title)
        let scalars = title.unicodeScalars
        let count = scalars.count
        for pair in ranges where pair.count == 2 {
            let (start, end) = (pair[0], pair[1])
            guard start >= 0, end > start, end <= count else { continue }
            let lower = scalars.index(scalars.startIndex, offsetBy: start)
            let upper = scalars.index(scalars.startIndex, offsetBy: end)
            guard let aLower = AttributedString.Index(lower, within: out),
                  let aUpper = AttributedString.Index(upper, within: out) else { continue }
            out[aLower..<aUpper].font = CicadaTheme.font(size: 13, weight: .semibold)
        }
        return out
    }
}

/// A cheap, already-known value beside a result (design §2.4) — read from what
/// the window holds, never fetched.
enum SettingsLiveValue {
    struct Inputs {
        var scheduleMode: String?
        var appearance: AppearancePreference = .dark
        var uiScale: Double = 1.0
        var connections: [ConnectionStatus] = []
    }

    static func text(for id: SettingsRowID, _ inputs: Inputs) -> String? {
        if let connection = id.item(of: "connection") {
            guard let c = inputs.connections.first(where: { $0.id == connection }) else { return nil }
            return !c.available ? Copy.settingsNotInstalled : c.connected ? Copy.settingsConnected : Copy.settingsNotConnected
        }
        switch id {
        case .sleepRuns:
            return SleepScheduleText.modes.first { $0.value == inputs.scheduleMode }?.label
        case .appearance:
            return inputs.appearance.label
        case .textSize:
            return "\(Int((inputs.uiScale * 100).rounded()))%"
        default:
            return nil
        }
    }
}
