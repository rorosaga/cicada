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
        .appearance, .textSize, .openAtLogin, .showInMenuBar, .backgroundService,
        .runSetup, .guidedTour, .demoMemory, .appVersion, .autoUpdate, .reportProblem,
        .ownerName, .ownerPhoto, .ownerEmail, .ownerProfiles, .ownerHandle, .ownerPage,
        .engineChoice, .plansAndKeys, .sleepUsePlan, .engineOverage, .engineAutoClaude,
        .sceneryPreview, .sleepRuns, .sleepTime, .sleepInterval, .scenerySource, .sceneryTime, .sceneryWeather, .mascot,
        .devicesList, .memoryHome, .devicesConnection, .memoryShare, .memoryCopy, .fromAnywhere, .remoteSwitch, .remoteReach, .remoteNew,
        .memoryLocation, .banks, .bankExport, .bankDelete, .searchMeaning, .searchImages, .memoryGroup, .fadePace,
        .outboundConnectors, .outboundFeeds, .outboundLogos, .telemetry, .credentials, .remoteAccess, .transcripts,
        .agentNotes,
    ]

    /// D6 (2026-10-22): rows that left Settings with their page, by id, with their new home — a palette recent, a
    /// harness script or a doc that names one still lands (`AppRouter.open(_:)`). `SettingsAnchorsTests` holds it.
    static let retiredRows: [SettingsRowID: SettingsHome] = [
        .sleepEngine: .settings(.intelligence, .engineChoice),
        .enginePreview: .settings(.intelligence, .engineChoice),
        .engineAsk: .settings(.intelligence, .engineChoice),
        .searchFolders: .page(.sources),
        .calendarApp: .page(.sources), .contactsApp: .page(.sources), .saveWhy: .page(.sources),
        .readingAgent: .readingInBrowser, .readingExploreSignedIn: .readingInBrowser, .readingNeverExplore: .readingInBrowser,
        .readingMethods: .readingInBrowser, .watchingMethods: .readingInBrowser, .readingSites: .readingInBrowser,
        .readingYouTube: .readingInBrowser,
        .agentsCloud: .settings(.devices, .fromAnywhere), .agentsSkill: .page(.skills),
        .agentsAutoRecall: .page(.agents), .agentsEditors: .page(.agents), .agentsReading: .readingInBrowser,
        .commandLineTool: .page(.agents),
    ]

    static let staticEntries: [SettingsEntry] = [
        // Sleep's look first: equal matches ("bookworm", "scenery") land on the study room's own rows.
        SettingsEntry(.mascot, .sleep, Copy.Mascot.title,
                      keywords: ["character", "avatar"] + MascotRegistry.all.map(\.displayName)),
        SettingsEntry(.scenerySource, .sleep, Copy.Scenery.source, keywords: ["scenery", "weather", "local weather", "How Sleep is doing", "choose"]),
        SettingsEntry(.sceneryTime, .sleep, Copy.Scenery.time, keywords: ["scenery", "day", "dusk", "night"], anchor: .scenerySource),
        SettingsEntry(.sceneryWeather, .sleep, Copy.Scenery.weather, keywords: ["scenery", "sunny", "cloudy", "windy", "rainy", "curtains"], anchor: .scenerySource),
        SettingsEntry(.sceneryPreview, .sleep, Copy.Scenery.preview, keywords: ["scenery", "study room"]),
        // General
        SettingsEntry(.appearance, .general, Copy.appearance, keywords: ["dark", "light", "theme", "mode", "system", "night"]),
        SettingsEntry(.textSize, .general, Copy.textSize, keywords: ["zoom", "font", "bigger", "smaller", "larger", "scale"]),
        SettingsEntry(.openAtLogin, .general, Copy.openAtLogin, keywords: ["login", "startup", "start", "launch", "boot"]),
        SettingsEntry(.showInMenuBar, .general, Copy.showInMenuBar, keywords: ["menu bar", "status", "bookworm", "icon", "tray", "hide"]),
        SettingsEntry(.backgroundService, .general, Copy.keepMemoryWorking, keywords: ["background", "launchd", "service", "closed", "always on", "sync"]),
        SettingsEntry(.runSetup, .general, Copy.setup, keywords: ["onboarding", "first run", "welcome", "start over", "checklist"]),
        SettingsEntry(.guidedTour, .general, Copy.Tour.settingsTitle, keywords: ["tour", "walkthrough", "tutorial", "guide", "help", "learn"]),
        SettingsEntry(.demoMemory, .general, Copy.Demo.demoTitle, keywords: ["demo", "example", "sample", "try", "made-up"]),
        SettingsEntry(.appVersion, .general, Copy.versionTitle, keywords: ["version", "build", "about", "update", "release"]),
        // G182 phase 5 — anchored on Version, its card-mate, because a developer build hides this row.
        SettingsEntry(.autoUpdate, .general, Copy.Updates.autoTitle,
                      keywords: ["update", "updates", "automatic", "upgrade", "new version", "check for updates", "install"],
                      anchor: .appVersion),
        SettingsEntry(.reportProblem, .general, Copy.ReportProblem.title,
                      keywords: ["report", "problem", "bug", "issue", "feedback", "diagnostics", "logs", "help"]),
        // You
        SettingsEntry(.ownerName, .you, Copy.ownerNameTitle, keywords: ["name", "me", "owner", "who"]),
        SettingsEntry(.ownerPhoto, .you, Copy.Profiles.photo, keywords: ["photo", "picture", "face"],
                      anchor: .ownerName),
        SettingsEntry(.ownerEmail, .you, Copy.ownerEmailTitle, keywords: ["email", "mail", "address", "gravatar"]),
        SettingsEntry(.ownerProfiles, .you, Copy.Profiles.title,
                      keywords: ["profile", "profiles", "links", "linkedin", "x", "twitter", "github", "website",
                                 "scholar", "instagram", "social", "where to check"]),
        // The pre-D6 GitHub handle shows as a profile link.
        SettingsEntry(.ownerHandle, .you, Copy.ownerHandleTitle, keywords: ["github", "username"], anchor: .ownerProfiles),
        SettingsEntry(.ownerPage, .you, Copy.ownerPageTitle, keywords: ["my page", "graph"], anchor: .ownerName),
        // Intelligence (D6) — Engines and Plans & keys, merged; their old names still find it.
        SettingsEntry(.engineChoice, .intelligence, Copy.Intelligence.inUse,
                      keywords: ["engine", "engines", "model", "llm", "claude", "chatgpt", "codex", "auto", "back to auto",
                                 "who reads", "different engine", "ask"]),
        SettingsEntry(.plansAndKeys, .intelligence, Copy.plansAndKeys,
                      keywords: ["sign in", "keys", "api key", "plan", "subscription", "credentials", "openrouter",
                                 "gemini", "xai", "grok", "groq", "mistral", "together", "fireworks", "deepinfra", "ollama",
                                 "local model"]),
        SettingsEntry(.sleepUsePlan, .intelligence, Copy.ServerPlan.usePlanTitle,
                      keywords: ["plan", "subscription", "scheduled", "nightly", "server", "limits"]),
        SettingsEntry(.engineOverage, .intelligence, Copy.keepGoingOnExtraUsage, keywords: ["extra usage", "overage", "limit"],
                      anchor: .sleepUsePlan),
        SettingsEntry(.engineAutoClaude, .intelligence, Copy.useClaudePlanWhenIStart,
                      keywords: ["claude plan", "subscription", "use for sleep", "api key"], anchor: .sleepUsePlan),
        // Sleep's hours
        SettingsEntry(.sleepRuns, .sleep, Copy.runsTitle, keywords: ["schedule", "nightly", "daily", "interval", "automatic", "consolidate", "when", "hours"]),
        SettingsEntry(.sleepTime, .sleep, Copy.runsAt, keywords: ["time", "hour", "clock"]),
        SettingsEntry(.sleepInterval, .sleep, Copy.runsEvery, keywords: ["hours", "how often", "interval"]),
        // Devices (G181, G212)
        SettingsEntry(.devicesList, .devices, Copy.Devices.devicesGroup,
                      keywords: ["devices", "pair", "qr", "code", "laptop", "server", "connected", "ssh", "revoke", "last seen", "add a device"]),
        SettingsEntry(.memoryHome, .devices, Copy.Devices.modeTitle,
                      keywords: ["server", "this mac", "headless", "remote", "address", "device token", "home server",
                                 "sync", "where", "memory lives"]),
        // Anchored on Memory on, its card-mate, because the row is drawn only while this app runs on a server.
        SettingsEntry(.devicesConnection, .devices, Copy.Devices.connectionIndexTitle,
                      keywords: ["server", "connection", "reachable", "offline", "waiting", "queue"],
                      anchor: .memoryHome),
        SettingsEntry(.memoryShare, .devices, Copy.MemoryCopy.shareTitle,
                      keywords: ["share", "sync", "other computers", "copy", "home", "publish"]),
        SettingsEntry(.memoryCopy, .devices, Copy.MemoryCopy.copyTitle,
                      keywords: ["copy", "replica", "offline", "sync", "another computer", "follow"]),
        SettingsEntry(.fromAnywhere, .devices, Copy.DevicesPage.apps,
                      keywords: ["remote", "connector", "outside this mac", Copy.fromAnywhere]),
        SettingsEntry(.remoteSwitch, .devices, Copy.remoteSwitchTitle,
                      keywords: ["phone", "claude.ai", "chatgpt", "perplexity", "connector", "remote", "mobile", Copy.fromAnywhere],
                      anchor: .fromAnywhere),
        SettingsEntry(.remoteReach, .devices, Copy.remoteReachTitle,
                      keywords: ["tailscale", "funnel", "ngrok", "tunnel", "public address", "https", Copy.fromAnywhere],
                      anchor: .fromAnywhere),
        SettingsEntry(.remoteNew, .devices, Copy.remoteNewConnectorTitle,
                      keywords: ["token", "link", "connect an app", "revoke", Copy.fromAnywhere], anchor: .fromAnywhere),
        // Privacy & data
        SettingsEntry(.memoryLocation, .privacy, Copy.memoryLocationTitle, keywords: ["folder", "path", "where", "finder", "files", "memory folder"]),
        SettingsEntry(.banks, .privacy, Copy.banksTitle, keywords: ["bank", "memories", "workspaces"]),
        SettingsEntry(.bankExport, .privacy, Copy.bankExportTitle, keywords: ["backup", "download", "zip", "take out", "copy"]),
        SettingsEntry(.bankDelete, .privacy, Copy.bankDeleteTitle, keywords: ["remove", "erase", "trash"]),
        // Search & memory's row (D6). Hidden keywords keep every technical word the old rows carried.
        SettingsEntry(.searchMeaning, .privacy, Copy.SearchFiles.runsHere,
                      keywords: ["meaning", "semantic", "embedding", "embeddings", "model", "vectors", "sharper",
                                 "search model", "download", "neural engine", "languages", "smarter search",
                                 "search version", "larger", "index", "search index", "search", "find",
                                 Copy.SearchFiles.meaningTitle, Copy.SearchFiles.formerSidebar]),
        SettingsEntry(.searchImages, .privacy, Copy.SearchFiles.imagesTitle,
                      keywords: ["image", "images", "picture", "pictures", "photos", "screenshots", "vision", "looks",
                                 "image model", "embedding"], anchor: .searchMeaning),
        SettingsEntry(.memoryGroup, .privacy, Copy.memorySection, keywords: [Copy.fadeHeader, "memory", "tidy"],
                      anchor: .searchMeaning),
        SettingsEntry(.fadePace, .privacy, Copy.fadePaceTitle,
                      keywords: ["fade", "decay", "forget", "archive", "pace", "still tracking", "slower", "faster"],
                      anchor: .searchMeaning),
        SettingsEntry(.outboundConnectors, .privacy, Copy.outboundConnectorsTitle, keywords: ["network", "internet", "fetch"]),
        SettingsEntry(.outboundFeeds, .privacy, Copy.outboundFeedsTitle, keywords: ["rss", "calendar", "network"]),
        SettingsEntry(.outboundLogos, .privacy, Copy.outboundLogosTitle, keywords: ["logos", "icons", "network"]),
        SettingsEntry(.telemetry, .privacy, Copy.telemetryTitle, keywords: ["telemetry", "analytics", "tracking", "ledger"]),
        SettingsEntry(.credentials, .privacy, Copy.credentialsTitle, keywords: ["api keys", "secrets", "remove keys"]),
        SettingsEntry(.remoteAccess, .privacy, Copy.remoteAccessTitle, keywords: ["remote", "outside", "from anywhere"]),
        SettingsEntry(.transcripts, .privacy, Copy.transcriptsTitle, keywords: ["transcripts", "conversations", "claude code"]),
        SettingsEntry(.agentNotes, .privacy, Copy.agentNotesTitle, keywords: ["memory notes", "agent notes", "claude code"]),
    ]

    /// Each section is a hit by its title, and by the names of the pages folded into it (D6, B1: keep the old search
    /// keywords on the merged entries).
    static let pageEntries: [SettingsEntry] = SettingsSection.allCases.map {
        SettingsEntry(.page($0), $0, $0.title, keywords: formerNames[$0, default: []])
    }

    static let formerNames: [SettingsSection: [String]] = [
        .intelligence: [Copy.engines, Copy.plansAndKeys],
        .privacy: [Copy.SearchFiles.formerSidebar, Copy.SearchFiles.sidebar],
        .devices: [Copy.Devices.formerSidebar, Copy.fromAnywhere],
    ]

    /// Names and ids only: a connection's account line and any token stay out, so typing in Settings never matches —
    /// or displays — a secret. D6: channels, harnesses, agents and skills left with their pages.
    static func dynamicEntries(connections: [ConnectionStatus]) -> [SettingsEntry] {
        connections.map { SettingsEntry(.connection($0.id), .intelligence, $0.label,
                                        keywords: [$0.planLabel ?? "", "sign in", "key", "plan"].filter { !$0.isEmpty }) }
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
        var appearance: AppearancePreference = AppearancePreference.defaultChoice
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
