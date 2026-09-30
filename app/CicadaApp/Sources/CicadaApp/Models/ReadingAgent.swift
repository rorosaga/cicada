import Foundation

/// G166 — how a saved link was read, and whether an agent may be asked to read it: `GET /sources`'s `read` block on a
/// row. Every field is lenient (an older backend sends no block at all, and a value this build cannot read is dropped
/// alone, never the row). `status` is `none`, `waiting`, `ok` or the agent's outcome (`needs_login`, `blocked`,
/// `not_found`, `failed`). `via` is what the agent SAID it read with — self-reported, never proof — and `harness` the
/// connection's label. `askable` false carries the server's own sentence in `reason`, so the app holds no host table.
struct MediaReadState: Codable, Equatable {
    var by: String?
    var status: String
    var tier: String?
    var at: String?
    var askedAt: String?
    var via: String?
    var harness: String?
    var note: String?
    var host: String?
    /// The wall Cicada's own reader hit on this page (`walled`, `login`, `consent`, `refused`), the site it belongs to
    /// (`siteKey`, `siteLabel`), whether the person let an agent read that site (`siteAllowed`) and how the page came to
    /// wait (`queuedBy: site`). All nil for a page the reader opened.
    var wall: String?
    var siteKey: String?
    var siteLabel: String?
    var siteAllowed: Bool
    var queuedBy: String?
    var askable: Bool
    var reason: String?

    enum CodingKeys: String, CodingKey {
        case by, status, tier, at, askedAt, via, harness, note, host, wall, siteKey, siteLabel, siteAllowed, queuedBy
        case askable, reason
    }

    init(status: String = "none", by: String? = nil, tier: String? = nil, at: String? = nil, askedAt: String? = nil,
         via: String? = nil, harness: String? = nil, note: String? = nil, host: String? = nil,
         wall: String? = nil, siteKey: String? = nil, siteLabel: String? = nil, siteAllowed: Bool = false,
         queuedBy: String? = nil, askable: Bool = false, reason: String? = nil) {
        self.status = status
        self.by = by
        self.tier = tier
        self.at = at
        self.askedAt = askedAt
        self.via = via
        self.harness = harness
        self.note = note
        self.host = host
        self.wall = wall
        self.siteKey = siteKey
        self.siteLabel = siteLabel
        self.siteAllowed = siteAllowed
        self.queuedBy = queuedBy
        self.askable = askable
        self.reason = reason
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = (try? c.decode(String.self, forKey: .status)) ?? "none"
        by = try? c.decodeIfPresent(String.self, forKey: .by)
        tier = try? c.decodeIfPresent(String.self, forKey: .tier)
        at = try? c.decodeIfPresent(String.self, forKey: .at)
        askedAt = try? c.decodeIfPresent(String.self, forKey: .askedAt)
        via = try? c.decodeIfPresent(String.self, forKey: .via)
        harness = try? c.decodeIfPresent(String.self, forKey: .harness)
        note = try? c.decodeIfPresent(String.self, forKey: .note)
        host = try? c.decodeIfPresent(String.self, forKey: .host)
        wall = try? c.decodeIfPresent(String.self, forKey: .wall)
        siteKey = try? c.decodeIfPresent(String.self, forKey: .siteKey)
        siteLabel = try? c.decodeIfPresent(String.self, forKey: .siteLabel)
        siteAllowed = (try? c.decode(Bool.self, forKey: .siteAllowed)) ?? false
        queuedBy = try? c.decodeIfPresent(String.self, forKey: .queuedBy)
        askable = (try? c.decode(Bool.self, forKey: .askable)) ?? false
        reason = try? c.decodeIfPresent(String.self, forKey: .reason)
    }
}

