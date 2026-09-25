import Foundation

// MARK: - GET /entities/{id}/provenance (G118 slice 2, design §4.5 / §4.8.4)
//
// "Where this came from" in one call — contributors, the conversations that
// fed the page with their best quote, and coverage stated honestly. Every
// field is optional-with-default: a backend without the route 404s (the
// section hides), and one that ships fewer fields still decodes (R10).

/// The one quote a provenance row shows (`ProvenanceSpan`). `kind` is the
/// stored evidence kind or `derived`; `start`/`end` are absolute offsets to
/// wash and are nil when `stale` (R-PB2). `excerpt` is ±240 chars cut on word
/// boundaries; `excerptStart` is its absolute offset and `mentionOffsets` are
/// RELATIVE to it — the inbox cause's shape (G115).
struct ProvenanceSpan: Codable, Hashable {
    let episode: String
    let start: Int?
    let end: Int?
    let hash: String
    let kind: EvidenceKind
    let excerpt: String
    let excerptStart: Int
    let mentionOffsets: [[Int]]
    let stale: Bool
    let grown: Bool
    let derived: Bool

    init(episode: String, start: Int?, end: Int?, hash: String = "", kind: EvidenceKind,
         excerpt: String, excerptStart: Int = 0, mentionOffsets: [[Int]] = [],
         stale: Bool = false, grown: Bool = false, derived: Bool = false) {
        self.episode = episode
        self.start = start
        self.end = end
        self.hash = hash
        self.kind = kind
        self.excerpt = excerpt
        self.excerptStart = excerptStart
        self.mentionOffsets = mentionOffsets
        self.stale = stale
        self.grown = grown
        self.derived = derived
    }

    enum CodingKeys: String, CodingKey {
        case episode, start, end, hash, kind, excerpt, excerptStart, mentionOffsets, stale, grown, derived
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episode = try c.decodeIfPresent(String.self, forKey: .episode) ?? ""
        start = try c.decodeIfPresent(Int.self, forKey: .start)
        end = try c.decodeIfPresent(Int.self, forKey: .end)
        hash = try c.decodeIfPresent(String.self, forKey: .hash) ?? ""
        kind = try c.decodeIfPresent(EvidenceKind.self, forKey: .kind) ?? .derived
        excerpt = try c.decodeIfPresent(String.self, forKey: .excerpt) ?? ""
        excerptStart = try c.decodeIfPresent(Int.self, forKey: .excerptStart) ?? 0
        mentionOffsets = try c.decodeIfPresent([[Int]].self, forKey: .mentionOffsets) ?? []
        stale = try c.decodeIfPresent(Bool.self, forKey: .stale) ?? false
        grown = try c.decodeIfPresent(Bool.self, forKey: .grown) ?? false
        derived = try c.decodeIfPresent(Bool.self, forKey: .derived) ?? false
    }

    /// A derived match is never "You said" (§4.9): the kind the chip renders
    /// is `derived` whenever the server says the words were found by name.
    var displayKind: EvidenceKind { derived ? .derived : kind }
}

/// One author of an entity (`ProvenanceContributor`, R-PB6): `claims` =
/// current claims with that `authored_by`; `commits` = commits that touched
/// the page with that `Cicada-Author`. `kind`/`provider` come from the one
/// `git_service.author_identity` rule, so the app never re-derives them.
struct ProvenanceContributor: Codable, Hashable, Identifiable {
    let author: String
    let kind: String
    let provider: String?
    let claims: Int
    let commits: Int
    /// Round-4 C4 (D1) — on a `harness` contributor, the models its beliefs were
    /// written with, joined to their turns at read. `[]` for every other kind,
    /// before D1, and for an app that never tells its model.
    let models: [ContributorModel]

    var id: String { author }

    init(author: String, kind: String, provider: String? = nil, claims: Int = 0, commits: Int = 0,
         models: [ContributorModel] = []) {
        self.author = author
        self.kind = kind
        self.provider = provider
        self.claims = claims
        self.commits = commits
        self.models = models
    }

