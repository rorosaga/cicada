import Foundation

// Onboarding v2 (G217, G92, ruling 36; 2026-10-22) — what each working step shows, decided purely so the views are
// renderers and the rules are tested without a window (`OnboardingStepsTests`).

// MARK: Intelligence

/// Step 2's headline (ruling 36 D1): a signed-in plan pre-selected and said in words with what runs; a chosen engine by
/// its own words; or nothing yet, which shows the plans and the keys side by side as equal options.
enum IntelligenceStepState: Equatable {
    /// The person's plan reads, said once (ruling 39, 2026-10-24: "avoid repetition"): the plan by name ("Using your
    /// Claude plan") and the harness Cicada runs on its limits ("Cicada runs your own Claude Code.").
    case plan(line: String, runs: String, mark: String)
    /// Something else reads (a key the person chose, a stored non-Auto choice): `EngineHeadline`'s own words.
    case chosen(title: String, line: String, mark: String)
    /// No engine can read yet.
    case nothing

    /// The keys onboarding offers (the person's likely providers, one router); every other key waits in Settings →
    /// Intelligence, one link away, so the step stays a choice rather than a catalogue.
    static let featuredKeys: Set<String> = ["byok-anthropic", "byok-openai", "byok-gemini", "byok-openrouter"]

    static func of(_ response: SleepEngineResponse?) -> IntelligenceStepState {
        guard let response else { return .nothing }
        let headline = EngineHeadline.of(response)
        if headline.needsSignIn { return .nothing }
        if headline.isAuto, let engine = response.preview?.manual.engine, ScheduleHonesty.planEngines.contains(engine) {
            return plan(response, card: engine == "claude-cli" ? "agent" : "codex")
        }
        // A plan chosen outright (or fixed by the environment) reads the same way: it is still the person's plan.
        if ["agent", "codex"].contains(response.selected) { return plan(response, card: response.selected) }
        return .chosen(title: headline.title, line: headline.line, mark: EngineStepMark.logo(headline.mark))
    }

    private static func plan(_ response: SleepEngineResponse, card: String) -> IntelligenceStepState {
        let claude = card == "agent"
        let label = response.candidates.first { $0.id == card }?.label
            ?? Copy.engineLabel(claude ? "claude-cli" : "codex-cli")
        return .plan(line: Copy.intelUsing(label), runs: Copy.intelRuns(claude ? "Claude Code" : "Codex"),
                     mark: claude ? "claude" : "openai")
    }
}

/// `EngineHeadline.mark` names an engine card; the logo set names the umbrella.
enum EngineStepMark {
    static func logo(_ card: String) -> String {
        switch card {
        case "agent": "claude"
        case "codex": "openai"
        case "openrouter": "openrouter"
        default: card
        }
    }
}

// MARK: Agents

/// What one agent's row offers, in the order Settings' own steps would (`AgentQuickSetup.actions`, `AgentSteps`).
enum AgentRowAction: Equatable {
    /// Already calling Cicada.
    case none
    /// Connect for me: the wire's commands plus Remembers automatically's (R-OB12), shown before the click that runs
    /// them (spec decision 14).
    case connect([AgentWiringStep])
    /// The Claude app: the config merge Settings' *Set up Claude* runs.
    case setUpClaude
    /// Cursor: the app's own catalog link.
    case openCursor
    /// Anything else: the setup prompt the agent carries out itself.
    case copy(String)
    /// Its setup has not arrived yet.
    case preparing
}

/// One product found on this Mac (Claude Code, the Claude app, Codex …): what Settings would offer it.
struct AgentStepRow: Identifiable, Equatable {
    let entry: AgentCatalogEntry
    let connected: Bool
    let action: AgentRowAction
    /// The product's name as its umbrella lists it ("Claude Code", "Claude Desktop"), else the catalog's.
    var name: String
    /// Seen only through the remote connector (claude.ai with no Claude Desktop on this Mac): named by the way's
    /// `remoteLabel`, never after the Mac app (ruling 39).
    var viaRemote = false
    var id: String { entry.id }