/// `GET|PUT /reading/settings` (G166). Not a Store domain — fetched when Settings → Reading the web opens, like the
/// fade pace — so no ETag use and no `VersionVector` mapping. `allowedSites` is `{site: day}`: the sites the person let an
/// agent read (a site is offered to switch on only once Cicada's own reader could not read one of its pages).
struct ReadingSettingsResponse: Decodable, Equatable {
    var agentEnabled: Bool
    var allowedSites: [String: String]
    var ackedAt: String?
    var ackCurrent: Bool
    /// The day of the last read an agent recorded, `nil` until one has.
    var lastAgentRead: String?

    enum CodingKeys: String, CodingKey { case agentEnabled, allowedSites, ackedAt, ackCurrent, lastAgentRead }

    init(agentEnabled: Bool = false, allowedSites: [String: String] = [:], ackedAt: String? = nil,
         ackCurrent: Bool = false, lastAgentRead: String? = nil) {
        self.agentEnabled = agentEnabled
        self.allowedSites = allowedSites
        self.ackedAt = ackedAt
        self.ackCurrent = ackCurrent
        self.lastAgentRead = lastAgentRead
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        agentEnabled = (try? c.decode(Bool.self, forKey: .agentEnabled)) ?? false
        allowedSites = (try? c.decode([String: String].self, forKey: .allowedSites)) ?? [:]
        ackedAt = try? c.decodeIfPresent(String.self, forKey: .ackedAt)
        ackCurrent = (try? c.decode(Bool.self, forKey: .ackCurrent)) ?? false
        lastAgentRead = try? c.decodeIfPresent(String.self, forKey: .lastAgentRead)
    }
}

/// One site Cicada's own reader could not read (`GET /reading/sites`): counts only — never a URL, a title or a note of a
/// page. `wall` is the commonest kind among its waiting pages; `needsLogin` counts pages whose last agent read said it
/// was not signed in; `note` is the server's one sentence for a site with a caveat; `iconHost` is the name the icon
/// service is asked about (never the site itself).
struct ReadingSite: Decodable, Equatable, Identifiable {
    var site: String
    var label: String
    var wall: String?
    var allowed: Bool
    var since: String?
    var waiting: Int
    var read: Int
    var needsLogin: Int
    var note: String?
    var iconHost: String?
    var id: String { site }

    enum CodingKeys: String, CodingKey { case site, label, wall, allowed, since, waiting, read, needsLogin, note, iconHost }

    init(site: String, label: String? = nil, wall: String? = nil, allowed: Bool = false, since: String? = nil,
         waiting: Int = 0, read: Int = 0, needsLogin: Int = 0, note: String? = nil, iconHost: String? = nil) {
        self.site = site
        self.label = label ?? site
        self.wall = wall
        self.allowed = allowed
        self.since = since
        self.waiting = waiting
        self.read = read
        self.needsLogin = needsLogin
        self.note = note
        self.iconHost = iconHost
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        site = try c.decode(String.self, forKey: .site)
        label = (try? c.decode(String.self, forKey: .label)) ?? site
        wall = try? c.decodeIfPresent(String.self, forKey: .wall)
        allowed = (try? c.decode(Bool.self, forKey: .allowed)) ?? false
        since = try? c.decodeIfPresent(String.self, forKey: .since)
        waiting = (try? c.decode(Int.self, forKey: .waiting)) ?? 0
        read = (try? c.decode(Int.self, forKey: .read)) ?? 0
        needsLogin = (try? c.decode(Int.self, forKey: .needsLogin)) ?? 0
        note = try? c.decodeIfPresent(String.self, forKey: .note)
        iconHost = try? c.decodeIfPresent(String.self, forKey: .iconHost)
    }
}

/// `GET /reading/sites`. A row this build cannot read is dropped alone, never the list.
struct ReadingSitesResponse: Decodable, Equatable {
    var sites: [ReadingSite]
    var waitingTotal: Int
    var waitingNotAllowed: Int
    var enabled: Bool

    enum CodingKeys: String, CodingKey { case sites, waitingTotal, waitingNotAllowed, enabled }

