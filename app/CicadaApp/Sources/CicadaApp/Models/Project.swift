import Foundation

// G141 PJ-5 — the Projects wire, camelCase as `api/models/schemas.py` serialises it (`ProjectsResponse` :1193,
// `ProjectTimeline` :1199, `ProjectWriteResponse` :1247). Every field decodes leniently — a missing or mistyped key
// takes its default (R-PP2, the house rule for a new wire) — so a server one field ahead or behind never blanks the
// page. Days are `YYYY-MM-DD` and instants ISO strings: nothing relative travels (R-PJ6); the page reads them through
// `ISODay` and `RelativeDay`. Fields a `ProjectOverlay` paints (Task 5) are `var`.

extension KeyedDecodingContainer {
    /// A present, well-typed value, or `fallback`: one bad field never fails the payload.
    func lenient<T: Decodable>(_ key: Key, _ fallback: T) -> T {
        (try? decodeIfPresent(T.self, forKey: key)) ?? fallback
    }

    /// A present, well-typed value, or nil.
    func lenient<T: Decodable>(_ key: Key) -> T? {
        try? decodeIfPresent(T.self, forKey: key)
    }
}

struct ProjectProgress: Decodable, Equatable, Sendable {
    var done: Int
    var total: Int

    init(done: Int = 0, total: Int = 0) {
        self.done = done
        self.total = total
    }

    enum CodingKeys: String, CodingKey { case done, total }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        done = c.lenient(.done, 0)
        total = c.lenient(.total, 0)
    }
}

struct ProjectActivityDay: Decodable, Equatable, Sendable {
    var day: String
    var n: Int

    enum CodingKeys: String, CodingKey { case day, n }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        day = c.lenient(.day, "")
        n = c.lenient(.n, 0)
    }
}

/// One claim as `ClaimModel` sends it — only what the page reads: an event's status, target and date basis, who wrote
/// it and where, and its evidence spans. A local subset, not new fields on the shared `Claim` (R-PP2).
struct ProjectClaim: Decodable, Equatable, Sendable {
    var id: String
    var text: String
    var subject: String
    var predicate: String
    var object: String
    var validFrom: String
    var validTo: String?
    var supersededBy: String?
    var status: String?
    var target: String?
    var dateBasis: String?
    var origin: String?
    var authoredBy: String
    var authorKind: String?
    var evidence: [Evidence]
    var sourceEpisodes: [String]

    enum CodingKeys: String, CodingKey {
        case id, text, subject, predicate, object, validFrom, validTo, supersededBy, status, target, dateBasis
        case origin, authoredBy, authorKind, evidence, sourceEpisodes
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.lenient(.id, "")
        text = c.lenient(.text, "")
        subject = c.lenient(.subject, "")
        predicate = c.lenient(.predicate, "")
        object = c.lenient(.object, "")
        validFrom = c.lenient(.validFrom, "")
        validTo = c.lenient(.validTo)
        supersededBy = c.lenient(.supersededBy)
        status = c.lenient(.status)
        target = c.lenient(.target)
        dateBasis = c.lenient(.dateBasis)
        origin = c.lenient(.origin)
        authoredBy = c.lenient(.authoredBy, "unknown")
        authorKind = c.lenient(.authorKind)
        evidence = c.lenient(.evidence, [])
        sourceEpisodes = c.lenient(.sourceEpisodes, [])
    }
}

/// A page (or an unlinked name) in a happening or a moment, resolved by the server (§6.1): `surface` is the exact
/// words the sentence used (R-PJ15), `derived` a read-time relink by name (R-PJ9), `isOwner` the G117 owner page.
struct ProjectParticipant: Decodable, Equatable, Hashable, Sendable {
    var id: String?
    var name: String
    var typeName: String?
    var role: String?
    var surface: String?
    var url: String?
    var isOwner: Bool
    var derived: Bool

    var type: EntityType { typeName.flatMap(EntityType.init(rawValue:)) ?? .unknown }

    init(id: String?, name: String, type: String? = nil, role: String? = nil, surface: String? = nil,
         url: String? = nil, isOwner: Bool = false, derived: Bool = false) {
        self.id = id
        self.name = name
        self.typeName = type
        self.role = role
        self.surface = surface
        self.url = url
        self.isOwner = isOwner
        self.derived = derived
    }

    enum CodingKeys: String, CodingKey { case id, name, typeName = "type", role, surface, url, isOwner, derived }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.lenient(.id)
        name = c.lenient(.name, "")
        typeName = c.lenient(.typeName)
        role = c.lenient(.role)
        surface = c.lenient(.surface)
        url = c.lenient(.url)
        isOwner = c.lenient(.isOwner, false)
        derived = c.lenient(.derived, false)
    }
}

