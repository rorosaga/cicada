import Foundation

// MARK: - "Where this comes from" (owner 2026-10-14, G61)
//
// One place on a page that answers where Cicada's knowledge about it comes from and how fresh it is: the sources (each
// with the beliefs it backs), the links its conversations named, and those conversations by app. Served whole by
// `GET /entities/{id}/sources/overview` (`api/services/page_sources.py`) — the card never reads the claims list to draw
// it. On demand, ETag-revalidated through `ProvenanceCache`, never a Store domain (R-PB11). Every decoder is tolerant:
// a field an older backend lacks reads as empty, never as a failed card.

/// One current belief a source backs: the sentence, and the key its Timeline opens.
struct PageSourceFact: Codable, Hashable, Identifiable {
    let claimId: String
    let text: String
    let predicate: String
    let context: String

    var id: String { claimId }
    var key: BeliefKey { BeliefKey(predicate: predicate, context: context) }

    init(claimId: String, text: String, predicate: String = "", context: String = "general") {
        self.claimId = claimId
        self.text = text
        self.predicate = predicate
        self.context = context
    }

    enum CodingKeys: String, CodingKey { case claimId, text, predicate, context }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        claimId = try c.decode(String.self, forKey: .claimId)
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
        predicate = try c.decodeIfPresent(String.self, forKey: .predicate) ?? ""
        context = try c.decodeIfPresent(String.self, forKey: .context) ?? "general"
    }
}

/// A `sources:` entry exactly as `GET /entities/{id}/sources` serves it (`source`), plus what the card says about it.
struct PageSource: Decodable, Hashable, Identifiable {
    /// What it backs: one fact (a predicate), the official-site role, or the page as a whole (no predicate).
    enum Scope: String, Hashable { case fact, site, page }

    let source: EntitySource
    /// The site key (`reading_hosts.site_of`) of a url source — what its mark is asked by; nil for anything else.
    let site: String?
    /// The title the page's own `## Links` gives this URL, when it gives one.
    let title: String?
    let scope: Scope
    /// The current beliefs it backs, newest first, at most four; `factCount` is all of them.
    let facts: [PageSourceFact]
    let factCount: Int

    var id: String { source.id }

    init(source: EntitySource, site: String? = nil, title: String? = nil, scope: Scope = .page,
         facts: [PageSourceFact] = [], factCount: Int? = nil) {
        self.source = source
        self.site = site
        self.title = title
        self.scope = scope
        self.facts = facts
        self.factCount = factCount ?? facts.count
    }

    enum CodingKeys: String, CodingKey { case site, title, scope, facts, factCount }

    init(from decoder: Decoder) throws {
        source = try EntitySource(from: decoder)
        let c = try decoder.container(keyedBy: CodingKeys.self)
        site = try c.decodeIfPresent(String.self, forKey: .site)
        title = try c.decodeIfPresent(String.self, forKey: .title)
        scope = (try c.decodeIfPresent(String.self, forKey: .scope)).flatMap(Scope.init(rawValue:)) ?? .page
        facts = (try? c.decodeIfPresent([PageSourceFact].self, forKey: .facts)) ?? []
        factCount = try c.decodeIfPresent(Int.self, forKey: .factCount) ?? facts.count
    }
}

/// The conversation a `## Links` line came from: what the Reader opens.
struct PageLinkOrigin: Decodable, Hashable {
    let episode: String
    let title: String
    let harness: String?
    let origin: String?
    let said: String?
    let available: Bool
    let evidence: Evidence?

    init(episode: String, title: String = "", harness: String? = nil, origin: String? = nil, said: String? = nil,
         available: Bool = true, evidence: Evidence? = nil) {
        self.episode = episode
        self.title = title
        self.harness = harness
        self.origin = origin
        self.said = said
        self.available = available
        self.evidence = evidence
    }

    enum CodingKeys: String, CodingKey { case episode, title, harness, origin, said, available, evidence }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episode = try c.decode(String.self, forKey: .episode)
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        harness = try c.decodeIfPresent(String.self, forKey: .harness)
        origin = try c.decodeIfPresent(String.self, forKey: .origin)
        said = try c.decodeIfPresent(String.self, forKey: .said)
        available = try c.decodeIfPresent(Bool.self, forKey: .available) ?? true
        evidence = try? c.decodeIfPresent(Evidence.self, forKey: .evidence)
    }
}