    init(sites: [ReadingSite] = [], waitingTotal: Int = 0, waitingNotAllowed: Int = 0, enabled: Bool = false) {
        self.sites = sites
        self.waitingTotal = waitingTotal
        self.waitingNotAllowed = waitingNotAllowed
        self.enabled = enabled
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        sites = ((try? c.decode([Lossy<ReadingSite>].self, forKey: .sites)) ?? []).compactMap(\.value)
        waitingTotal = (try? c.decode(Int.self, forKey: .waitingTotal)) ?? 0
        waitingNotAllowed = (try? c.decode(Int.self, forKey: .waitingNotAllowed)) ?? 0
        enabled = (try? c.decode(Bool.self, forKey: .enabled)) ?? false
    }
}

private struct Lossy<T: Decodable>: Decodable {
    let value: T?
    init(from decoder: Decoder) throws { value = try? T(from: decoder) }
}

// MARK: How your agent reads (`GET|PUT /agent-methods`)

/// The page of a skill in the graph, when it has one: `state` is `present`, `adopted`, `created` or another word the
/// server uses; the app reads only whether an id exists.
struct AgentMethodPage: Decodable, Equatable {
    var id: String
    var state: String?

    enum CodingKeys: String, CodingKey { case id, state }

    init(id: String, state: String? = nil) {
        self.id = id
        self.state = state
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        state = try? c.decodeIfPresent(String.self, forKey: .state)
    }
}

/// One choice of how the person's agent does a job. `kind` is `auto`, `own` or `skill`; a skill is catalog data the
/// person can pick, tagged Skill in its row. `state` is per agent (`installed`, `missing`, …) and `page` the skill's page
/// in the graph. The server sends the whole Skills-card shape for a skill; this build reads only what a row shows.
struct AgentMethodOption: Decodable, Equatable, Identifiable {
    var id: String
    var kind: String
    var title: String
    var detail: String
    var reach: String?
    var cicadaNote: String?
    var state: [String: String]
    var page: AgentMethodPage?
    /// The whole Skills-card shape of a skill option, decoded through `RecommendedSkill`, so "Install…" can open the
    /// skill's own detail from here (a skill ranked below the Skills page's five has no card there). nil for a built-in.
    var skill: RecommendedSkill?

    var isSkill: Bool { kind == "skill" }
    /// Installed for at least one of the agents that can use it.
    var installedAnywhere: Bool { state.values.contains("installed") }

    enum CodingKeys: String, CodingKey { case id, kind, title, detail, reach, cicadaNote, state, page }

    init(id: String, kind: String, title: String, detail: String = "", reach: String? = nil,
         cicadaNote: String? = nil, state: [String: String] = [:], page: AgentMethodPage? = nil,
         skill: RecommendedSkill? = nil) {
        self.id = id
        self.kind = kind
        self.title = title
        self.detail = detail
        self.reach = reach
        self.cicadaNote = cicadaNote
        self.state = state
        self.page = page
        self.skill = skill
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        kind = (try? c.decode(String.self, forKey: .kind)) ?? "skill"
        skill = kind == "skill" ? try? RecommendedSkill(from: decoder) : nil
        title = (try? c.decode(String.self, forKey: .title)) ?? id
        detail = (try? c.decode(String.self, forKey: .detail)) ?? ""
        reach = try? c.decodeIfPresent(String.self, forKey: .reach)
        cicadaNote = try? c.decodeIfPresent(String.self, forKey: .cicadaNote)
        state = (try? c.decode([String: String].self, forKey: .state)) ?? [:]
        page = try? c.decodeIfPresent(AgentMethodPage.self, forKey: .page)
    }
}

struct AgentMethodJob: Decodable, Equatable {
    var job: String
    var question: String
    var chosen: String
    var options: [AgentMethodOption]

    enum CodingKeys: String, CodingKey { case job, question, chosen, options }

    init(job: String, question: String, chosen: String = "auto", options: [AgentMethodOption] = []) {
        self.job = job
        self.question = question
        self.chosen = chosen
        self.options = options
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        job = try c.decode(String.self, forKey: .job)
        question = (try? c.decode(String.self, forKey: .question)) ?? ""
        chosen = (try? c.decode(String.self, forKey: .chosen)) ?? "auto"
        options = ((try? c.decode([Lossy<AgentMethodOption>].self, forKey: .options)) ?? []).compactMap(\.value)
    }
}

