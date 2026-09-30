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
    var hostKey: String?
    var askable: Bool
    var reason: String?

    enum CodingKeys: String, CodingKey {
        case by, status, tier, at, askedAt, via, harness, note, host, hostKey, askable, reason
    }

    init(status: String = "none", by: String? = nil, tier: String? = nil, at: String? = nil, askedAt: String? = nil,
         via: String? = nil, harness: String? = nil, note: String? = nil, host: String? = nil,
         hostKey: String? = nil, askable: Bool = false, reason: String? = nil) {
        self.status = status
        self.by = by
        self.tier = tier
        self.at = at
        self.askedAt = askedAt
        self.via = via
        self.harness = harness
        self.note = note
        self.host = host
        self.hostKey = hostKey
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
        hostKey = try? c.decodeIfPresent(String.self, forKey: .hostKey)
        askable = (try? c.decode(Bool.self, forKey: .askable)) ?? false
        reason = try? c.decodeIfPresent(String.self, forKey: .reason)
    }
}

/// One of the five sites the person may allow an agent to be asked about (`GET /reading/settings`'s `hostSwitches`).
struct ReadingHostSwitch: Decodable, Equatable, Identifiable {
    var key: String
    var label: String
    var domains: [String]
    var note: String?
    var id: String { key }

    enum CodingKeys: String, CodingKey { case key, label, domains, note }

    init(key: String, label: String, domains: [String] = [], note: String? = nil) {
        self.key = key
        self.label = label
        self.domains = domains
        self.note = note
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        key = try c.decode(String.self, forKey: .key)
        label = (try? c.decode(String.self, forKey: .label)) ?? key
        domains = (try? c.decode([String].self, forKey: .domains)) ?? []
        note = try? c.decodeIfPresent(String.self, forKey: .note)
    }
}

/// `GET|PUT /reading/settings` (G166). Not a Store domain — fetched when Settings → Agents opens, like the fade pace
/// — so no ETag use and no `VersionVector` mapping.
struct ReadingSettingsResponse: Decodable, Equatable {
    var agentEnabled: Bool
    var agentHosts: [String]
    var ackedAt: String?
    var ackCurrent: Bool
    var hostSwitches: [ReadingHostSwitch]
    /// The day of the last read an agent recorded, `nil` until one has.
    var lastAgentRead: String?

    enum CodingKeys: String, CodingKey {
        case agentEnabled, agentHosts, ackedAt, ackCurrent, hostSwitches, lastAgentRead
    }

    init(agentEnabled: Bool = false, agentHosts: [String] = [], ackedAt: String? = nil, ackCurrent: Bool = false,
         hostSwitches: [ReadingHostSwitch] = [], lastAgentRead: String? = nil) {
        self.agentEnabled = agentEnabled
        self.agentHosts = agentHosts
        self.ackedAt = ackedAt
        self.ackCurrent = ackCurrent
        self.hostSwitches = hostSwitches
        self.lastAgentRead = lastAgentRead
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        agentEnabled = (try? c.decode(Bool.self, forKey: .agentEnabled)) ?? false
        agentHosts = (try? c.decode([String].self, forKey: .agentHosts)) ?? []
        ackedAt = try? c.decodeIfPresent(String.self, forKey: .ackedAt)
        ackCurrent = (try? c.decode(Bool.self, forKey: .ackCurrent)) ?? false
        hostSwitches = ((try? c.decode([LossyHostSwitch].self, forKey: .hostSwitches)) ?? []).compactMap(\.value)
        lastAgentRead = try? c.decodeIfPresent(String.self, forKey: .lastAgentRead)
    }
}

private struct LossyHostSwitch: Decodable {
    let value: ReadingHostSwitch?
    init(from decoder: Decoder) throws { value = try? ReadingHostSwitch(from: decoder) }
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
    }

    /// Whether the Feed's detail column draws a Read section: something was recorded or asked, an agent may be asked,
    /// or the link is on a login-walled site (`hostKey`), where the disabled button says which switch is off. An
    /// ordinary page with agent reading off draws nothing: "Ask an agent" is offered only once it is on.
    static func shows(_ read: MediaReadState?) -> Bool {
        guard let read else { return false }
        return read.status != "none" || read.askable || read.hostKey != nil
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
            return Copy.Reading.notRead
        }
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
            if read.askable { return [.ask] }
            if let reason = read.reason, !reason.isEmpty { return [.unavailable(reason: reason)] }
            return []
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