struct ProjectFact: Decodable, Equatable, Sendable {
    var claimId: String
    var phrase: String
    var state: String

    enum CodingKeys: String, CodingKey { case claimId, phrase, state }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        claimId = c.lenient(.claimId, "")
        phrase = c.lenient(.phrase, "")
        state = c.lenient(.state, "said")
    }
}

/// A moment's or a happening's best words — offsets into `episode`, never a copy (G118). No hash travels, so a Reader
/// opened from a moment cannot ask for grown/stale (R-PP16; reported).
struct ProjectQuote: Decodable, Equatable, Sendable {
    var episode: String
    var start: Int?
    var end: Int?
    var kind: String
    var status: String

    enum CodingKeys: String, CodingKey { case episode, start, end, kind, status }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episode = c.lenient(.episode, "")
        start = c.lenient(.start)
        end = c.lenient(.end)
        kind = c.lenient(.kind, "derived")
        status = c.lenient(.status, "current")
    }
}

/// Where a row was said. `resumable` is per request and may be stale behind a 304 (spec §7): the click re-checks.
struct ProjectConversation: Decodable, Equatable, Sendable {
    var id: String?
    var episodeId: String
    var title: String
    var origin: String?
    var harness: String?
    var resumable: Bool

    enum CodingKeys: String, CodingKey { case id, episodeId, title, origin, harness, resumable }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.lenient(.id)
        episodeId = c.lenient(.episodeId, "")
        title = c.lenient(.title, "")
        origin = c.lenient(.origin)
        harness = c.lenient(.harness)
        resumable = c.lenient(.resumable, false)
    }
}

/// One row of a project's story (spec §6.1): `moment` (derived, "said here"), `happening` (an event claim),
/// `history` (a `## History` bullet) or `created` ("Cicada started tracking this").
struct ProjectItem: Decodable, Equatable, Identifiable, Sendable {
    var kind: String
    var id: String
    var day: String?
    var at: String?
    var dateBasis: String?
    var state: String?
    var via: String?
    var project: String?
    var text: String
    var facts: [ProjectFact]
    var moreFacts: Int
    var participants: [ProjectParticipant]
    /// D6 — how many participants the happening has when the server sent only the first 12 (D6's cap); nil from a
    /// backend that sends them all.
    var participantsTotal: Int?
    var quote: ProjectQuote?
    var conversation: ProjectConversation?
    var claim: ProjectClaim?
    var verbatim: Bool

    enum CodingKeys: String, CodingKey {
        case kind, id, day, at, dateBasis, state, via, project, text, facts, moreFacts, participants, participantsTotal
        case quote, conversation, claim, verbatim
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        kind = c.lenient(.kind, "moment")
        id = c.lenient(.id, "")
        day = c.lenient(.day)
        at = c.lenient(.at)
        dateBasis = c.lenient(.dateBasis)
        state = c.lenient(.state)
        via = c.lenient(.via)
        project = c.lenient(.project)
        text = c.lenient(.text, "")
        facts = c.lenient(.facts, [])
        moreFacts = c.lenient(.moreFacts, 0)
        participants = c.lenient(.participants, [])
        participantsTotal = c.lenient(.participantsTotal)
        quote = c.lenient(.quote)
        conversation = c.lenient(.conversation)
        claim = c.lenient(.claim)
        verbatim = c.lenient(.verbatim, false)
    }

    /// A happening's own status (`ongoing`/`done`/`dropped`), else the moment's state (`said`/`changed`/`ended`).
    var status: String { claim?.status ?? state ?? "said" }
}

/// A milestone slot's head (R-PJ4): `status` is `planned|done|missed|dropped|passed-no-word`; `chain` is the slot's
/// history newest first, crossing the `due` → `milestone` hop (detail only — the list's rows carry none).
struct ProjectMilestone: Decodable, Equatable, Identifiable, Sendable {
    var slug: String
    var name: String
    var status: String
    var target: String?
    var doneOn: String?
    var moved: Bool
    var source: String
    var on: String?
    var claimId: String?
    var chain: [ProjectClaim]

    var id: String { slug }

    init(slug: String, name: String, status: String, target: String? = nil, doneOn: String? = nil, moved: Bool = false,
         source: String = "milestone", on: String? = nil, claimId: String? = nil, chain: [ProjectClaim] = []) {
        self.slug = slug
        self.name = name
        self.status = status
        self.target = target
        self.doneOn = doneOn
        self.moved = moved
        self.source = source
        self.on = on
        self.claimId = claimId
        self.chain = chain
    }