/// `GET /agent-methods` — a job per entry (today only `reading`). A `PUT` answers one job plus `write.page`, what the
/// server did about the chosen skill's page (`created`, `adopted`, `exists`, `foreign`, `busy`, `demo`, `none`).
struct AgentMethodsResponse: Decodable, Equatable {
    var jobs: [AgentMethodJob]

    enum CodingKeys: String, CodingKey { case jobs }

    init(jobs: [AgentMethodJob] = []) { self.jobs = jobs }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        jobs = ((try? c.decode([Lossy<AgentMethodJob>].self, forKey: .jobs)) ?? []).compactMap(\.value)
    }

    func job(_ name: String) -> AgentMethodJob? { jobs.first { $0.job == name } }
}

struct AgentMethodWriteResponse: Decodable, Equatable {
    var job: AgentMethodJob
    var pageState: String

    enum CodingKeys: String, CodingKey { case write }
    struct Write: Decodable { var page: String? }

    init(job: AgentMethodJob, pageState: String = "none") {
        self.job = job
        self.pageState = pageState
    }

    init(from decoder: Decoder) throws {
        job = try AgentMethodJob(from: decoder)
        let c = try decoder.container(keyedBy: CodingKeys.self)
        pageState = (try? c.decode(Write.self, forKey: .write))?.page ?? "none"
    }
}

/// What a skill row of "How your agent reads" offers on its right, in order of what is true. Pure: the view and the
/// tests read the same function. A built-in choice offers nothing.
enum MethodRowWords {
    enum Action: Equatable {
        /// The skill has a page in the graph: open it there.
        case openInGraph(String)
        /// Installed for an agent but no page yet: "Add to your graph".
        case addToGraph
        /// Not installed anywhere: "Install…" opens the skill's own detail (its consent sheet or its setup prompt).
        case install
        case none
    }

    static func action(_ option: AgentMethodOption) -> Action {
        guard option.isSkill else { return .none }
        if let page = option.page { return .openInGraph(page.id) }
        if option.installedAnywhere { return .addToGraph }
        return option.skill == nil ? .none : .install
    }

    /// The line under a skill's name: whether it is installed, then what it reaches.
    static func detail(_ option: AgentMethodOption) -> String {
        let reach = option.reach ?? option.detail
        guard option.isSkill else { return option.detail }
        let installed = option.installedAnywhere ? Copy.Reading.skillInstalled : Copy.Reading.skillNotInstalled
        return reach.isEmpty ? installed : "\(installed) · \(reach)"
    }
}

/// The words of a site's row in Settings → Reading the web. Pure: the view and the tests read the same functions.
/// Only measured counts and the server's own sentences; no page, title or URL ever reaches a row.
enum ReadingSiteWords {
    static func countLine(_ site: ReadingSite) -> String {
        if site.waiting > 0 {
            return site.allowed ? Copy.Reading.queued(site.waiting) : Copy.Reading.waitingNotAllowed(site.waiting)
        }
        return site.read > 0 ? Copy.Reading.readCount(site.read) : Copy.Reading.nothingWaiting
    }

    /// The server's caveat for the site, else the wall's plain name.
    static func detail(_ site: ReadingSite) -> String? {
        if let note = site.note?.trimmingCharacters(in: .whitespacesAndNewlines), !note.isEmpty { return note }
        return Copy.Reading.wallWords(site.wall)
    }

    /// An allowed site whose last agent read found the agent signed out: its pages wait until the person signs in and
    /// says "try again" (the server pauses the site for a week).
    static func isPaused(_ site: ReadingSite) -> Bool { site.allowed && site.needsLogin > 0 }
}

/// `POST /reading/asks` — only the hand-off sentence is read; the ask itself lands on the link's `read` block over the
/// `reading` sync component.
struct ReadingAskResponse: Decodable, Equatable {
    var prompt: String
    var saved: Bool

