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
        .appearance, .textSize, .runSetup, .appVersion, .autoUpdate, .openAtLogin, .showInMenuBar,
        .backgroundService, .commandLineTool,
        .memoryHome, .devicesConnection, .devicesList,
        .guidedTour, .demoMemory,
        .ownerName, .ownerHandle, .ownerEmail, .ownerPage,
        .memoryLocation, .banks, .bankExport, .bankDelete, .telemetry,
        .outboundConnectors, .outboundFeeds, .outboundLogos, .credentials, .remoteAccess, .transcripts,
        .searchFolders, .searchMeaning, .searchImages, .searchAdvanced, .searchModel, .searchIndex,
        .enrichLinks, .fadePace,
        .sleepRuns, .sleepTime, .sleepInterval, .sleepEngine, .sleepUsePlan,
        .scenerySource, .sceneryTime, .sceneryWeather, .sceneryPreview,
        .mascot,
        .calendarApp, .contactsApp, .saveWhy,
        .agentsInstall, .agentsCloud, .agentsSkill, .agentsAutoRecall, .agentsEditors, .agentsReading,
        .readingAgent, .readingExploreSignedIn, .readingNeverExplore, .readingMethods, .watchingMethods, .readingSites,
        .readingYouTube,
        // Cicada's own skills — per-item ids (a `:`), so outside the bare-name lint
        .skill(CicadaSkillBundle.cicada.rawValue), .skill(CicadaSkillBundle.cicadaLibrarian.rawValue),
        .skill(CicadaSkillBundle.linkedinPeople.rawValue),
        .remoteSwitch, .remoteReach, .remoteNew,
        .engineChoice, .engineModel, .engineOverage, .enginePreview, .engineAsk, .engineAutoClaude,
        .backendStatus, .mcpCommand, .apiToken, .envOverrides, .settingsFile,
    ]

    static let staticEntries: [SettingsEntry] = [
        SettingsEntry(.mascot, .sleep, Copy.Mascot.title,
                      keywords: ["character", "avatar"] + MascotRegistry.all.map(\.displayName)),
        SettingsEntry(.scenerySource, .sleep, Copy.Scenery.source, keywords: ["scenery", "weather", "local weather", "How Sleep is doing", "choose"], detail: Copy.Scenery.disclosure),
        SettingsEntry(.sceneryTime, .sleep, Copy.Scenery.time, keywords: ["scenery", "day", "dusk", "night"], anchor: .scenerySource),
        SettingsEntry(.sceneryWeather, .sleep, Copy.Scenery.weather, keywords: ["scenery", "sunny", "cloudy", "windy", "rainy", "curtains"], anchor: .scenerySource),
        SettingsEntry(.sceneryPreview, .sleep, Copy.Scenery.preview, keywords: ["scenery", "study room"]),
        // General
        SettingsEntry(.appearance, .general, Copy.appearance, keywords: ["dark", "light", "theme", "mode", "system", "night"]),
        SettingsEntry(.textSize, .general, Copy.textSize, keywords: ["zoom", "font", "bigger", "smaller", "larger", "scale"], detail: Copy.textSizeDetail),
        SettingsEntry(.runSetup, .general, Copy.setup, keywords: ["onboarding", "first run", "welcome", "start over"], detail: Copy.runSetupDetail),
        SettingsEntry(.appVersion, .general, Copy.versionTitle, keywords: ["version", "build", "about", "update", "release"]),
        // G182 phase 5 — anchored on Version, its card-mate, because a developer build hides this row: a search for
        // "update" lands on a row that is always there.
        SettingsEntry(.autoUpdate, .general, Copy.Updates.autoTitle,
                      keywords: ["update", "updates", "automatic", "upgrade", "new version", "check for updates", "install"],
                      anchor: .appVersion),
        SettingsEntry(.openAtLogin, .general, Copy.openAtLogin, keywords: ["login", "startup", "start", "launch", "boot"]),
        SettingsEntry(.showInMenuBar, .general, Copy.showInMenuBar, keywords: ["menu bar", "status", "bookworm", "icon", "tray", "hide"], detail: Copy.showInMenuBarDetail),
        SettingsEntry(.backgroundService, .general, Copy.keepMemoryWorking, keywords: ["background", "launchd", "service", "closed", "always on", "sync"]),
        // Devices (G181 phase 3)
        SettingsEntry(.memoryHome, .devices, Copy.Devices.modeTitle,
                      keywords: ["server", "this mac", "headless", "remote", "address", "device token", "home server",
                                 "sync", "where", "memory lives"]),
        SettingsEntry(.devicesConnection, .devices, Copy.Devices.connectionGroup,
                      keywords: ["server", "connection", "reachable", "offline", "waiting", "queue"]),
        SettingsEntry(.devicesList, .devices, Copy.Devices.devicesGroup,
                      keywords: ["devices", "synced", "laptop", "token", "revoke", "add a device", "last seen"]),
        SettingsEntry(.commandLineTool, .general, Copy.cliToolTitle, keywords: ["command line", "terminal", "shell", "cli", "path", "agent", "install"]),
        SettingsEntry(.guidedTour, .general, Copy.Tour.settingsTitle, keywords: ["tour", "walkthrough", "tutorial", "guide", "help", "learn"], detail: Copy.Tour.settingsDetail),
        SettingsEntry(.demoMemory, .general, Copy.Demo.demoTitle, keywords: ["demo", "example", "sample", "try", "made-up"], detail: Copy.Demo.demoDetail),
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
        // Search & files (owner, 2026-10-14). The page never shows a technical word; these hidden keywords keep every
        // one the old Memory rows carried ("index", "model", "embedding", "embeddings", "semantic", "vectors"), so a
        // technical search still lands on the right row (REVIEW §1e).
        SettingsEntry(.searchFolders, .searchFiles, Copy.SearchFiles.foldersGroup,
                      keywords: ["folder", "folders", "add a folder", "notes", "markdown", "files", "directory", "watch",
                                 "watched folders", "vault", "notes & files", "documents"],
                      detail: Copy.SearchFiles.addFolderDetail),
        SettingsEntry(.searchMeaning, .searchFiles, Copy.SearchFiles.meaningTitle,
                      keywords: ["meaning", "semantic", "embedding", "embeddings", "model", "vectors", "sharper",
                                 "search model", "download", "neural engine", "languages", "smarter search"]),
        SettingsEntry(.searchImages, .searchFiles, Copy.SearchFiles.imagesTitle,
                      keywords: ["image", "images", "picture", "pictures", "photos", "screenshots", "vision", "looks",
                                 "image model", "embedding"]),
        SettingsEntry(.searchAdvanced, .searchFiles, Copy.SearchFiles.advanced,
                      keywords: ["advanced", "search version", "rebuild"]),
        // Advanced's two rows land on the disclosure, which opens on landing (R-O6: the row a hit names is on screen).
        SettingsEntry(.searchModel, .searchFiles, Copy.SearchModel.title,
                      keywords: ["model", "embedding", "embeddings", "semantic", "larger", "smaller", "built in",
                                 "download", "vectors", "hugging face"],
                      anchor: .searchAdvanced),
        SettingsEntry(.searchIndex, .searchFiles, Copy.SearchFiles.rebuildTitle,
                      keywords: ["search", "index", "rebuild", "find", "search index"], anchor: .searchAdvanced),
        // Memory
        SettingsEntry(.enrichLinks, .memory, Copy.enrichLinksTitle, keywords: ["links", "previews", "descriptions", "bookmarks"], detail: Copy.enrichLinksDetail),
        SettingsEntry(.fadePace, .memory, Copy.fadePaceTitle,
                      keywords: ["fade", "decay", "forget", "archive", "pace", "still tracking", "slower", "faster"],
                      detail: Copy.fadePaceDetail),
        // Sleep
        SettingsEntry(.sleepRuns, .sleep, Copy.runsTitle, keywords: ["schedule", "nightly", "daily", "interval", "automatic", "consolidate", "when"]),
        SettingsEntry(.sleepTime, .sleep, Copy.runsAt, keywords: ["time", "hour", "clock"]),
        SettingsEntry(.sleepInterval, .sleep, Copy.runsEvery, keywords: ["hours", "how often", "interval"]),
        SettingsEntry(.sleepEngine, .sleep, Copy.sleepEngineRowTitle, keywords: ["model", "who runs"]),
        SettingsEntry(.sleepUsePlan, .sleep, Copy.ServerPlan.usePlanTitle,
                      keywords: ["plan", "subscription", "scheduled", "nightly", "server", "limits"]),
        // Integrations — round-4 D2: the one row the app owns there (R-FA13); every other row is a channel.
        SettingsEntry(.calendarApp, .integrations, Copy.calendarAppTitle,
                      keywords: ["calendar", "events", "meetings", "icloud", "google calendar", "exchange", "schedule"]),
        // Round 4 (G154): Contacts, the second row the app owns there.
        SettingsEntry(.contactsApp, .integrations, Copy.contactsTitle,
                      keywords: ["contacts", "address book", "people", "photos", "birthday"]),
        // G191: the save-why question, under the browsers it listens to.
        SettingsEntry(.saveWhy, .integrations, Copy.SaveWhy.switchTitle,
                      keywords: ["bookmark", "why", "intent", "reason", "notch", "prompt", "ask"],
                      detail: Copy.SaveWhy.switchDetail),
        // Agents
        SettingsEntry(.agentsInstall, .agents, Copy.agentsInstallTitle, keywords: ["make install", "setup", "python", "service"]),
        SettingsEntry(.agentsCloud, .agents, Copy.agentsCloudTitle, keywords: ["web", "cloud", "mobile", "claude.ai", "chatgpt"]),
        SettingsEntry(.agentsSkill, .agents, Copy.agentsSkillTitle, keywords: ["skill", "SKILL.md", "claude code"]),
        SettingsEntry(.agentsAutoRecall, .agents, Copy.autoRecallTitle,
                      keywords: ["remember", "recall", "automatic", "hooks", "context", "claude code", "codex"],
                      detail: Copy.autoRecallDetail),
        SettingsEntry(.agentsEditors, .agents, Copy.PageEdits.rowTitle,
                      keywords: ["edit", "edits", "pages", "trust", "trusted", "permission", "fix", "aliases", "write"],
                      detail: Copy.PageEdits.rowDetail),
        SettingsEntry(.agentsReading, .agents, Copy.Reading.agentsRowTitle,
                      keywords: ["read", "pages", "browser", "sites"], detail: Copy.Reading.agentsRowDetail),
        // Reading the web (G166)
        SettingsEntry(.readingAgent, .reading, Copy.Reading.switchTitle,
                      keywords: ["read", "pages", "links", "browser", "linkedin", "sign in", "login", "ask an agent",
                                 "reading", "web"],
                      detail: Copy.Reading.switchDetail),
        SettingsEntry(.readingExploreSignedIn, .reading, Copy.Explore.signedInTitle,
                      keywords: ["explore", "exploring", "bookmarks", "saved sites", "signed in", "private", "cookies",
                                 "incognito", "screenshots"],
                      detail: Copy.Explore.signedInDetail),
        SettingsEntry(.readingYouTube, .reading, Copy.Reading.youtubeGroup,
                      keywords: ["youtube", "watch later", "watch history", "history", "videos", "agent", "browser"],
                      detail: Copy.Reading.youtubeIntro),
        SettingsEntry(.readingNeverExplore, .reading, Copy.Explore.neverTitle,
                      keywords: ["never explore", "explore", "exclude", "block", "skip", "site", "bookmarks"],
                      detail: Copy.Explore.neverDetail),
        SettingsEntry(.readingMethods, .reading, Copy.Reading.methodsGroup,
                      keywords: ["skill", "tool", "browser", "computer", "how", "reads", "own tools", "let my agent choose",
                                 "agent"],
                      detail: Copy.Reading.methodsDetail),
        SettingsEntry(.watchingMethods, .reading, Copy.Reading.watchMethodsGroup,
                      keywords: ["skill", "tool", "video", "videos", "watch", "watches", "watching", "browser",
                                 "computer", "mac", "own tools", "let my agent choose", "agent"],
                      detail: Copy.Reading.watchMethodsDetail),
        SettingsEntry(.readingSites, .reading, Copy.Reading.sitesGroup,
                      keywords: ["sites", "wall", "sign in", "login", "consent", "favicon", "icon", "allow"],
                      detail: Copy.Reading.sitesIntro),
        // Cicada's own skills (G138) — per-item ids, so outside the bare-name lint
        SettingsEntry(.skill(CicadaSkillBundle.cicada.rawValue), .skills, CicadaSkillBundle.cicada.title,
                      keywords: ["cicada skill", "recall", "save"], detail: CicadaSkillBundle.cicada.summary),
        SettingsEntry(.skill(CicadaSkillBundle.cicadaLibrarian.rawValue), .skills, CicadaSkillBundle.cicadaLibrarian.title,
                      keywords: ["librarian", "consolidate"], detail: CicadaSkillBundle.cicadaLibrarian.summary),
        SettingsEntry(.skill(CicadaSkillBundle.linkedinPeople.rawValue), .skills, CicadaSkillBundle.linkedinPeople.title,
                      keywords: ["linkedin", "people", "profile", "connections"],
                      detail: CicadaSkillBundle.linkedinPeople.summary),
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
        SettingsEntry(.settingsFile, .advanced, Copy.settingsFileTitle, keywords: ["api/.env", ".env", "settings", "concurrency", "in effect"]),
    ]

    /// A page whose header asks its own question (Search & files) is also found by it.
    static let pageEntries: [SettingsEntry] = SettingsSection.allCases.map {
        SettingsEntry(.page($0), $0, $0.title, keywords: $0.pageTitle == $0.title ? [] : [$0.pageTitle], detail: $0.subtitle)
    }

    /// Names and ids only: a connection's account line, an agent's install
    /// command (which carries this machine's paths) and any token stay out,
    /// so typing in Settings never matches — or displays — a secret.
    static func dynamicEntries(channels: [SourceChannel], harnessRows: [SourceOverview],
                               exportOnly: [AddSourceTile], connections: [ConnectionStatus],
                               agents: [AgentCatalogEntry], skills: [RecommendedSkill] = []) -> [SettingsEntry] {
        var out: [SettingsEntry] = []
        // R-FA13 — `calendar-local` is `.calendarApp`'s row, never a second search entry; `contacts-local` is
        // `.contactsApp`'s (G154).
        // A watched folder lists on Search & files (owner, 2026-10-14), every other channel on Integrations.
        out += channels.filter { $0.id != CalendarRow.channelId && $0.id != ContactsReader.channel }.map {
            $0.id.hasPrefix("folder:")
                ? SettingsEntry(.channel($0.id), .searchFiles, $0.label, keywords: [$0.id, "folder", Copy.SearchFiles.foldersGroup])
                : SettingsEntry(.channel($0.id), .integrations, $0.label,
                                keywords: [$0.id, IntegrationCategory.of(channelId: $0.id).title])
        }
        out += harnessRows.map { SettingsEntry(.harness($0.harness ?? $0.id), .integrations, $0.label,
                                               keywords: ["agent", "conversations"]) }
        out += exportOnly.map { SettingsEntry(.exportOnly($0.id), .integrations, $0.title, keywords: ["import", "export"]) }
        out += connections.map { SettingsEntry(.connection($0.id), .plansAndKeys, $0.label,
                                               keywords: [$0.planLabel ?? "", "sign in", "key", "plan"].filter { !$0.isEmpty }) }
        out += agents.map { SettingsEntry(.agent($0.id), .agents, $0.name, keywords: ["mcp", "connect", "register"] + $0.searchTerms) }
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

/// G139's landing, as values (R-HS22): what ⏎ in the panel's field opens, and what VoiceOver hears
/// when it lands. `SettingsPanel.openTopHit` and `land(_:)` call these, so the test drives the same
/// code the field does.
enum SettingsSearchLanding {
    static func topHit(_ query: String, in entries: [SettingsEntry]) -> SettingsEntry? {
        SettingsIndex.search(query.trimmingCharacters(in: .whitespacesAndNewlines), in: entries).first?.entry
    }

    /// "Sleep, Runs", not just "Sleep".
    static func announcement(section: SettingsSection, row: SettingsRowID, in entries: [SettingsEntry]) -> String {
        SettingsIndex.entry(for: row, in: entries).map { "\(section.title), \($0.title)" } ?? section.title
    }
}
