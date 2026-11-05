import Foundation

// Projects v2 (TODO ruling 45, wire g141-7) — the person's own list, what Cicada suggests, and the "project knowledge"
// side panel: conversations tied with why, sources and influences, what a provider project carried. Lenient like
// every Projects field (R-PP2): a missing or mistyped key takes its default.

/// Who last set a project's description: `user`, or the agent that did on the person's ask.
struct ProjectDescriptionBy: Decodable, Equatable, Sendable {
    var by: String
    var day: String?

    init(by: String = "user", day: String? = nil) {
        self.by = by
        self.day = day
    }

    enum CodingKeys: String, CodingKey { case by, day }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        by = c.lenient(.by, "user")
        day = c.lenient(.day)
    }

    var isPerson: Bool { by == "user" }
}

/// One source or influence on a project (proposal §2.6): a link (`source == "link"`) or a claim whose object is a page
/// (`entity`) or plain text. `tag` is the side panel's group; `by` is `user`, a harness label or `sleep`.
struct ProjectInfluence: Decodable, Equatable, Identifiable, Sendable {
    var id: String
    var source: String
    var label: String
    var url: String?
    var entity: String?
    var entityType: String?
    var tag: String
    var how: String?
    var by: String
    var day: String?
    var claimId: String?
    var predicate: String?
    var ref: String?
    var page: String?

    init(id: String, source: String = "claim", label: String, url: String? = nil, entity: String? = nil,
         tag: String = "Thing", how: String? = nil, by: String = "user", day: String? = nil, claimId: String? = nil,
         ref: String? = nil, page: String? = nil) {
        self.id = id
        self.source = source
        self.label = label
        self.url = url
        self.entity = entity
        self.entityType = nil
        self.tag = tag
        self.how = how
        self.by = by
        self.day = day
        self.claimId = claimId
        self.predicate = nil
        self.ref = ref
        self.page = page
    }

    enum CodingKeys: String, CodingKey {
        case id, source, label, url, entity, entityType, tag, how, by, day, claimId, predicate, ref, page
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.lenient(.id, "")
        source = c.lenient(.source, "claim")
        label = c.lenient(.label, "")
        url = c.lenient(.url)
        entity = c.lenient(.entity)
        entityType = c.lenient(.entityType)
        tag = c.lenient(.tag, "Thing")
        how = c.lenient(.how)
        by = c.lenient(.by, "user")
        day = c.lenient(.day)
        claimId = c.lenient(.claimId)
        predicate = c.lenient(.predicate)
        ref = c.lenient(.ref)
        page = c.lenient(.page)
    }

    /// The kinds that label a group in the side panel; anything else (the server's "Thing", "Idea", …) sits unlabelled.
    static let knownTags: Set<String> = ["Film", "Book", "Paper", "Video", "Link", "Person", "Tool", "Podcast",
                                         "Article", "Media", "Organisation", "Place", "Project"]

    /// The person may take back what they added, a link or a claim on the project.
    var undoable: Bool { claimId != nil || ref != nil }
}

/// What a provider project carried: Claude's instructions (shown while the imported episode still holds those bytes)
/// and its documents, by name only.
struct ProjectKnowledge: Decodable, Equatable, Sendable {
    var provider: String
    var projectId: String
    var name: String
    var episode: String?
    var instructions: String?
    var docs: [String]

    enum CodingKeys: String, CodingKey { case provider, projectId, name, episode, instructions, docs }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        provider = c.lenient(.provider, "")
        projectId = c.lenient(.projectId, "")
        name = c.lenient(.name, "")
        episode = c.lenient(.episode)
        instructions = c.lenient(.instructions)
        docs = c.lenient(.docs, [])
    }
}

/// One conversation tied to the project, and why (`GET /projects/{id}/conversations`).
struct ProjectConversationRow: Decodable, Equatable, Identifiable, Sendable {
    var episodeId: String
    var conversationId: String?
    var title: String
    var origin: String?
    var harness: String?
    var resumable: Bool
    var day: String?
    var why: [String]
    var relayed: Bool
    var providerLabel: String?
    var manual: Bool
    /// Ruling 56 (g141-10) — the agent that tied or proposed it, and its one sentence why.
    var by: String? = nil
    var reason: String? = nil

    var id: String { episodeId }

    init(episodeId: String, title: String, origin: String? = nil, harness: String? = nil, day: String? = nil,
         why: [String] = [], relayed: Bool = false, manual: Bool = false) {
        self.episodeId = episodeId
        self.conversationId = nil
        self.title = title
        self.origin = origin
        self.harness = harness
        self.resumable = false
        self.day = day
        self.why = why
        self.relayed = relayed
        self.providerLabel = nil
        self.manual = manual
    }