    enum CodingKeys: String, CodingKey { case prompt, saved }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        prompt = (try? c.decode(String.self, forKey: .prompt)) ?? ""
        saved = (try? c.decode(Bool.self, forKey: .saved)) ?? false
    }
}

/// The words for a link's `read` block, and which controls it offers. Pure: the Feed's detail column and the tests
/// read the same functions. Only known facts, and no more — Cicada cannot know an agent used a browser, so no line
/// says "in your browser" (spec §7.5).
enum ReadWords {
    enum Action: Equatable {
        /// "Ask an agent" — the first ask, on a link nobody has asked about.
        case ask
        /// "Ask again" — after an outcome (a wall, a block, a failure) the person wants retried.
        case askAgain
        /// The link cannot be asked about now; the button is drawn disabled and says why on hover (DR-41).
        case unavailable(reason: String)
        /// "Open in browser" — the person signs in themselves; the app opens the link and nothing more.
        case openInBrowser
        /// "Copy for an agent" — the prompt for a link that is waiting.
        case copyForAgent
        /// "Let an agent read <site>" — the site's switch, from a page Cicada's reader could not open. With agent
        /// reading off it raises the first-use sheet, like the switch in Settings.
        case allowSite(site: String, label: String)
    }

    /// Whether the Feed's detail column draws a Read section: something was recorded or asked, an agent may be asked,
    /// or Cicada's own reader hit a wall on the page (`wall`), where the disabled button says why. An ordinary page
    /// with agent reading off draws nothing: "Ask an agent" is offered only once it is on.
    static func shows(_ read: MediaReadState?) -> Bool {
        guard let read else { return false }
        return read.status != "none" || read.askable || read.wall != nil
    }

    /// Who read it, in words: the connection's own label when it sent one.
    static func reader(_ read: MediaReadState) -> String {
        if let harness = read.harness?.trimmingCharacters(in: .whitespaces), !harness.isEmpty {
            return ReadWords.harnessName(harness)
        }
        return Copy.Reading.anAgent
    }

    /// A connection label as the app names it (`claude-code` reads as "Claude Code").
    static func harnessName(_ raw: String) -> String {
        let names = ["claude-code": "Claude Code", "codex": "Codex", "claude-web": "Claude", "chatgpt": "ChatGPT",
                     "cursor": "Cursor", "gemini": "Gemini"]
        if let known = names[raw.lowercased()] { return known }
        return raw.replacingOccurrences(of: "-", with: " ").replacingOccurrences(of: "_", with: " ")
    }

    /// The status sentence. `day` is the already-formatted absolute day of `at`, or `nil`.
    static func line(_ read: MediaReadState, day: String?) -> String {
        let host = (read.host?.isEmpty == false) ? read.host! : Copy.Reading.thisSite
        switch read.status {
        case "waiting":
            if read.siteAllowed, read.queuedBy == "site" {
                return Copy.Reading.siteAllowedWaiting(siteName(read))
            }
            return Copy.Reading.waiting
        case "ok":
            let who = read.by == "agent" ? reader(read) : Copy.Reading.cicadasReader
            return day.map { Copy.Reading.readBy(who, $0) } ?? Copy.Reading.readBy(who)
        case "needs_login":
            return Copy.Reading.needsLogin(host)
        case "blocked":
            return Copy.Reading.blocked(host)
        case "not_found":
            return Copy.Reading.notFound
        case "failed":
            return Copy.Reading.failed
        default:
            if let wall = read.wall { return Copy.Reading.wallLine(wall) }
            return Copy.Reading.notRead
        }
    }

    /// The site's name as the sites list shows it, else its key, else the host.
    static func siteName(_ read: MediaReadState) -> String {
        for candidate in [read.siteLabel, read.siteKey, read.host] {
            if let value = candidate?.trimmingCharacters(in: .whitespaces), !value.isEmpty { return value }
        }
        return Copy.Reading.thisSite
    }