    init(entry: AgentCatalogEntry, connected: Bool, action: AgentRowAction, name: String? = nil, viaRemote: Bool = false) {
        self.entry = entry; self.connected = connected; self.action = action; self.name = name ?? entry.name
        self.viaRemote = viaRemote
    }

    /// Whether this product still has something to do here (`.none` is connected; `.preparing` waits for its setup).
    var actionable: Bool {
        switch action {
        case .none, .preparing: false
        default: true
        }
    }
}

/// One row of the Agents step (owner fix round, 2026-10-22): a provider umbrella (`GET /providers`, as the Agents page
/// lists them) with the products of it found on this Mac. The umbrella's own mark (`LogoTile`), never a product badge;
/// one Connect that offers each found product's own action.
struct AgentUmbrellaRow: Identifiable, Equatable {
    let id: String
    let label: String
    let logo: String?
    let products: [AgentStepRow]

    var connected: Bool { products.contains(where: \.connected) }
    /// "Claude Code · Claude Desktop" — the products found, in the umbrella's order.
    var detail: String { products.map(\.name).joined(separator: " · ") }
    var actionable: [AgentStepRow] { products.filter(\.actionable) }
}

enum AgentStepRows {
    /// The agents found on this machine — the backend's wiring says a harness is installed (config detection), the
    /// Claude app is on this Mac, or `/agents/live` already saw it call — in catalog order. Cloud agents and "another
    /// agent" are not rows here: the step's own two rows below the list cover them.
    static func rows(wiring: AgentWiringResponse?, live: [String: AgentLiveRow], setups: [String: AgentSetupPrompt],
                     claudeAppInstalled: Bool) -> [AgentStepRow] {
        AgentCatalog.all.compactMap { entry -> AgentStepRow? in
            let row = wiring?.agents.first { $0.id == entry.id }
            let connected = live[entry.id]?.connected == true
            switch entry.kind {
            case .remote, .anyAgent: return nil
            case .claude:
                guard claudeAppInstalled || connected else { return nil }
                return AgentStepRow(entry: entry, connected: connected, action: connected ? .none : .setUpClaude,
                                    viaRemote: !claudeAppInstalled)
            case .prompt, .deeplink:
                guard row?.installed == true || connected else { return nil }
                return AgentStepRow(entry: entry, connected: connected,
                                    action: connected ? .none : action(for: entry, wiring: row, setups: setups))
            }
        }
    }

    /// The found products grouped under their provider umbrellas, in the providers table's order. A product no
    /// umbrella claims (an older backend's table, or none loaded yet) gets an umbrella of its own under its vendor's
    /// mark (`umbrellaLogo`), so a product badge never stands in for the umbrella.
    static func umbrellas(_ providers: [ProviderUmbrella], products: [AgentStepRow]) -> [AgentUmbrellaRow] {
        var left = products
        var out: [AgentUmbrellaRow] = []
        for umbrella in providers {
            var mine: [AgentStepRow] = []
            for way in umbrella.ways {
                guard let i = left.firstIndex(where: { $0.id == way.id || way.setup.contains($0.id)
                    || $0.entry.setupHarnesses.contains(way.id) }) else { continue }
                var product = left.remove(at: i)
                product.name = product.viaRemote ? (way.remoteLabel ?? way.label) : way.label
                mine.append(product)
            }
            if !mine.isEmpty {
                out.append(AgentUmbrellaRow(id: umbrella.id, label: umbrella.label, logo: umbrella.logo, products: mine))
            }
        }
        for product in left {
            out.append(AgentUmbrellaRow(id: product.id, label: product.name, logo: umbrellaLogo(product.entry.id),
                                        products: [product]))
        }
        return out
    }

    /// The vendor's mark for a product: Claude Code and the Claude app draw Anthropic's, Codex and ChatGPT OpenAI's,
    /// Gemini CLI Gemini's; everything else is its own vendor already.
    static func umbrellaLogo(_ id: String) -> String? {
        switch id {
        case "claude-code", "claude": "claude"
        case "codex", "chatgpt": "openai"
        case "gemini-cli": "gemini"
        default: AgentCatalog.entry(for: id)?.mark
        }
    }