    enum CodingKeys: String, CodingKey { case slug, name, status, target, doneOn, moved, source, on, claimId, chain }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        slug = c.lenient(.slug, "")
        name = c.lenient(.name, "")
        status = c.lenient(.status, "planned")
        target = c.lenient(.target)
        doneOn = c.lenient(.doneOn)
        moved = c.lenient(.moved, false)
        source = c.lenient(.source, "milestone")
        on = c.lenient(.on)
        claimId = c.lenient(.claimId)
        chain = c.lenient(.chain, [])
    }
}

struct ProjectOpenThread: Decodable, Equatable, Identifiable, Sendable {
    var claimId: String
    var text: String
    var since: String
    var lastHeard: String
    var on: String?
    var verbatim: Bool

    var id: String { claimId }

    init(claimId: String, text: String, since: String, lastHeard: String, on: String? = nil) {
        self.claimId = claimId
        self.text = text
        self.since = since
        self.lastHeard = lastHeard
        self.on = on
        self.verbatim = false
    }

    enum CodingKeys: String, CodingKey { case claimId, text, since, lastHeard, on, verbatim }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        claimId = c.lenient(.claimId, "")
        text = c.lenient(.text, "")
        since = c.lenient(.since, "")
        lastHeard = c.lenient(.lastHeard, since)
        on = c.lenient(.on)
        verbatim = c.lenient(.verbatim, false)
    }
}

/// A page around the project (§6.4). `pending` is a name no page holds yet ("mentioned once, not a page yet").
struct ProjectMember: Decodable, Equatable, Identifiable, Sendable {
    var memberId: String?
    var typeName: String?
    var name: String
    var rolePhrase: String
    var fact: String
    var lastSeen: String?
    var count: Int
    var pending: Bool

    var id: String { memberId ?? "pending:\(name)" }
    var type: EntityType { typeName.flatMap(EntityType.init(rawValue:)) ?? .unknown }

    enum CodingKeys: String, CodingKey {
        case memberId = "id", typeName = "type", name, rolePhrase, fact, lastSeen, count, pending
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        memberId = c.lenient(.memberId)
        typeName = c.lenient(.typeName)
        name = c.lenient(.name, "")
        rolePhrase = c.lenient(.rolePhrase, "")
        fact = c.lenient(.fact, "")
        lastSeen = c.lenient(.lastSeen)
        count = c.lenient(.count, 0)
        pending = c.lenient(.pending, false)
    }
}

struct ProjectMemberGroup: Decodable, Equatable, Identifiable, Sendable {
    var label: String
    var members: [ProjectMember]
    var more: Int

    var id: String { label }

    enum CodingKeys: String, CodingKey { case label, members, more }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        label = c.lenient(.label, "")
        members = c.lenient(.members, [])
        more = c.lenient(.more, 0)
    }
}

struct ProjectCluster: Decodable, Equatable, Sendable {
    var groups: [ProjectMemberGroup] = []
    var alsoUses: [ProjectMember] = []

    init() {}

    enum CodingKeys: String, CodingKey { case groups, alsoUses }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        groups = c.lenient(.groups, [])
        alsoUses = c.lenient(.alsoUses, [])
    }
}

struct ProjectRef: Decodable, Equatable, Sendable {
    var id: String
    var name: String
    var oneLiner: String
    var parent: String?
    var children: [String]
    var status: String
    var created: String?

    enum CodingKeys: String, CodingKey { case id, name, oneLiner, parent, children, status, created }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.lenient(.id, "")
        name = c.lenient(.name, "")
        oneLiner = c.lenient(.oneLiner, "")
        parent = c.lenient(.parent)
        children = c.lenient(.children, [])
        status = c.lenient(.status, "active")
        created = c.lenient(.created)
    }
}

struct ProjectNow: Decodable, Equatable, Sendable {
    var threads: [ProjectOpenThread] = []
    var next: ProjectMilestone?

    init() {}

    enum CodingKeys: String, CodingKey { case threads, next }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        threads = c.lenient(.threads, [])
        next = c.lenient(.next)
    }
}

struct ProjectPending: Decodable, Equatable, Sendable {
    var unconsolidated: Int = 0
    var newestDay: String?

    init() {}

    enum CodingKeys: String, CodingKey { case unconsolidated, newestDay }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        unconsolidated = c.lenient(.unconsolidated, 0)
        newestDay = c.lenient(.newestDay)
    }
}

/// `GET /projects` — one row per live project, lighter than the detail (§6.5).
struct ProjectRow: Decodable, Equatable, Identifiable, Sendable {
    var id: String
    var name: String
    var oneLiner: String
    var parent: String?
    var children: [String]
    var status: String
    var created: String?
    var planned: Bool
    var lastMomentDay: String?
    var medianGapDays: Double?
    var openThreads: [ProjectOpenThread]
    var milestones: [ProjectMilestone]
    var progress: ProjectProgress
    var activity: [ProjectActivityDay]
    var followups: Int

