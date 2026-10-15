import Foundation

/// G166 exploring (owner 2026-10-14) — the wire of `api/routers/explore.py`. Lenient everywhere: a field this build
/// cannot read is dropped alone, never the answer (an older backend has no explore routes at all — a 404 — and the
/// cache then shows nothing).

/// Who started a run: the person's click, or a trusted local agent they asked in chat (D5), with its label.
struct ExploreStarter: Decodable, Equatable, Sendable {
    var kind: String
    var harness: String?

    init(kind: String = "person", harness: String? = nil) {
        self.kind = kind
        self.harness = harness
    }

    enum CodingKeys: String, CodingKey { case kind, harness }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        kind = (try? c.decode(String.self, forKey: .kind)) ?? "person"
        harness = try? c.decodeIfPresent(String.self, forKey: .harness)
    }

    var isAgent: Bool { kind == "agent" }
}

/// The active run's counts (`batch_view`). `agents` is the number of sessions holding a live lease; `etaMinutes` the
/// median time a site took so far, over the sites left, shared by the agents working.
struct ExploreBatch: Decodable, Equatable, Sendable {
    var id: String
    var createdAt: String?
    var startedBy: ExploreStarter
    var stoppedAt: String?
    var total: Int
    var done: Int
    var waiting: Int
    var claimed: Int
    var agents: Int
    var needsLogin: Int
    var blocked: Int
    var failed: Int
    var gone: Int
    var etaMinutes: Int?

    init(id: String = "x_000000", createdAt: String? = nil, startedBy: ExploreStarter = ExploreStarter(),
         stoppedAt: String? = nil, total: Int, done: Int = 0, waiting: Int = 0, claimed: Int = 0, agents: Int = 0,
         needsLogin: Int = 0, blocked: Int = 0, failed: Int = 0, gone: Int = 0, etaMinutes: Int? = nil) {
        self.id = id
        self.createdAt = createdAt
        self.startedBy = startedBy
        self.stoppedAt = stoppedAt
        self.total = total
        self.done = done
        self.waiting = waiting
        self.claimed = claimed
        self.agents = agents
        self.needsLogin = needsLogin
        self.blocked = blocked
        self.failed = failed
        self.gone = gone
        self.etaMinutes = etaMinutes
    }

    enum CodingKeys: String, CodingKey {
        case id, createdAt, startedBy, stoppedAt, total, done, waiting, claimed, agents, needsLogin, blocked, failed,
             gone, etaMinutes
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decode(String.self, forKey: .id)) ?? ""
        createdAt = try? c.decodeIfPresent(String.self, forKey: .createdAt)
        startedBy = (try? c.decode(ExploreStarter.self, forKey: .startedBy)) ?? ExploreStarter()
        stoppedAt = try? c.decodeIfPresent(String.self, forKey: .stoppedAt)
        func int(_ key: CodingKeys) -> Int { (try? c.decode(Int.self, forKey: key)) ?? 0 }
        total = int(.total)
        done = int(.done)
        waiting = int(.waiting)
        claimed = int(.claimed)
        agents = int(.agents)
        needsLogin = int(.needsLogin)
        blocked = int(.blocked)
        failed = int(.failed)
        gone = int(.gone)
        etaMinutes = try? c.decodeIfPresent(Int.self, forKey: .etaMinutes)
    }

    /// Still going: sites waiting or held, and nobody stopped it.
    var isRunning: Bool { stoppedAt == nil && (waiting + claimed) > 0 }
}

/// One saved site's latest capture, for its row's chip ("Explored 14 Oct").
struct ExploreLatest: Decodable, Equatable, Sendable {
    var id: String
    var capturedAt: String?
    var outcome: String?
    var signedIn: Bool
    var thumbUrl: String?

    enum CodingKeys: String, CodingKey { case id, capturedAt, outcome, signedIn, thumbUrl }

    init(id: String, capturedAt: String? = nil, outcome: String? = nil, signedIn: Bool = true, thumbUrl: String? = nil) {
        self.id = id
        self.capturedAt = capturedAt
        self.outcome = outcome
        self.signedIn = signedIn
        self.thumbUrl = thumbUrl
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decode(String.self, forKey: .id)) ?? ""
        capturedAt = try? c.decodeIfPresent(String.self, forKey: .capturedAt)
        outcome = try? c.decodeIfPresent(String.self, forKey: .outcome)
        signedIn = (try? c.decode(Bool.self, forKey: .signedIn)) ?? true
        thumbUrl = try? c.decodeIfPresent(String.self, forKey: .thumbUrl)
    }
}

/// One saved site in the run or already explored, joined by the app on `mediaEntityId|url` to the row it shows.
struct ExploreItem: Decodable, Equatable, Sendable, Identifiable {
    var key: String?
    var mediaEntityId: String
    var url: String?
    /// `queued`, `claimed`, `paused`, `failed`, or `explored` (not in the queue, with a capture).
    var state: String
    var code: String?
    var latest: ExploreLatest?

    var id: String { "\(mediaEntityId)|\(url ?? "")" }

    enum CodingKeys: String, CodingKey { case key, mediaEntityId, url, state, code, latest }