    /// The controls, in order. A waiting ask offers the hand-off prompt; a wall offers the browser first; a link that
    /// cannot be asked about says why instead of hiding the row.
    static func actions(_ read: MediaReadState) -> [Action] {
        switch read.status {
        case "waiting":
            return [.copyForAgent]
        case "needs_login":
            return read.askable ? [.openInBrowser, .askAgain] : [.openInBrowser]
        case "blocked", "not_found", "failed":
            return read.askable ? [.askAgain] : []
        case "ok":
            return read.askable ? [.askAgain] : []
        default:
            var actions: [Action] = []
            if read.askable {
                actions.append(.ask)
            } else if let reason = read.reason, !reason.isEmpty {
                actions.append(.unavailable(reason: reason))
            }
            // A page Cicada's reader could not open offers its site's switch, until the site is allowed.
            if read.wall != nil, !read.siteAllowed, let key = read.siteKey?.trimmingCharacters(in: .whitespaces),
               !key.isEmpty {
                actions.append(.allowSite(site: key, label: siteName(read)))
            }
            return actions
        }
    }

    /// The Feed row's flag: only a login wall an agent reported. Any other outcome stays in the detail column.
    static func rowFlag(_ read: MediaReadState?) -> String? {
        read?.status == "needs_login" ? Copy.Reading.rowFlag : nil
    }

    /// The ids of the links currently behind a login wall.
    static func walledIds(_ items: [MediaFeedItem]) -> Set<String> {
        Set(items.filter { $0.read?.status == "needs_login" }.map(\.id))
    }

    /// What changed since the last look: the new wall set and the links that just hit one. `previous == nil` is the
    /// first look (a launch, or after a bank switch) and announces nothing, so old walls never toast on startup.
    static func newlyWalled(previous: Set<String>?, items: [MediaFeedItem]) -> (current: Set<String>, fresh: [MediaFeedItem]) {
        let current = walledIds(items)
        guard let previous else { return (current, []) }
        return (current, items.filter { current.contains($0.id) && !previous.contains($0.id) })
    }

    /// The toast for links that just hit a wall, or nil when none did.
    static func walledToast(_ fresh: [MediaFeedItem]) -> String? {
        guard !fresh.isEmpty else { return nil }
        let hosts = fresh.map { ($0.read?.host).flatMap { $0.isEmpty ? nil : $0 } ?? Copy.Reading.thisSite }
        return Copy.Reading.walledToast(fresh.count == 1 ? [hosts[0]] : hosts)
    }

    /// The agent's own note on a link, marked as its words, or nil.
    static func agentNoteLine(_ read: MediaReadState) -> String? {
        guard read.by == "agent", let note = read.note?.trimmingCharacters(in: .whitespacesAndNewlines),
              !note.isEmpty else { return nil }
        return Copy.Reading.agentNote(reader(read), note)
    }

    /// Only a web link is ever opened in a browser (never a file path or a custom scheme).
    static func browserURL(_ raw: String) -> URL? {
        guard let url = URL(string: raw), let scheme = url.scheme?.lowercased(),
              scheme == "http" || scheme == "https", url.host != nil else { return nil }
        return url
    }

    /// An absolute day for a stored timestamp (`2026-09-29T12:01:00Z` or a bare `2026-09-29`), or `nil`.
    static func day(_ iso: String?, locale: Locale = .autoupdatingCurrent,
                    timeZone: TimeZone = .autoupdatingCurrent) -> String? {
        guard let iso, !iso.isEmpty else { return nil }
        let full = ISO8601DateFormatter()
        full.formatOptions = [.withInternetDateTime]
        let bare = DateFormatter()
        bare.dateFormat = "yyyy-MM-dd"
        bare.timeZone = TimeZone(identifier: "UTC")
        guard let date = full.date(from: iso) ?? bare.date(from: String(iso.prefix(10))) else { return nil }
        var style = Date.FormatStyle().day().month(.abbreviated)
        style.locale = locale
        style.timeZone = timeZone
        return date.formatted(style)
    }
}