    enum CodingKeys: String, CodingKey {
        case id, name, oneLiner, parent, children, status, created, planned, lastMomentDay, medianGapDays
        case openThreads, milestones, progress, activity, followups
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.lenient(.id, "")
        name = c.lenient(.name, "")
        oneLiner = c.lenient(.oneLiner, "")
        parent = c.lenient(.parent)
        children = c.lenient(.children, [])
        status = c.lenient(.status, "active")
        created = c.lenient(.created)
        planned = c.lenient(.planned, false)
        lastMomentDay = c.lenient(.lastMomentDay)
        medianGapDays = c.lenient(.medianGapDays)
        openThreads = c.lenient(.openThreads, [])
        milestones = c.lenient(.milestones, [])
        progress = c.lenient(.progress, ProjectProgress())
        activity = c.lenient(.activity, [])
        followups = c.lenient(.followups, 0)
    }
}

struct ProjectsResponse: Decodable, Equatable, Sendable {
    var projects: [ProjectRow]
    var tzName: String
    var partial: Bool

    enum CodingKeys: String, CodingKey { case projects, tzName, partial }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        projects = c.lenient(.projects, [])
        tzName = c.lenient(.tzName, "UTC")
        partial = c.lenient(.partial, false)
    }
}

/// `GET /projects/{id}/timeline` — one project's whole story (spec §10.1).
struct ProjectTimeline: Decodable, Equatable, Sendable {
    var project: ProjectRef
    var tzName: String
    var now: ProjectNow
    var pending: ProjectPending
    var milestones: [ProjectMilestone]
    var items: [ProjectItem]
    var activity: [ProjectActivityDay]
    var momentDays: [String]
    var lastMomentDay: String?
    var medianGapDays: Double?
    var cluster: ProjectCluster
    var conversations: [ProjectConversation]
    var partial: Bool

    enum CodingKeys: String, CodingKey {
        case project, tzName, now, pending, milestones, items, activity, momentDays, lastMomentDay, medianGapDays
        case cluster, conversations, partial
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        project = try c.decode(ProjectRef.self, forKey: .project)   // the one field without which there is no page
        tzName = c.lenient(.tzName, "UTC")
        now = c.lenient(.now, ProjectNow())
        pending = c.lenient(.pending, ProjectPending())
        milestones = c.lenient(.milestones, [])
        items = c.lenient(.items, [])
        activity = c.lenient(.activity, [])
        momentDays = c.lenient(.momentDays, [])
        lastMomentDay = c.lenient(.lastMomentDay)
        medianGapDays = c.lenient(.medianGapDays)
        cluster = c.lenient(.cluster, ProjectCluster())
        conversations = c.lenient(.conversations, [])
        partial = c.lenient(.partial, false)
    }

    /// Whether a row's page (`thread.on`, `item.project`; nil = the project itself) is in this project's tree — the
    /// only pages a write can reach. The story also shows the owner's own events that name the project (the server's
    /// `project_timeline._events`), but `routers/projects._find_event` searches the tree alone, so Done / Still going
    /// / Stopped, D and Not right on such a row would always 404 and roll back. Final review of G141 PJ-5.
    func holds(_ page: String?) -> Bool {
        guard let page else { return true }
        return page == project.id || project.children.contains(page)
    }

    /// The open thread D may settle: in Now, on a page of the tree.
    func settleableThread(_ claimId: String) -> ProjectOpenThread? {
        now.threads.first { $0.claimId == claimId && holds($0.on) }
    }
}

/// What every Projects write answers (`routers/projects.py`): the claim it wrote, the day and how that day was
/// decided (R-PJ6 — the Log's confirmation says it), and a Log's companion note.
struct ProjectWriteResponse: Decodable, Equatable, Sendable {
    var action: String
    var claimId: String?
    var day: String?
    var dateBasis: String?
    var episodeId: String?

    init(action: String, claimId: String? = nil, day: String? = nil, dateBasis: String? = nil, episodeId: String? = nil) {
        self.action = action
        self.claimId = claimId
        self.day = day
        self.dateBasis = dateBasis
        self.episodeId = episodeId
    }

    enum CodingKeys: String, CodingKey { case action, claimId, day, dateBasis, episodeId }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        action = c.lenient(.action, "")
        claimId = c.lenient(.claimId)
        day = c.lenient(.day)
        dateBasis = c.lenient(.dateBasis)
        episodeId = c.lenient(.episodeId)
    }
}