    init(key: String? = nil, mediaEntityId: String, url: String? = nil, state: String, code: String? = nil,
         latest: ExploreLatest? = nil) {
        self.key = key
        self.mediaEntityId = mediaEntityId
        self.url = url
        self.state = state
        self.code = code
        self.latest = latest
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        key = try? c.decodeIfPresent(String.self, forKey: .key)
        mediaEntityId = (try? c.decode(String.self, forKey: .mediaEntityId)) ?? ""
        url = try? c.decodeIfPresent(String.self, forKey: .url)
        state = (try? c.decode(String.self, forKey: .state)) ?? "explored"
        code = try? c.decodeIfPresent(String.self, forKey: .code)
        latest = try? c.decodeIfPresent(ExploreLatest.self, forKey: .latest)
    }
}

/// `GET /explore/state`.
struct ExploreState: Decodable, Equatable, Sendable {
    var batch: ExploreBatch?
    var items: [ExploreItem]
    var nextChangeAt: String?

    init(batch: ExploreBatch? = nil, items: [ExploreItem] = [], nextChangeAt: String? = nil) {
        self.batch = batch
        self.items = items
        self.nextChangeAt = nextChangeAt
    }

    enum CodingKeys: String, CodingKey { case batch, items, nextChangeAt }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        batch = try? c.decodeIfPresent(ExploreBatch.self, forKey: .batch)
        items = (try? c.decode([ExploreItem].self, forKey: .items)) ?? []
        nextChangeAt = try? c.decodeIfPresent(String.self, forKey: .nextChangeAt)
    }
}

/// The run's size, never a price (ruling 12).
struct ExploreEstimate: Decodable, Equatable, Sendable {
    var size: String
    var minutes: Int

    init(size: String = "light", minutes: Int = 0) {
        self.size = size
        self.minutes = minutes
    }
}

struct ExploreOrigin: Decodable, Equatable, Sendable, Identifiable {
    var origin: String
    var label: String
    var count: Int
    var id: String { origin }
}

/// `GET /explore/candidates` — what the Explore sheet counts, and whether a run can start here.
struct ExploreCandidates: Decodable, Equatable, Sendable {
    var eligible: Int
    var neverExplored: Int
    var origins: [ExploreOrigin]
    var excluded: [String: Int]
    var estimate: ExploreEstimate
    var estimateNeverExplored: ExploreEstimate
    var agentEnabled: Bool
    var exploreSignedIn: Bool
    var skillVerified: Bool
    var demo: Bool

    init(eligible: Int = 0, neverExplored: Int = 0, origins: [ExploreOrigin] = [], excluded: [String: Int] = [:],
         estimate: ExploreEstimate = ExploreEstimate(), estimateNeverExplored: ExploreEstimate = ExploreEstimate(),
         agentEnabled: Bool = false, exploreSignedIn: Bool = true, skillVerified: Bool = true, demo: Bool = false) {
        self.eligible = eligible
        self.neverExplored = neverExplored
        self.origins = origins
        self.excluded = excluded
        self.estimate = estimate
        self.estimateNeverExplored = estimateNeverExplored
        self.agentEnabled = agentEnabled
        self.exploreSignedIn = exploreSignedIn
        self.skillVerified = skillVerified
        self.demo = demo
    }

    enum CodingKeys: String, CodingKey {
        case eligible, neverExplored, origins, excluded, estimate, estimateNeverExplored, agentEnabled,
             exploreSignedIn, skillVerified, demo
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        eligible = (try? c.decode(Int.self, forKey: .eligible)) ?? 0
        neverExplored = (try? c.decode(Int.self, forKey: .neverExplored)) ?? 0
        origins = (try? c.decode([ExploreOrigin].self, forKey: .origins)) ?? []
        excluded = (try? c.decode([String: Int].self, forKey: .excluded)) ?? [:]
        estimate = (try? c.decode(ExploreEstimate.self, forKey: .estimate)) ?? ExploreEstimate()
        estimateNeverExplored = (try? c.decode(ExploreEstimate.self, forKey: .estimateNeverExplored)) ?? ExploreEstimate()
        agentEnabled = (try? c.decode(Bool.self, forKey: .agentEnabled)) ?? false
        exploreSignedIn = (try? c.decode(Bool.self, forKey: .exploreSignedIn)) ?? true
        skillVerified = (try? c.decode(Bool.self, forKey: .skillVerified)) ?? false
        demo = (try? c.decode(Bool.self, forKey: .demo)) ?? false
    }
}

/// Which saved sites a click explores.
enum ExploreScope: String, Sendable, CaseIterable {
    case neverExplored = "never_explored"
    case all
}

struct ExploreStartedBatch: Decodable, Equatable, Sendable {
    var id: String
    var total: Int
}

/// `POST /explore/batches`: the batch and the prompt to copy for the person's agent.
struct ExploreStartResponse: Decodable, Equatable, Sendable {
    var batch: ExploreStartedBatch
    var prompt: String
}

/// Looks v2 — what "Save its look" answers: the link it queued, whether it joined a run already going, and the prompt
/// to hand the person's agent.
struct ExploreLookResponse: Decodable, Equatable, Sendable {
    var key: String
    var mediaEntityId: String
    var joined: Bool
    var prompt: String
}

struct ExploreStopResponse: Decodable, Equatable, Sendable {
    var stopped: Bool
    var dropped: Int
    var finishing: Int
}

struct ExplorePromptResponse: Decodable, Equatable, Sendable {
    var prompt: String
}
