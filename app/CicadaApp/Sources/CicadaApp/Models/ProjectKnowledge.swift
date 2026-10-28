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

/// One suggestion under the list's Suggested fold: a project page or a fallback page (`kind == "page"`), or a
/// provider's project with no page yet (`kind == "group"`, named on accept). `whyKind` orders and words it.
struct SuggestedProject: Decodable, Equatable, Identifiable, Sendable {
    var id: String
    var kind: String
    var name: String
    var pageType: String?
    var whyKind: String
    var why: String
    var quote: String?
    var episode: String?
    var day: String?
    var repoName: String?
    var sessions: Int
    var by: String?
    var provider: String?
    var dismissed: Bool

    init(id: String, kind: String = "page", name: String, whyKind: String = "none", why: String = "",
         quote: String? = nil, day: String? = nil, repoName: String? = nil, sessions: Int = 0, by: String? = nil,
         provider: String? = nil, dismissed: Bool = false) {
        self.id = id
        self.kind = kind
        self.name = name
        self.pageType = nil
        self.whyKind = whyKind
        self.why = why
        self.quote = quote
        self.episode = nil
        self.day = day
        self.repoName = repoName
        self.sessions = sessions
        self.by = by
        self.provider = provider
        self.dismissed = dismissed
    }

    enum CodingKeys: String, CodingKey {
        case id, kind, name, pageType, whyKind, why, quote, episode, day, repoName, sessions, by, provider, dismissed
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.lenient(.id, "")
        kind = c.lenient(.kind, "page")
        name = c.lenient(.name, "")
        pageType = c.lenient(.pageType)
        whyKind = c.lenient(.whyKind, "none")
        why = c.lenient(.why, "")
        quote = c.lenient(.quote)
        episode = c.lenient(.episode)
        day = c.lenient(.day)
        repoName = c.lenient(.repoName)
        sessions = c.lenient(.sessions, 0)
        by = c.lenient(.by)
        provider = c.lenient(.provider)
        dismissed = c.lenient(.dismissed, false)
    }

    /// A provider grouping has no page and no name of its own: accepting it asks for one.
    var needsName: Bool { kind == "group" }
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
        case manual
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
    }
}

struct ProjectConversationsPage: Decodable, Equatable, Sendable {
    var project: String
    var total: Int
    var counts: [String: Int]
    var conversations: [ProjectConversationRow]
    var offset: Int
    var partial: Bool

    init(project: String, total: Int = 0, counts: [String: Int] = [:], conversations: [ProjectConversationRow] = [],
         partial: Bool = false) {
        self.project = project
        self.total = total
        self.counts = counts
        self.conversations = conversations
        self.offset = 0
        self.partial = partial
    }

    enum CodingKeys: String, CodingKey { case project, total, counts, conversations, offset, partial }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        project = c.lenient(.project, "")
        total = c.lenient(.total, 0)
        counts = c.lenient(.counts, [:])
        conversations = c.lenient(.conversations, [])
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

    init(id: String, action: String, mine: Bool = true, claimId: String? = nil, page: String? = nil) {
        self.id = id
        self.action = action
        self.mine = mine
        self.claimId = claimId
        self.page = page
    }

    enum CodingKeys: String, CodingKey { case id, action, mine, claimId, page }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.lenient(.id, "")
        action = c.lenient(.action, "")
        mine = c.lenient(.mine, false)
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

    enum CodingKeys: String, CodingKey { case id, name, type, rolePhrase, fact, count, lastSeen, tie, by }

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
    }

    var isProposed: Bool { tie == "proposed" }
}