/// A link from the page's `## Links` that is not one of its sources.
struct PageLink: Decodable, Hashable, Identifiable {
    let url: String
    let title: String
    let site: String?
    let note: String?
    let cameFrom: PageLinkOrigin?

    var id: String { url }
    var link: URL? { URL(string: url) }

    init(url: String, title: String = "", site: String? = nil, note: String? = nil, cameFrom: PageLinkOrigin? = nil) {
        self.url = url
        self.title = title
        self.site = site
        self.note = note
        self.cameFrom = cameFrom
    }

    enum CodingKeys: String, CodingKey { case url, title, site, note, cameFrom }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        url = try c.decode(String.self, forKey: .url)
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        site = try c.decodeIfPresent(String.self, forKey: .site)
        note = try c.decodeIfPresent(String.self, forKey: .note)
        cameFrom = try? c.decodeIfPresent(PageLinkOrigin.self, forKey: .cameFrom)
    }
}

/// The conversations that fed a page from one app.
struct PageSourceApp: Decodable, Hashable, Identifiable {
    let harness: String?
    let origin: String?
    let source: String?
    let conversations: Int
    let facts: Int
    let passages: Int
    let lastSaid: String?

    var id: String { harness ?? origin ?? "" }

    init(harness: String? = nil, origin: String? = nil, source: String? = nil, conversations: Int = 0, facts: Int = 0,
         passages: Int = 0, lastSaid: String? = nil) {
        self.harness = harness
        self.origin = origin
        self.source = source
        self.conversations = conversations
        self.facts = facts
        self.passages = passages
        self.lastSaid = lastSaid
    }

    enum CodingKeys: String, CodingKey { case harness, origin, source, conversations, facts, passages, lastSaid }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        harness = try c.decodeIfPresent(String.self, forKey: .harness)
        origin = try c.decodeIfPresent(String.self, forKey: .origin)
        source = try c.decodeIfPresent(String.self, forKey: .source)
        conversations = try c.decodeIfPresent(Int.self, forKey: .conversations) ?? 0
        facts = try c.decodeIfPresent(Int.self, forKey: .facts) ?? 0
        passages = try c.decodeIfPresent(Int.self, forKey: .passages) ?? 0
        lastSaid = try c.decodeIfPresent(String.self, forKey: .lastSaid)
    }
}

struct PageConversations: Decodable, Hashable {
    let total: Int
    let firstSaid: String?
    let lastSaid: String?
    let apps: [PageSourceApp]

    init(total: Int = 0, firstSaid: String? = nil, lastSaid: String? = nil, apps: [PageSourceApp] = []) {
        self.total = total
        self.firstSaid = firstSaid
        self.lastSaid = lastSaid
        self.apps = apps
    }

    enum CodingKeys: String, CodingKey { case total, firstSaid, lastSaid, apps }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        total = try c.decodeIfPresent(Int.self, forKey: .total) ?? 0
        firstSaid = try c.decodeIfPresent(String.self, forKey: .firstSaid)
        lastSaid = try c.decodeIfPresent(String.self, forKey: .lastSaid)
        apps = (try? c.decodeIfPresent([PageSourceApp].self, forKey: .apps)) ?? []
    }
}

/// `GET /entities/{id}/sources/overview`.
struct PageSourcesOverview: Decodable, Hashable {
    let entityId: String
    let entityType: String
    let sources: [PageSource]
    let links: [PageLink]
    let linksTotal: Int
    let conversations: PageConversations
    let factsTotal: Int
    let factsWithSource: Int
    let lastChecked: String?

    init(entityId: String, entityType: String = "", sources: [PageSource] = [], links: [PageLink] = [],
         linksTotal: Int? = nil, conversations: PageConversations = PageConversations(), factsTotal: Int = 0,
         factsWithSource: Int = 0, lastChecked: String? = nil) {
        self.entityId = entityId
        self.entityType = entityType
        self.sources = sources
        self.links = links
        self.linksTotal = linksTotal ?? links.count
        self.conversations = conversations
        self.factsTotal = factsTotal
        self.factsWithSource = factsWithSource
        self.lastChecked = lastChecked
    }