    /// An umbrella's dot and word: green once any of its products called; Waiting after this step started one; Not
    /// connected before — the Agents page's word for the same state (ruling 39: one status vocabulary, never "Found").
    static func status(_ row: AgentUmbrellaRow, started: Set<String>) -> (word: String, on: Bool) {
        if row.connected { return (Copy.Status.connected, true) }
        return (row.products.contains { started.contains($0.id) } ? Copy.Status.waiting : Copy.Status.notConnected, false)
    }

    static func action(for entry: AgentCatalogEntry, wiring: AgentWiring?,
                       setups: [String: AgentSetupPrompt]) -> AgentRowAction {
        let setup = entry.setupHarnesses.first.flatMap { setups[$0] }
        let quick = AgentQuickSetup.actions(catalogId: entry.id, setup: setup, wiring: wiring)
        for action in quick {
            if case .connectForMe(let steps) = action { return .connect(steps + AgentSteps.recallSteps(for: wiring)) }
        }
        if quick.contains(.openCursor) { return .openCursor }
        for action in quick {
            if case .copyPrompt(let text) = action { return .copy(text) }
        }
        return .preparing
    }

    /// The row's dot and word: green once Cicada saw it call; Waiting after this step connected it; Not connected before.
    static func status(_ row: AgentStepRow, started: Bool) -> (word: String, on: Bool) {
        if row.connected { return (Copy.Status.connected, true) }
        return (started ? Copy.Status.waiting : Copy.Status.notConnected, false)
    }
}

// MARK: Sources

/// One tile of step 4's grid, and what its tick does — exactly what that source's row on the Sources page does.
enum SourceTileKind: Equatable {
    /// Calendar, Contacts, a browser: the one turn-on (`FoundTurnOn`) through `SetupRunner`, as the old Import page
    /// and Home's Getting started run it; its consent is the macOS prompt the entry's own words name.
    case tick(ImportEntry)
    /// Messages and the accounts read through the person's browser: the Sources page's own detail for that entry,
    /// opened over onboarding (`SourceCatalogDetail`), so its consents and switches are the page's.
    case open(SourceCatalogEntry)
    /// A chat export: the window's one drop target, or the file panel.
    case chats
}

struct SourceTile: Identifiable, Equatable {
    let id: String
    let title: String
    let origin: String
    let kind: SourceTileKind
}

enum SourceTiles {
    /// The Sources page's entries the grid opens, in the grid's order.
    static let openIds = ["imessage", "youtube", "x", "instagram"]

    /// The popular ones: Calendar, Contacts, each supported browser on this Mac, Messages, YouTube, X, Instagram,
    /// and chat history. Apple Notes, Wispr Flow, tab groups and the rest stay one click away on the Sources page.
    static func tiles(imports: [ImportEntry]) -> [SourceTile] {
        var out: [SourceTile] = []
        let calendar = imports.first { $0.id == .app(AppSourceDrivers.calendar) }
        let contacts = imports.first { $0.id == .app(AppSourceDrivers.contacts) }
        for entry in [calendar, contacts].compactMap({ $0 }) {
            out.append(SourceTile(id: entry.id.key, title: entry.title, origin: entry.origin, kind: .tick(entry)))
        }
        for entry in imports where entry.category == .browsers && entry.parent == nil {
            out.append(SourceTile(id: entry.id.key, title: entry.title, origin: entry.origin, kind: .tick(entry)))
        }
        for id in openIds {
            guard let entry = SourceCatalog.fixed.first(where: { $0.id == id }) else { continue }
            out.append(SourceTile(id: "open:" + id, title: entry.title, origin: entry.origin, kind: .open(entry)))
        }
        out.append(SourceTile(id: "chats", title: Copy.sourcesChats, origin: "claude-export", kind: .chats))
        return out
    }

    /// A ticked source's dot and word (`SetupProgress`'s phase).
    static func status(phase: SetupRowPhase?) -> (word: String, tone: StatusWord.Tone) {
        switch phase {
        case .comingIn?: (Copy.sourcesComingIn, .on)
        case .done?: (Copy.sourcesOn, .on)
        case .needsYou?: (Copy.sourcesNeedsYou, .attention)
        case .off?, nil: (Copy.sourcesOff, .off)
        }
    }