    enum CodingKeys: String, CodingKey { case author, kind, provider, claims, commits, models }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        author = try c.decodeIfPresent(String.self, forKey: .author) ?? "unknown"
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "unknown"
        provider = try c.decodeIfPresent(String.self, forKey: .provider)
        claims = try c.decodeIfPresent(Int.self, forKey: .claims) ?? 0
        commits = try c.decodeIfPresent(Int.self, forKey: .commits) ?? 0
        // `try?`: a mistyped list from a backend a shape ahead must not drop the
        // whole contributor row (round-4 decode tolerance).
        models = (try? c.decodeIfPresent([ContributorModel].self, forKey: .models)) ?? []
    }
}

/// One model a harness contributor wrote with (C4) — `beliefs` is how many of
/// its current beliefs on this page came from turns with that model.
struct ContributorModel: Codable, Hashable {
    let model: String
    let effort: String?
    let beliefs: Int

    init(model: String, effort: String? = nil, beliefs: Int = 0) {
        self.model = model
        self.effort = effort
        self.beliefs = beliefs
    }

    enum CodingKeys: String, CodingKey { case model, effort, beliefs }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        model = (try? c.decodeIfPresent(String.self, forKey: .model)) ?? ""
        effort = (try? c.decodeIfPresent(String.self, forKey: .effort)) ?? nil
        beliefs = (try? c.decodeIfPresent(Int.self, forKey: .beliefs)) ?? 0
    }
}

/// A conversation that fed the entity (`ProvenanceConversation`, R-PB7).
/// `episodeId` is its newest episode; `available == false` means no episode
/// file is left in the bank (the row stays, honestly, but opens nothing).
struct ProvenanceConversation: Codable, Hashable, Identifiable {
    let conversationId: String?
    let episodeId: String
    let episodeIds: [String]
    let title: String
    let harness: String?
    let origin: String?
    let timestamp: String?
    let claimCount: Int
    let available: Bool
    let best: ProvenanceSpan?

    var id: String { conversationId ?? episodeId }

    init(conversationId: String? = nil, episodeId: String, episodeIds: [String]? = nil, title: String = "",
         harness: String? = nil, origin: String? = nil, timestamp: String? = nil, claimCount: Int = 0,
         available: Bool = true, best: ProvenanceSpan? = nil) {
        self.conversationId = conversationId
        self.episodeId = episodeId
        self.episodeIds = episodeIds ?? [episodeId]
        self.title = title
        self.harness = harness
        self.origin = origin
        self.timestamp = timestamp
        self.claimCount = claimCount
        self.available = available
        self.best = best
    }

    enum CodingKeys: String, CodingKey {
        case conversationId, episodeId, episodeIds, title, harness, origin, timestamp, claimCount, available, best
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        conversationId = try c.decodeIfPresent(String.self, forKey: .conversationId)
        episodeId = try c.decodeIfPresent(String.self, forKey: .episodeId) ?? ""
        episodeIds = try c.decodeIfPresent([String].self, forKey: .episodeIds) ?? [episodeId]
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        harness = try c.decodeIfPresent(String.self, forKey: .harness)
        origin = try c.decodeIfPresent(String.self, forKey: .origin)
        timestamp = try c.decodeIfPresent(String.self, forKey: .timestamp)
        claimCount = try c.decodeIfPresent(Int.self, forKey: .claimCount) ?? 0
        available = try c.decodeIfPresent(Bool.self, forKey: .available) ?? true
        best = try c.decodeIfPresent(ProvenanceSpan.self, forKey: .best)
    }
}

struct ProvenancePage: Codable, Hashable, Identifiable {
    let entityId: String
    let name: String
    let claimCount: Int

    var id: String { entityId }

    init(entityId: String, name: String = "", claimCount: Int = 0) {
        self.entityId = entityId
        self.name = name
        self.claimCount = claimCount
    }

    enum CodingKeys: String, CodingKey { case entityId, name, claimCount }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        entityId = try c.decodeIfPresent(String.self, forKey: .entityId) ?? ""
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? ""
        claimCount = try c.decodeIfPresent(Int.self, forKey: .claimCount) ?? 0
    }
}