    enum CodingKeys: String, CodingKey {
        case entityId, entityType, sources, links, linksTotal, conversations, factsTotal, factsWithSource, lastChecked
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        entityId = try c.decode(String.self, forKey: .entityId)
        entityType = try c.decodeIfPresent(String.self, forKey: .entityType) ?? ""
        sources = try c.decodeIfPresent([PageSource].self, forKey: .sources) ?? []
        links = (try? c.decodeIfPresent([PageLink].self, forKey: .links)) ?? []
        linksTotal = try c.decodeIfPresent(Int.self, forKey: .linksTotal) ?? links.count
        conversations = (try? c.decodeIfPresent(PageConversations.self, forKey: .conversations)) ?? PageConversations()
        factsTotal = try c.decodeIfPresent(Int.self, forKey: .factsTotal) ?? 0
        factsWithSource = try c.decodeIfPresent(Int.self, forKey: .factsWithSource) ?? 0
        lastChecked = try c.decodeIfPresent(String.self, forKey: .lastChecked)
    }

    /// The sources' backing, by `EntitySource.id` — a source row finds what it backs after an edit replaced the list.
    func backing(_ source: EntitySource) -> PageSource? {
        sources.first { $0.id == source.id }
    }

    /// The sources a belief can be looked up at, best first: those for its own fact (the person's, then one they took
    /// or Cicada's read confirmed, then the rest — `fact_sources.rank`'s order), never the page-wide or official-site
    /// ones, which back no one fact. The way back from a belief to where to check it.
    func lookUps(predicate: String) -> [PageSource] {
        let key = predicate.trimmingCharacters(in: .whitespaces).lowercased()
        guard !key.isEmpty else { return [] }
        let matching = sources.filter { $0.scope == .fact && ($0.source.predicate ?? "").lowercased() == key }
        return matching.enumerated().sorted { a, b in
            let (ra, rb) = (Self.rank(a.element.source), Self.rank(b.element.source))
            return ra != rb ? ra < rb : a.offset < b.offset
        }.map(\.element)
    }

    private static func rank(_ s: EntitySource) -> Int {
        let who = s.addedBy.trimmingCharacters(in: .whitespaces)
        if who.isEmpty || who == "user" { return 0 }
        if s.accepted == true || s.verified != nil { return 1 }
        return who == ContributorIdentity.systemAuthor ? 2 : 3
    }
}

// MARK: - Words

/// Everything "Where this comes from" says, pure and tested. Dates go through the app's one formatter; relative words
/// are computed when read (DR-58); names of apps through `ProvenanceSummary.placeName` (DR-54).
enum PageSourcesWords {
    /// A closed section's few words: "· 2 sources · 3 conversations". Nil until something is known.
    static func summary(_ o: PageSourcesOverview?, conversations fallback: Int? = nil) -> String? {
        let sources = o?.sources.count ?? 0
        let conversations = o?.conversations.total ?? fallback ?? 0
        var parts: [String] = []
        if sources > 0 { parts.append(Copy.PageSources.sources(sources)) }
        if conversations > 0 { parts.append(Copy.Provenance.conversations(conversations)) }
        if o == nil, fallback == nil { return nil }
        return parts.isEmpty ? Copy.PageSources.nothingYetSummary : "· " + parts.joined(separator: " · ")
    }

    /// "6 of 7 facts have a place to check them." Nil on a page with no beliefs.
    static func coverage(_ o: PageSourcesOverview) -> String? {
        guard o.factsTotal > 0 else { return nil }
        if o.factsWithSource == 0 { return Copy.PageSources.noFactCheckable(o.factsTotal) }
        if o.factsWithSource >= o.factsTotal { return Copy.PageSources.everyFactCheckable(o.factsTotal) }
        return Copy.PageSources.someFactsCheckable(o.factsWithSource, of: o.factsTotal)
    }