    /// An opened source's dot and word (the Sources page's own status).
    static func status(catalog: SourceCatalogStatus) -> (word: String, tone: StatusWord.Tone) {
        switch catalog {
        case .connected: (Copy.sourcesOn, .on)
        case .needsSignIn: (Copy.sourcesNeedsYou, .attention)
        case .off: (Copy.sourcesOff, .off)
        }
    }

    /// Chat history's word: what the dropped exports are doing, else what to do.
    static func chatsStatus(phases: [SetupRowPhase]) -> (word: String, tone: StatusWord.Tone) {
        if phases.contains(.comingIn) { return (Copy.sourcesComingIn, .on) }
        if phases.contains(.needsYou) { return (Copy.sourcesNeedsYou, .attention) }
        if phases.contains(.done) { return (Copy.sourcesOn, .on) }
        return (Copy.sourcesDropFile, .off)
    }

    /// The words a tick tile shows before anyone clicks it (owner fix round, 2026-10-22): what it reads and the
    /// consent it leads to, in the Import catalog's own words — "Asks macOS once for your calendars", a browser's
    /// "Bookmarks · History" — and, for a browser macOS hides, that it needs Full Disk Access. Never only a tooltip.
    static func caption(_ entry: ImportEntry, needsAccess: Bool) -> String? {
        if needsAccess { return Copy.sourcesNeedsAccess }
        if let idle = entry.idleLine, idle != Copy.importTickToBringIn { return idle }
        return entry.meta ?? entry.idleLine
    }

    /// Whether a tick tile reads as ticked: running or keeping up (`ImportRows.control`).
    static func isTicked(_ entry: ImportEntry, phase: SetupRowPhase?) -> Bool {
        switch ImportRows.control(entry, phase: phase) {
        case .tick(let on): on
        case .locked, .done: true
        }
    }
}

// MARK: Saved lists

/// One list the person's own agent can keep current from their signed-in browser (G71 YouTube, G206 X, Instagram,
/// LinkedIn) — every list the backend supports (`reading_settings.YOUTUBE_LISTS`, `SAVED_LISTS`), in the step's order.
enum SavedListItem: String, CaseIterable, Identifiable {
    case youtubeWatchLater, youtubeHistory, x, instagram, linkedin

    var id: String { rawValue }

    /// The `PUT /reading/settings` patch this list rides and its key there.
    var family: Family { self == .youtubeWatchLater || self == .youtubeHistory ? .youtube : .saved }
    var key: String {
        switch self {
        case .youtubeWatchLater: YouTubeList.watchLater.rawValue
        case .youtubeHistory: YouTubeList.history.rawValue
        case .x: "x"
        case .instagram: "instagram"
        case .linkedin: "linkedin"
        }
    }

    /// The mark (`OriginIconography`): the platform's own logo.
    var origin: String {
        switch self {
        case .youtubeWatchLater: "youtube-playlist"
        case .youtubeHistory: "youtube-history"
        case .x: "x-bookmarks"
        case .instagram: "instagram-saved"
        case .linkedin: "linkedin-saved"
        }
    }

    var title: String { Copy.savedListsItem(self) }

    enum Family { case youtube, saved }
}

/// The step's rules (owner 2026-10-26, ruling 39's dated line): every list pre-ticked except one the person turned off
/// before (an off is never overridden); the one button's answer is the consent — the ticked lists on with the first-use
/// acknowledgement in the same call, the unticked ones recorded off, so no later default turns them on.
enum SavedListsStepModel {
    static func initialTicks(_ settings: ReadingSettingsResponse?) -> Set<SavedListItem> {
        Set(SavedListItem.allCases.filter { !turnedOff($0, settings) })
    }

    static func turnedOff(_ item: SavedListItem, _ settings: ReadingSettingsResponse?) -> Bool {
        guard let settings else { return false }
        switch item {
        case .youtubeWatchLater: return settings.youtubeListsOff.watchLater
        case .youtubeHistory: return settings.youtubeListsOff.history
        default: return settings.savedListsOff[item.key] == true
        }
    }