    enum CodingKeys: String, CodingKey {
        case episodeId, conversationId = "id", title, origin, harness, resumable, day, why, relayed, providerLabel
        case manual, by, reason
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episodeId = c.lenient(.episodeId, "")
        conversationId = c.lenient(.conversationId)
        title = c.lenient(.title, "")
        origin = c.lenient(.origin)
        harness = c.lenient(.harness)
        resumable = c.lenient(.resumable, false)
        day = c.lenient(.day)
        why = c.lenient(.why, [])
        relayed = c.lenient(.relayed, false)
        providerLabel = c.lenient(.providerLabel)
        manual = c.lenient(.manual, false)
        by = c.lenient(.by)
        reason = c.lenient(.reason)
    }
}

struct ProjectConversationsPage: Decodable, Equatable, Sendable {
    var project: String
    var total: Int
    var counts: [String: Int]
    var conversations: [ProjectConversationRow]
    var offset: Int
    var partial: Bool
    /// Ruling 56 — what an agent off the trust list proposed: never counted until the person adds one.
    var proposed: [ProjectConversationRow]

    init(project: String, total: Int = 0, counts: [String: Int] = [:], conversations: [ProjectConversationRow] = [],
         partial: Bool = false, proposed: [ProjectConversationRow] = []) {
        self.project = project
        self.total = total
        self.counts = counts
        self.conversations = conversations
        self.offset = 0
        self.partial = partial
        self.proposed = proposed
    }

    enum CodingKeys: String, CodingKey { case project, total, counts, conversations, offset, partial, proposed }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        project = c.lenient(.project, "")
        total = c.lenient(.total, 0)
        counts = c.lenient(.counts, [:])
        conversations = c.lenient(.conversations, [])
        proposed = c.lenient(.proposed, [])
        offset = c.lenient(.offset, 0)
        partial = c.lenient(.partial, false)
    }
}

/// What the ownership, header, tie and influence routes answer.
struct ProjectOwnershipResponse: Decodable, Equatable, Sendable {
    var id: String
    var action: String
    var mine: Bool
    var claimId: String?
    var page: String?
    /// Ruling 56 — Remove gave the page back as what it was: it has no project view any more.
    var retyped = false

    init(id: String, action: String, mine: Bool = true, claimId: String? = nil, page: String? = nil) {
        self.id = id
        self.action = action
        self.mine = mine
        self.claimId = claimId
        self.page = page
    }

    enum CodingKeys: String, CodingKey { case id, action, mine, claimId, page, retyped }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.lenient(.id, "")
        action = c.lenient(.action, "")
        mine = c.lenient(.mine, false)
        retyped = c.lenient(.retyped, false)
        claimId = c.lenient(.claimId)
        page = c.lenient(.page)
    }
}

/// One page in "Pages in this project" (decision 10, wire g141-8). `tie`: `said` (a claim or an event ties it),
/// `user` (the person tied it by hand), `agent` (a trusted agent did, `by` its name) or `proposed` (an agent not on the
/// trust list proposed it — shown for the person to take, not yet part of the project).
struct ProjectPageRow: Decodable, Equatable, Identifiable, Sendable {
    var id: String
    var name: String
    var type: String?
    var rolePhrase: String
    var fact: String
    var count: Int
    var lastSeen: String?
    var tie: String
    var by: String?
    /// Ruling 56 (g141-10) — an agent's one sentence on why it tied or proposed this page.
    var reason: String? = nil
    /// G227 (g141-9) — the name to show when another page shares this title.
    var displayName: String? = nil
    /// G227 — its qualifier alone, drawn as a `Tag` beside the plain name.
    var qualifier: String? = nil

    var shownName: String { displayName ?? name }

    init(id: String, name: String, type: String? = nil, rolePhrase: String = "", fact: String = "", count: Int = 0,
         lastSeen: String? = nil, tie: String = "said", by: String? = nil) {
        self.id = id
        self.name = name
        self.type = type
        self.rolePhrase = rolePhrase
        self.fact = fact
        self.count = count
        self.lastSeen = lastSeen
        self.tie = tie
        self.by = by
    }

    enum CodingKeys: String, CodingKey { case id, name, type, rolePhrase, fact, count, lastSeen, tie, by, reason, displayName, qualifier }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.lenient(.id, "")
        name = c.lenient(.name, "")
        type = c.lenient(.type)
        rolePhrase = c.lenient(.rolePhrase, "")
        fact = c.lenient(.fact, "")
        count = c.lenient(.count, 0)
        lastSeen = c.lenient(.lastSeen)
        tie = c.lenient(.tie, "said")
        by = c.lenient(.by)
        displayName = c.lenient(.displayName)
        qualifier = c.lenient(.qualifier)
        reason = c.lenient(.reason)
    }

    var isProposed: Bool { tie == "proposed" }
}