    /// "Last said Sep 3 · sources last checked Oct 5" — when the newest conversation was said and when Cicada's own
    /// read last looked at a source. Nil when neither is known.
    static func freshness(_ o: PageSourcesOverview, locale: Locale = .autoupdatingCurrent) -> String? {
        var parts: [String] = []
        if let said = EntityDates.shortDay(o.conversations.lastSaid, locale: locale) {
            parts.append(Copy.PageSources.lastSaid(said))
        }
        if let checked = EntityDates.shortDay(o.lastChecked, locale: locale) {
            parts.append(parts.isEmpty ? Copy.PageSources.checkedFirst(checked) : Copy.PageSources.checked(checked))
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// What a group of sources for one fact backs: "Backs 5 beliefs" / "No current belief yet". Nil for the official
    /// site and the page-wide group, whose own title already says what they are for (DR-38).
    static func backs(_ s: PageSource) -> String? {
        guard s.scope == .fact else { return nil }
        return s.factCount == 0 ? Copy.PageSources.backsNothingYet : Copy.PageSources.backs(s.factCount)
    }

    /// "and 3 more" under a capped fact list; nil when every backed belief is shown.
    static func moreFacts(_ s: PageSource) -> String? {
        let more = s.factCount - s.facts.count
        return more > 0 ? Copy.PageSources.andMore(more) : nil
    }

    /// A link named in a conversation leads the same way as a source: its title, else its host; the URL second.
    static func linkTitle(_ l: PageLink) -> String {
        let named = l.title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard named.isEmpty else { return named }
        guard let host = l.link?.host?.lowercased(), !host.isEmpty else { return l.url }
        return host.hasPrefix("www.") ? String(host.dropFirst(4)) : host
    }

    /// A link's note, as the page's line gives it ("how the launch went"); nil when it gives none.
    static func linkNote(_ l: PageLink) -> String? {
        let note = l.note?.trimmingCharacters(in: .whitespaces) ?? ""
        return note.isEmpty ? nil : note
    }

    /// The conversation that named a link, the way a person would (DR-54): "Claude Code · Launch plan · Sep 3", or
    /// "a Claude Code conversation · Sep 3" without a title.
    static func cameFrom(_ origin: PageLinkOrigin, locale: Locale = .autoupdatingCurrent) -> String {
        let place = ProvenanceSummary.placeName(harness: origin.harness, origin: origin.origin)
        let day = ReaderTime.day(timestamp: origin.said, episode: origin.episode, locale: locale, withYear: false)
        let head = origin.title.trimmingCharacters(in: .whitespaces).isEmpty
            ? Copy.PageSources.aConversation(in: place) : "\(place) · \(origin.title)"
        return day.map { "\(head) · \($0)" } ?? head
    }

    /// One app's line: "2 conversations · 5 beliefs · 2 passages · last Sep 3".
    static func appDetail(_ a: PageSourceApp, locale: Locale = .autoupdatingCurrent) -> String {
        var parts = [Copy.Provenance.conversations(a.conversations)]
        if a.facts > 0 { parts.append(Copy.Provenance.beliefs(a.facts)) }
        if a.passages > 0 { parts.append(Copy.PageSources.passages(a.passages)) }
        if let day = EntityDates.shortDay(a.lastSaid, locale: locale) { parts.append(Copy.PageSources.last(day)) }
        return parts.joined(separator: " · ")
    }

    static func appName(_ a: PageSourceApp) -> String {
        let name = ProvenanceSummary.placeName(harness: a.harness, origin: a.origin)
        return name.prefix(1).uppercased() + name.dropFirst()
    }

    /// The chip a belief wears when a source backs its fact: "Check at example.org", else the kind in words. It says
    /// where to check, never that anything was checked (S3 is shadow).
    static func lookUpChip(_ s: PageSource) -> String {
        if let site = s.site, !site.isEmpty { return Copy.PageSources.checkAt(site) }
        switch s.source.kind {
        case "path", "repo": return Copy.PageSources.chipFile
        case "app": return Copy.PageSources.chipApp
        default: return Copy.PageSources.chipNote
        }
    }

    /// What a source row leads with (review polish, 2026-10-14): a link reads as its site's name — the title the page
    /// already holds for it (its `## Links` line, or the saved page it is linked to), else its host — with the full
    /// URL as the secondary line. Anything that is not a link keeps its own words and no second line.
    static func heading(_ s: EntitySource, title: String?) -> (title: String, url: String?) {
        guard let url = s.url, let host = url.host?.lowercased(), !host.isEmpty else { return (s.ref, nil) }
        let named = title?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let shown = named.isEmpty ? (host.hasPrefix("www.") ? String(host.dropFirst(4)) : host) : named
        return (shown, s.ref)
    }

    /// The scroll anchor of a source row, so a belief's chip can land on it.
    static func anchor(_ sourceId: String) -> String { "page-source-\(sourceId)" }
}
