import Foundation

// G139 — the small wire and pure pieces behind You, Privacy & data, Memory
// and Advanced. Every field optional-with-default so an older backend decodes.

/// `GET /maintenance/search-index` and its rebuild (Task 5). `state` is
/// `search_index.ensure_fresh`'s own word — `ready|stale|building|unavailable`.
struct SearchIndexStatus: Codable, Equatable {
    var state: String
    var builtAt: String? = nil
    var documents: Int? = nil
}

/// The part of `POST /maintenance/enrich-links`' report the Memory page says
/// out loud; the rest of `MaintenanceEnrichLinksResponse` is ignored.
struct EnrichLinksReport: Codable, Equatable {
    var selected: Int = 0
    var summarized: Int = 0
    var fetched: Int = 0
    var failed: Int = 0
    var remaining: Int = 0

    init(selected: Int = 0, summarized: Int = 0, fetched: Int = 0, failed: Int = 0, remaining: Int = 0) {
        self.selected = selected; self.summarized = summarized; self.fetched = fetched
        self.failed = failed; self.remaining = remaining
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        selected = (try? c.decode(Int.self, forKey: .selected)) ?? 0
        summarized = (try? c.decode(Int.self, forKey: .summarized)) ?? 0
        fetched = (try? c.decode(Int.self, forKey: .fetched)) ?? 0
        failed = (try? c.decode(Int.self, forKey: .failed)) ?? 0
        remaining = (try? c.decode(Int.self, forKey: .remaining)) ?? 0
    }
}

/// `DELETE /banks/{name}` (R-O19): the roster after the move and where the
/// bank went, relative to the memory folder.
struct BankTrashResult: Decodable {
    let banks: [MemoryBank]
    let active: String?
    let trashedTo: String

    enum CodingKeys: String, CodingKey { case banks, active, trashedTo }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        banks = (try? c.decode([MemoryBank].self, forKey: .banks)) ?? []
        active = try c.decodeIfPresent(String.self, forKey: .active)
        trashedTo = (try? c.decode(String.self, forKey: .trashedTo)) ?? ""
    }
}

/// The You page's edits. `PUT /settings/owner` rewrites and commits the owner's
/// page, so only a real change is ever sent, and never a blank name (the
/// backend 400s on it).
struct OwnerDraft: Equatable {
    var name = ""
    var handle = ""
    var email = ""

    init() {}
    init(_ saved: OwnerSettings) {
        name = saved.name
        handle = saved.handle ?? ""
        email = saved.email ?? ""
    }

    func update(from saved: OwnerSettings?) -> (name: String, handle: String?, email: String?)? {
        func clean(_ s: String) -> String? {
            let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
            return t.isEmpty ? nil : t
        }
        guard let n = clean(name) else { return nil }
        let h = clean(handle), e = clean(email)
        if let saved, saved.name == n, saved.handle == h, saved.email == e { return nil }
        return (n, h, e)
    }
}

/// Plain words for every env switch `api/services/env_overrides.py` can report
/// (`CicadaPagesTests` holds the two lists together).
enum EnvOverrideCopy {
    static func meaning(_ name: String) -> String? {
        switch name {
        case "CICADA_LLM_MODE": "Pins the engine for every cycle, even on the schedule."
        case "CICADA_AGENT_MODEL": "Chooses the Claude model the plan engine uses."
        case "CICADA_CODEX_MODEL": "Chooses the ChatGPT model the plan engine uses."
        case "CICADA_OLLAMA_MODEL": "Chooses the Ollama model."
        case "CICADA_CONSOLIDATION_MODEL": "Chooses the model an API key uses."
        case "CICADA_EMBEDDING_MODE": "Changes how search understands meaning."
        case "CICADA_MEMORY_PATH", "CICADA_MEMORY_ROOT": "Where your memory lives."
        case "CICADA_HOME": "Where Cicada keeps its own files — keys, token, logs."
        case "CICADA_API_TOKEN": "Replaces the saved API token."
        case "CICADA_API_AUTH": "Turns the API token check off. Only for testing."
        case "CICADA_TELEMETRY": "Turns the usage ledger on or off."
        case "CICADA_ALLOW_CONNECTOR_FETCH": "Lets the nightly connector check reach the internet."
        case "CICADA_ALLOW_FEED_FETCH": "Lets Cicada check your feeds and calendars."
        case "CICADA_ALLOW_LOGO_FETCH": "Lets Cicada fetch logos for your pages."
        case "CICADA_OBSERVER_OWNER": "Names whose words count as yours."
        case "CICADA_REMOTE_PORT": "Changes the port From anywhere listens on."
        case "CICADA_AGENT_ALLOW_OVERAGE": "Lets a Claude cycle keep going on extra usage."
        default: nil
        }
    }
}

/// The Memory page's two status lines, pure so they are tested in words.
enum MemoryMaintenanceText {
    static func index(_ status: SearchIndexStatus?, now: Date = Date()) -> String? {
        guard let status else { return nil }
        switch status.state {
        case "ready":
            guard let built = StatusSnapshot.parseDate(status.builtAt) else { return "Up to date." }
            let ago = RelativeDateTimeFormatter().localizedString(for: built, relativeTo: now)
            return "Up to date · rebuilt \(ago)"
        case "stale": return "Catching up with your latest pages…"
        case "building": return "Building for the first time…"
        default: return "Not available on this Mac — search still works from your pages."
        }
    }

    static func links(_ report: EnrichLinksReport, locale: Locale = .autoupdatingCurrent) -> String {
        if report.summarized == 0 && report.remaining == 0 {
            return "Nothing to fetch — every saved link has a description."
        }
        let done = "Described \(UsageFormat.count(report.summarized, locale: locale)) \(report.summarized == 1 ? "link" : "links")"
        return report.remaining > 0
            ? "\(done) · \(UsageFormat.count(report.remaining, locale: locale)) still to go"
            : done
    }
}