/// Coverage stated honestly (§4.5 item 5): of `claims` current beliefs,
/// `withSpan` carry at least one exact quote and `legacy` carry no evidence
/// at all (recorded before slice 1; there is no backfill).
struct ProvenanceTotals: Codable, Hashable {
    let claims: Int
    let withSpan: Int
    let legacy: Int
    let conversations: Int

    init(claims: Int = 0, withSpan: Int = 0, legacy: Int = 0, conversations: Int = 0) {
        self.claims = claims
        self.withSpan = withSpan
        self.legacy = legacy
        self.conversations = conversations
    }

    enum CodingKeys: String, CodingKey { case claims, withSpan, legacy, conversations }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        claims = try c.decodeIfPresent(Int.self, forKey: .claims) ?? 0
        withSpan = try c.decodeIfPresent(Int.self, forKey: .withSpan) ?? 0
        legacy = try c.decodeIfPresent(Int.self, forKey: .legacy) ?? 0
        conversations = try c.decodeIfPresent(Int.self, forKey: .conversations) ?? 0
    }
}

struct EntityProvenance: Codable, Hashable {
    let entityId: String
    let entityName: String
    let entityType: String
    let contributors: [ProvenanceContributor]
    let conversations: [ProvenanceConversation]
    let pages: [ProvenancePage]
    let inferredCount: Int
    let totals: ProvenanceTotals
    let commitsTruncated: Bool

    init(entityId: String, entityName: String = "", entityType: String = "",
         contributors: [ProvenanceContributor] = [], conversations: [ProvenanceConversation] = [],
         pages: [ProvenancePage] = [], inferredCount: Int = 0, totals: ProvenanceTotals = ProvenanceTotals(),
         commitsTruncated: Bool = false) {
        self.entityId = entityId
        self.entityName = entityName
        self.entityType = entityType
        self.contributors = contributors
        self.conversations = conversations
        self.pages = pages
        self.inferredCount = inferredCount
        self.totals = totals
        self.commitsTruncated = commitsTruncated
    }

    enum CodingKeys: String, CodingKey {
        case entityId, entityName, entityType, contributors, conversations, pages, inferredCount, totals
        case commitsTruncated
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        entityId = try c.decodeIfPresent(String.self, forKey: .entityId) ?? ""
        entityName = try c.decodeIfPresent(String.self, forKey: .entityName) ?? ""
        entityType = try c.decodeIfPresent(String.self, forKey: .entityType) ?? ""
        contributors = try c.decodeIfPresent([ProvenanceContributor].self, forKey: .contributors) ?? []
        conversations = try c.decodeIfPresent([ProvenanceConversation].self, forKey: .conversations) ?? []
        pages = try c.decodeIfPresent([ProvenancePage].self, forKey: .pages) ?? []
        inferredCount = try c.decodeIfPresent(Int.self, forKey: .inferredCount) ?? 0
        totals = try c.decodeIfPresent(ProvenanceTotals.self, forKey: .totals) ?? ProvenanceTotals()
        commitsTruncated = try c.decodeIfPresent(Bool.self, forKey: .commitsTruncated) ?? false
    }
}

// MARK: - GET /episodes/{id}/citations (G118 slice 2, §4.8.3; G106 (ii))

/// One belief a document contributed (`EpisodeCitation`). `evidence` is the
/// stored entry for a span or reasoning row, nil for a derived one;
/// `start`/`end` are what to wash — nil for reasoning, a missed name, or a
/// stale span (R-PB2). `current == false` is a superseded or closed claim.
struct EpisodeCitation: Codable, Hashable, Identifiable {
    let claimId: String
    let subjectId: String
    let subjectName: String
    let subjectType: String
    let text: String
    let current: Bool
    let authoredBy: String
    let observer: String
    let evidence: Evidence?
    let kind: EvidenceKind
    let start: Int?
    let end: Int?
    let stale: Bool
    let grown: Bool
    let derived: Bool

    /// A claim can cite one document at several spans; each is its own row.
    var id: String { "\(claimId)|\(start ?? -1)|\(end ?? -1)|\(kind.rawValue)" }