    struct Write: Equatable {
        /// Agent reading on, with the acknowledgement: only when something is ticked.
        let consent: Bool
        let youtubeLists: [String: Bool]
        let savedLists: [String: Bool]
    }

    static func write(_ ticked: Set<SavedListItem>) -> Write {
        var youtube: [String: Bool] = [:]
        var saved: [String: Bool] = [:]
        for item in SavedListItem.allCases {
            switch item.family {
            case .youtube: youtube[item.key] = ticked.contains(item)
            case .saved: saved[item.key] = ticked.contains(item)
            }
        }
        return Write(consent: !ticked.isEmpty, youtubeLists: youtube, savedLists: saved)
    }

    /// The foot's one primary: the answer when something is ticked, else simply moving on (the unticked are noted off).
    static func primaryTitle(_ ticked: Set<SavedListItem>) -> String {
        ticked.isEmpty ? Copy.onboardingContinue : Copy.savedListsKeep
    }
}

// MARK: Done

/// Step 5's one line (owner 2026-10-22: a new install consolidates nightly, and once right after onboarding when the
/// person brought something in): "Talk to your agent; Cicada remembers." and what happens next, from real state — the
/// schedule's own time when a schedule can read, "now" only when something came in and an engine can read it, else
/// Read now on Home. Never a promise the schedule does not keep (`OnboardingScheduleLine`'s old lesson).
enum DoneLine {
    /// `nowKey`: the key provider a run started now would bill (the person's own chosen key, e.g. "OpenAI"), said in
    /// words beside "now" — never a metered read the line leaves unnamed (re-review, 2026-10-22).
    static func line(brought: Bool, canReadNow: Bool, scheduleLoaded: Bool, honesty: HonestyInputs,
                     nowKey: String? = nil) -> String {
        Copy.doneLead + (tail(brought: brought, canReadNow: canReadNow, scheduleLoaded: scheduleLoaded,
                              honesty: honesty, nowKey: nowKey).map { " " + $0 } ?? "")
    }

    static func tail(brought: Bool, canReadNow: Bool, scheduleLoaded: Bool, honesty: HonestyInputs,
                     nowKey: String? = nil) -> String? {
        let now = brought && canReadNow
        let nowLine = nowKey.map(Copy.doneImportsNowOnKey) ?? Copy.doneImportsNow
        guard scheduleLoaded else { return now ? nowLine : nil }
        let when = ScheduleHonesty.scheduledCanRead(honesty) ? ScheduleHonesty.whenPhrase(honesty.schedule) : nil
        switch (when, now) {
        case let (when?, true):
            return nowKey.map { Copy.doneScheduledAndNowOnKey(when, $0) } ?? Copy.doneScheduledAndNow(when)
        case let (when?, false): return Copy.doneScheduled(when)
        case (nil, true): return nowLine
        case (nil, false): return Copy.doneReadNow
        }
    }

    /// The key provider a run started now bills, when it reads on a key (`litellm`): the provider's own name.
    static func nowKey(_ response: SleepEngineResponse?) -> String? {
        guard let response, response.preview?.manual.engine == "litellm" else { return nil }
        let id = response.provider ?? byokFallback(response)
        return response.providers.first { $0.id == id }?.label ?? id
    }

    private static func byokFallback(_ response: SleepEngineResponse) -> String? {
        EngineOption.runsOnOpenRouter(response.preview?.manual.model) ? "openrouter" : nil
    }

    /// Open Cicada reads once now when the person brought something in and an engine can read it (owner 2026-10-22) —
    /// a run they started, so ruling 4's scheduled gate does not apply.
    static func readsNow(brought: Bool, canReadNow: Bool) -> Bool { brought && canReadNow }

    /// Something came in during setup: a ticked source or a dropped export that is arriving or arrived.
    static func brought(_ snapshots: [SetupRowSnapshot]) -> Bool {
        snapshots.contains { $0.phase == .comingIn || $0.phase == .done }
    }

    /// An engine a run the person starts can read with (the manual preview names one).
    static func canReadNow(_ response: SleepEngineResponse?) -> Bool {
        guard let engine = response?.preview?.manual.engine else { return false }
        return !["none", "auto", ""].contains(engine)
    }
}