    var range: Range<Int>? {
        guard let start, let end, start >= 0, end > start else { return nil }
        return start..<end
    }

    var displayKind: EvidenceKind { derived ? .derived : kind }

    init(claimId: String, subjectId: String, subjectName: String = "", subjectType: String = "",
         text: String = "", current: Bool = true, authoredBy: String = "unknown", observer: String = "agent",
         evidence: Evidence? = nil, kind: EvidenceKind = .reasoning, start: Int? = nil, end: Int? = nil,
         stale: Bool = false, grown: Bool = false, derived: Bool = false) {
        self.claimId = claimId
        self.subjectId = subjectId
        self.subjectName = subjectName
        self.subjectType = subjectType
        self.text = text
        self.current = current
        self.authoredBy = authoredBy
        self.observer = observer
        self.evidence = evidence
        self.kind = kind
        self.start = start
        self.end = end
        self.stale = stale
        self.grown = grown
        self.derived = derived
    }

    enum CodingKeys: String, CodingKey {
        case claimId, subjectId, subjectName, subjectType, text, current, authoredBy, observer
        case evidence, kind, start, end, stale, grown, derived
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        claimId = try c.decodeIfPresent(String.self, forKey: .claimId) ?? ""
        subjectId = try c.decodeIfPresent(String.self, forKey: .subjectId) ?? ""
        subjectName = try c.decodeIfPresent(String.self, forKey: .subjectName) ?? ""
        subjectType = try c.decodeIfPresent(String.self, forKey: .subjectType) ?? ""
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
        current = try c.decodeIfPresent(Bool.self, forKey: .current) ?? true
        authoredBy = try c.decodeIfPresent(String.self, forKey: .authoredBy) ?? "unknown"
        observer = try c.decodeIfPresent(String.self, forKey: .observer) ?? "agent"
        evidence = try c.decodeIfPresent(Evidence.self, forKey: .evidence)
        kind = try c.decodeIfPresent(EvidenceKind.self, forKey: .kind) ?? .reasoning
        start = try c.decodeIfPresent(Int.self, forKey: .start)
        end = try c.decodeIfPresent(Int.self, forKey: .end)
        stale = try c.decodeIfPresent(Bool.self, forKey: .stale) ?? false
        grown = try c.decodeIfPresent(Bool.self, forKey: .grown) ?? false
        derived = try c.decodeIfPresent(Bool.self, forKey: .derived) ?? false
    }
}

struct EpisodeCitationEntity: Codable, Hashable, Identifiable {
    let entityId: String
    let name: String
    let type: String

    var id: String { entityId }

    enum CodingKeys: String, CodingKey { case entityId, name, type }

    init(entityId: String, name: String = "", type: String = "") {
        self.entityId = entityId
        self.name = name
        self.type = type
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        entityId = try c.decodeIfPresent(String.self, forKey: .entityId) ?? ""
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? ""
        type = try c.decodeIfPresent(String.self, forKey: .type) ?? ""
    }
}

/// Spans first in document order (the navigator steps through them), then
/// rows without offsets. `partial` means more pages named the document than
/// one call parses (R-PB10: "capped", not "index cold").
struct EpisodeCitations: Codable, Hashable {
    let episode: String
    let citations: [EpisodeCitation]
    let entities: [EpisodeCitationEntity]
    let partial: Bool

    init(episode: String, citations: [EpisodeCitation] = [], entities: [EpisodeCitationEntity] = [],
         partial: Bool = false) {
        self.episode = episode
        self.citations = citations
        self.entities = entities
        self.partial = partial
    }

    enum CodingKeys: String, CodingKey { case episode, citations, entities, partial }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episode = try c.decodeIfPresent(String.self, forKey: .episode) ?? ""
        citations = try c.decodeIfPresent([EpisodeCitation].self, forKey: .citations) ?? []
        entities = try c.decodeIfPresent([EpisodeCitationEntity].self, forKey: .entities) ?? []
        partial = try c.decodeIfPresent(Bool.self, forKey: .partial) ?? false
    }
}
