import XCTest
@testable import CicadaApp

// MARK: - Fixtures

private func decodeFixture<T: Decodable>(_ json: String, as: T.Type = T.self) throws -> T {
    try JSONDecoder().decode(T.self, from: Data(json.utf8))
}

private let graphJSON = """
{"nodes":[{"id":"n1","name":"Cicada","type":"project","status":"active","confidence":0.9}],
 "links":[],"observers":[]}
"""

private let inboxJSON = """
[{"id":"inbox-001","kind":"decay","requiredInput":"choice","title":"Still interested?"}]
"""

private let banksJSON = """
{"banks":[{"id":"work","name":"work"}],"active":"work"}
"""

private let consumptionJSON = """
{"summary":{"costUsd":1.5,"equivCostUsd":3.0,"range":"month"},
 "calendar":{"days":[],"weeks":53},
 "stats":{"byModel":[],"byStage":[],"byConnection":[],"byBank":[],"hourHistogram":[0],"series":[],"range":"month"},
 "connections":{"connections":[],"range":"month"},
 "harness":{}}
"""

private let statusJSON = """
{"sleep":{"status":"idle","stage":0,"totalStages":5,"cycleId":null,"error":null},
 "inbox":{"total":2,"byKind":{"decay":2}},
 "episodes":{"unprocessed":0,"lastIngestedAt":null},
 "lastSleepAt":null,"nextSleepAt":null}
"""

// MARK: - Fake API

/// Records which conditional fetches the Store issued and hands back canned
/// answers.
///
/// `@MainActor`-isolated on purpose: the gated tests below genuinely run the
/// test body and an in-flight fetch concurrently, and a plain
/// `@unchecked Sendable` class had its `calls`/`gates` collections mutated from
/// two executors at once (intermittent segfaults / task-allocator aborts).
/// Isolation makes every touch serialize with the `@MainActor` Store.
@MainActor
final class FakeSyncAPI: SyncAPI {
    enum Reply {
        case value(Any)          // a fresh payload
        case notModified
        case failure
        /// What `APIClient`'s `catch APIError.httpError(404, _)` branches now
        /// hand back — `Conditional.unavailable`, i.e. "endpoint not shipped",
        /// reported as a no-change rather than as an empty payload.
        case notFound
    }

    var calls: [SyncDomain] = []
    var replies: [SyncDomain: Reply] = [:]
    /// Replies consumed one per call, ahead of `replies` — lets a test make a
    /// domain fail once and succeed afterwards.
    var onceReplies: [SyncDomain: [Reply]] = [:]
    /// Domains whose fetch parks until `releaseGate(_:)` — lets a test hold a
    /// request in flight and inspect the Store mid-reconcile.
    var gatedDomains: Set<SyncDomain> = []
    var gates: [SyncDomain: CheckedContinuation<Void, Never>] = [:]

    fileprivate func gateIfNeeded(_ domain: SyncDomain) async {
        guard gatedDomains.contains(domain) else { return }
        await withCheckedContinuation { self.gates[domain] = $0 }
    }

    func releaseGate(_ domain: SyncDomain) {
        let g = gates[domain]
        gates[domain] = nil
        g?.resume()
    }
    var syncVersion = VersionVector(version: "v0", components: [:])

    // MARK: Writes (§5.4)

    /// Every write the fake saw, in order, as "name:argument" strings.
    var writes: [String] = []
    /// When true, every write throws — drives the rollback paths.
    var failWrites = false
    /// Parks the next write until `releaseWriteGate()`, so a test can inspect
    /// the Store while a mutation is mid-flight.
    var gateWrites = false
    private var writeGate: CheckedContinuation<Void, Never>?
    /// Set once a gated write has actually parked.
    private(set) var writeIsParked = false

    func releaseWriteGate() {
        let g = writeGate
        writeGate = nil
        writeIsParked = false
        g?.resume()
    }

    /// Spins (bounded) until a gated write has parked.
    func waitForParkedWrite(file: StaticString = #filePath, line: UInt = #line) async {
        for _ in 0..<200_000 {
            if writeIsParked { return }
            await Task.yield()
        }
        XCTFail("write never parked on the gate", file: file, line: line)
    }

    private func record(_ what: String) async throws {
        writes.append(what)
        if gateWrites {
            await withCheckedContinuation { c in
                writeIsParked = true
                writeGate = c
            }
        }
        if failWrites { throw APIError.serverUnreachable }
    }

    func resolveInbox(id: String, action: String, answer: String?,
                      optionKey: String?, remindDays: Int?,
                      mergeTarget: String?, mergeSurvivor: String?) async throws {
        try await record(
            "resolveInbox:\(id):\(action):\(optionKey ?? "nil"):\(remindDays.map(String.init) ?? "nil")"
        )
    }
    func setConnectionTier(_ id: String, tier: String?) async throws -> ConnectionStatus {
        try await record("setConnectionTier:\(id):\(tier ?? "nil")")
        return try connectionFixture(id: id)
    }
    func setUseForSleep(_ id: String, on: Bool) async throws -> ConnectionStatus {
        try await record("setUseForSleep:\(id):\(on)")
        return try connectionFixture(id: id)
    }
    func setConnectionKey(_ id: String, key: String) async throws -> ConnectionStatus {
        try await record("setConnectionKey:\(id)")
        return try connectionFixture(id: id)
    }
    func removeConnectionKey(_ id: String) async throws -> ConnectionStatus {
        try await record("removeConnectionKey:\(id)")
        return try connectionFixture(id: id)
    }
    func logoutConnection(_ id: String) async throws -> ConnectionStatus {
        try await record("logoutConnection:\(id)")
        return try connectionFixture(id: id)
    }
    func subscribeFeed(url: String, tags: [String]) async throws -> FeedSubscription {
        try await record("subscribeFeed:\(url)")
        return FeedSubscription(url: url, tags: tags)
    }
    func unsubscribeFeed(url: String) async throws {
        try await record("unsubscribeFeed:\(url)")
    }
    func subscribeCalendar(url: String, tags: [String]) async throws -> CalendarSubscription {
        try await record("subscribeCalendar:\(url)")
        return CalendarSubscription(url: url, tags: tags)
    }
    func unsubscribeCalendar(url: String) async throws {
        try await record("unsubscribeCalendar:\(url)")
    }
    func syncSafariTabs(db: Data, wal: Data?, devices: [String]?) async throws -> SafariTabsSyncResult {
        try await record("syncSafariTabs:\(devices?.count ?? 0)")
        return SafariTabsSyncResult(new: 1, skipped: 0, seen: 1, devices: [])
    }
    func syncBookmarks(chromeData: Data?, safariData: Data?, folders: [String]?) async throws -> BookmarkSyncResult {
        try await record("syncBookmarks:\(folders?.count ?? 0)")
        return BookmarkSyncResult(new: 1, skipped: 0, sources: [])
    }
    func activateBank(name: String) async throws {
        try await record("activateBank:\(name)")
    }
    func triggerSleep() async throws -> SleepTriggerResponse {
        try await record("triggerSleep")
        return try JSONDecoder().decode(
            SleepTriggerResponse.self,
            from: Data(#"{"status":"started","cycleId":"c1","message":"started"}"#.utf8))
    }

    private func connectionFixture(id: String) throws -> ConnectionStatus {
        ConnectionStatus(id: id, label: id, kind: "subscription", available: true,
                         connected: true, plan: "max", planLabel: nil, tier: nil,
                         account: nil, priceUsdMonth: nil, priceNote: nil,
                         billing: "subscription", engineRole: nil, detail: nil,
                         how: nil, powers: [], login: nil)
    }
    var entities: [String: Entity] = [:]
    var entityFetches = 0

    // MARK: - Conversations (G48, on-demand — no SyncDomain)
    var recentConversations: [ConversationSummary] = []
    var failRecentConversations = false
    var resumeDescriptor = ResumeDescriptor()
    var resumeError: (any Error)?
    /// By-id lookups the fake bank knows. Deliberately SEPARATE from
    /// `recentConversations` so a test can model the real asymmetry: a
    /// conversation the bank has, but that the capped recent page omits.
    var conversationsById: [String: ConversationSummary] = [:]
    var conversationIdFetches: [String] = []
    var failConversationById = false

    /// G124 R5 — the fake filters the way the backend does: `harness`/`origin`
    /// match exactly, and `harness == "unknown"` matches rows with an empty
    /// harness (an MCP episode that never stamped one).
    func fetchRecentConversations(limit: Int, harness: String?, origin: String?) async throws -> [ConversationSummary] {
        if failRecentConversations { throw APIError.serverUnreachable }
        return recentConversations.filter { row in
            if let harness, !(row.harness == harness || (harness == "unknown" && row.harness.isEmpty)) { return false }
            if let origin, row.origin != origin { return false }
            return true
        }
    }

    func fetchConversation(id: String) async throws -> ConversationSummary? {
        conversationIdFetches.append(id)
        if failConversationById { throw APIError.serverUnreachable }
        return conversationsById[id]
    }

    func resumeConversation(id: String) async throws -> ResumeDescriptor {
        if let resumeError { throw resumeError }
        return resumeDescriptor
    }

    private func answer<T>(_ domain: SyncDomain, fallback: T) throws -> Conditional<T> {
        calls.append(domain)
        var reply = replies[domain]
        if var queued = onceReplies[domain], !queued.isEmpty {
            reply = queued.removeFirst()
            onceReplies[domain] = queued
        }
        switch reply {
        case .notModified: return Conditional(value: nil, etag: nil, notModified: true)
        case .notFound: return .unavailable(etag: nil)
        case .failure: throw APIError.serverUnreachable
        case .value(let v): return Conditional(value: (v as! T), etag: "\"\(domain.rawValue)\"", notModified: false)
        case nil: return Conditional(value: fallback, etag: "\"\(domain.rawValue)\"", notModified: false)
        }
    }

    func fetchGraph(etag: String?) async throws -> Conditional<GraphResponse> {
        let result = try answer(.graph, fallback: try decodeFixture(graphJSON) as GraphResponse)
        await gateIfNeeded(.graph)
        return result
    }
    func fetchInbox(etag: String?) async throws -> Conditional<[InboxItem]> {
        let result = try answer(.inbox, fallback: try decodeFixture(inboxJSON) as [InboxItem])
        await gateIfNeeded(.inbox)
        return result
    }
    func fetchBanks(etag: String?) async throws -> Conditional<BanksResponse> {
        try answer(.banks, fallback: try decodeFixture(banksJSON))
    }
    func fetchSources(etag: String?) async throws -> Conditional<[MediaFeedItem]> {
        try answer(.sources, fallback: [])
    }
    func fetchChannels(etag: String?) async throws -> Conditional<[SourceChannel]> {
        try answer(.channels, fallback: [])
    }
    func fetchFeeds(etag: String?) async throws -> Conditional<[FeedSubscription]> {
        try answer(.feeds, fallback: [])
    }
    func fetchCalendars(etag: String?) async throws -> Conditional<[CalendarSubscription]> {
        try answer(.calendars, fallback: [])
    }
    func fetchContributors(etag: String?) async throws -> Conditional<[Contributor]> {
        let result: Conditional<[Contributor]> = try answer(.contributors, fallback: [])
        await gateIfNeeded(.contributors)
        return result
    }
    func fetchOrigins(etag: String?) async throws -> Conditional<[OriginStat]> {
        try answer(.origins, fallback: [])
    }
    var sourcesOverview: [SourceOverview] = []
    func fetchSourcesOverview(etag: String?) async throws -> Conditional<[SourceOverview]> {
        try answer(.sourcesOverview, fallback: sourcesOverview)
    }
    func fetchConnections(etag: String?) async throws -> Conditional<[ConnectionStatus]> {
        try answer(.connections, fallback: [])
    }
    func fetchConsumption(etag: String?, current: ConsumptionBundle?) async throws -> Conditional<ConsumptionBundle> {
        try answer(.consumption, fallback: current ?? (try decodeFixture(consumptionJSON) as ConsumptionBundle))
    }
    func fetchStatus() async throws -> StatusSnapshot {
        calls.append(.status)
        if case .failure = replies[.status] { throw APIError.serverUnreachable }
        if case .value(let v) = replies[.status], let s = v as? StatusSnapshot { return s }
        return try decodeFixture(statusJSON)
    }
    func fetchEntity(id: String) async throws -> Entity {
        entityFetches += 1
        guard let e = entities[id] else { throw APIError.httpError(404, "missing") }
        return e
    }
    func fetchSyncVersion() async throws -> VersionVector { syncVersion }
    func syncEventLines() async throws -> (AsyncThrowingStream<String, any Error>, HTTPURLResponse) {
        throw APIError.serverUnreachable
    }
}

// MARK: - Tests

@MainActor
final class StoreTests: XCTestCase {

    private func tempCache() -> SnapshotCache {
        SnapshotCache(root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString))
    }

    /// (a) hydrate() reads the bank from the cached banks roster and loads
    /// every domain for that bank off disk — no network at all.
    func testHydrateLoadsFromSeededCache() async throws {
        let cache = tempCache()
        let banks: BanksResponse = try decodeFixture(banksJSON)
        let inbox: [InboxItem] = try decodeFixture(inboxJSON)
        await cache.save(banks, etag: "\"b\"", domain: .banks, bank: Store.rosterBank)
        await cache.save(inbox, etag: "\"i\"", domain: .inbox, bank: "work")
        await cache.flush()

        let api = FakeSyncAPI()
        let store = Store(cache: cache, api: api)
        await store.hydrate()

        XCTAssertEqual(store.bank, "work")
        XCTAssertEqual(store.inbox.value?.count, 1)
        XCTAssertEqual(store.inbox.etag, "\"i\"")
        XCTAssertEqual(store.banks.value?.active, "work")
        XCTAssertTrue(api.calls.isEmpty, "hydrate must not hit the network")
    }

    /// G125 v3 Task 8, review round 2. `loadedAt` moves on a disk hydrate —
    /// it is a change token (`GraphViewModel` re-maps the graph off it), not a
    /// freshness claim. The Sleep page's `as of HH:MM` chip needs the second
    /// meaning, so `refreshedAt` exists and a hydrate must leave it nil:
    /// otherwise a cold launch with the backend stopped prints the minute the
    /// app opened over data that could be days old.
    ///
    /// The assertion is written all the way through to the page's own
    /// decision, because that is the bug: a never-refreshed page is `.live`,
    /// with no hour to print, exactly as `sleepLiveness`'s third refusal says.
    func testDiskHydrateLeavesRefreshedAtNilSoTheStalenessChipHasNoHourToFabricate() async throws {
        let cache = tempCache()
        let banks: BanksResponse = try decodeFixture(banksJSON)
        let status: StatusSnapshot = try decodeFixture(statusJSON)
        await cache.save(banks, etag: "\"b\"", domain: .banks, bank: Store.rosterBank)
        await cache.save(status, etag: nil, domain: .status, bank: "work")
        await cache.save([SourceOverview(id: "claude-code", label: "Claude Code", kind: .harness)],
                         etag: "\"o\"", domain: .sourcesOverview, bank: "work")
        await cache.flush()

        let store = Store(cache: cache, api: FakeSyncAPI())
        await store.hydrate()

        XCTAssertNotNil(store.status.value, "the hydrate did land")
        XCTAssertNotNil(store.status.loadedAt, "loadedAt stays a change token and must still move")
        XCTAssertNotNil(store.sourcesOverview.loadedAt)
        XCTAssertNil(store.status.refreshedAt, "a disk read is not a backend confirmation")
        XCTAssertNil(store.sourcesOverview.refreshedAt)
        XCTAssertNil(store.banks.refreshedAt)

        XCTAssertFalse(store.isConnected)
        let liveness = sleepLiveness(
            isConnected: store.isConnected,
            refreshedAt: SleepLiveness.stalestRefreshedAt(store.status.refreshedAt,
                                                          store.sourcesOverview.refreshedAt),
            isError: false)
        XCTAssertEqual(liveness, .live,
                       "a page the backend has never confirmed must show no chip, not the launch minute")
        XCTAssertNil(liveness.asOf)
    }

    /// The other half of round 2: `refreshedAt` has to be *stamped* somewhere,
    /// or the chip could never appear. Both landed outcomes count — a 200 with
    /// a new body and a 304 saying the body we hold is current — because both
    /// mean the backend answered just now; only a failure leaves the last
    /// confirmation standing.
    func testALandedResponseStampsRefreshedAtOnBoth200And304() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: tempCache(), api: api)

        await store.refresh([.sourcesOverview, .status])
        XCTAssertNotNil(store.sourcesOverview.refreshedAt, "a 200 is a confirmation")
        XCTAssertNotNil(store.status.refreshedAt)

        // A 304 moves it too — a domain that rarely changes is not stale.
        let longAgo = Date(timeIntervalSinceReferenceDate: 0)
        store.sourcesOverview.refreshedAt = longAgo
        api.replies[.sourcesOverview] = .notModified
        await store.refresh([.sourcesOverview])
        XCTAssertGreaterThan(store.sourcesOverview.refreshedAt ?? longAgo, longAgo,
                             "a 304 confirms the value we hold is current")

        // A failure does not: the last real confirmation is what the chip must
        // date the page by, so the reader sees the moment contact was lost.
        let confirmed = store.sourcesOverview.refreshedAt
        api.replies[.sourcesOverview] = .failure
        await store.refresh([.sourcesOverview])
        XCTAssertEqual(store.sourcesOverview.refreshedAt, confirmed,
                       "a failed fetch confirms nothing and must not move the chip forward")

        store.isConnected = false
        XCTAssertEqual(
            sleepLiveness(isConnected: false,
                          refreshedAt: SleepLiveness.stalestRefreshedAt(store.status.refreshedAt,
                                                                        store.sourcesOverview.refreshedAt),
                          isError: false),
            .stale(asOf: SleepLiveness.stalestRefreshedAt(store.status.refreshedAt,
                                                          store.sourcesOverview.refreshedAt)!),
            "once the backend HAS confirmed something, a disconnect dates the page by it")
    }

    /// (b) A 304 keeps the existing value instead of blanking it.
    func testNotModifiedKeepsExistingValue() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: tempCache(), api: api)
        await store.refresh([.inbox])
        XCTAssertEqual(store.inbox.value?.count, 1)
        let etag = store.inbox.etag

        api.replies[.inbox] = .notModified
        await store.refresh([.inbox])
        XCTAssertEqual(store.inbox.value?.count, 1, "304 must not blank the snapshot")
        XCTAssertEqual(store.inbox.etag, etag)
        XCTAssertFalse(store.inbox.isRefreshing)
    }

    /// (c) apply(version:) refreshes only the domains the changed components
    /// map to — an `inbox` bump touches inbox + graph + status, nothing else.
    func testApplyVersionRefreshesOnlyChangedDomains() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: tempCache(), api: api)
        store.version = VersionVector(version: "v1", components: ["inbox": "a", "entities": "e", "sources": "s"])
        api.calls.removeAll()

        await store.apply(version: VersionVector(
            version: "v2", components: ["inbox": "b", "entities": "e", "sources": "s"]))

        XCTAssertEqual(Set(api.calls), [.inbox, .graph, .status])
        XCTAssertEqual(store.version?.version, "v2")
    }

    /// (d) A failing fetch never destroys what's on screen. A toast is raised
    /// only when there was nothing to show in the first place.
    func testFailureKeepsValueAndToastsOnlyWhenEmpty() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: tempCache(), api: api)
        await store.refresh([.inbox])
        XCTAssertEqual(store.inbox.value?.count, 1)

        api.replies[.inbox] = .failure
        await store.refresh([.inbox])
        XCTAssertEqual(store.inbox.value?.count, 1, "an error must keep the last good value")
        XCTAssertNil(store.toast, "no toast while we still have something to show")
        XCTAssertFalse(store.inbox.isRefreshing)

        // Empty snapshot + failure → surface it.
        api.replies[.contributors] = .failure
        await store.refresh([.contributors])
        XCTAssertNil(store.contributors.value)
        XCTAssertNotNil(store.toast)
    }

    /// PR #19 round-4 review: `refreshStatus()` has its own loop separate from
    /// `refreshOne` and used to only set `toast` on a failed first fetch,
    /// never `domainErrors[.status]` — so `SleepQueueCard.loadState`, which
    /// reads that key, could never reach `.failed` and spun on `.loading`
    /// forever. A failed first status fetch must latch the domain error, and
    /// a later successful fetch must clear it, exactly like every other
    /// domain in `refreshOne`.
    func testFailedStatusFetchLatchesDomainErrorAndSuccessClearsIt() async throws {
        let api = FakeSyncAPI()
        api.replies[.status] = .failure
        let store = Store(cache: tempCache(), api: api)

        await store.refresh([.status])
        XCTAssertNil(store.status.value, "no snapshot has ever landed")
        XCTAssertFalse(store.status.isRefreshing, "a failed fetch must not leave the domain spinning")
        XCTAssertEqual(store.domainErrors[.status], "Couldn't load status")

        api.replies[.status] = nil
        await store.refresh([.status])
        XCTAssertNotNil(store.status.value)
        XCTAssertNil(store.domainErrors[.status], "a landed response clears the latched failure")
    }

    /// entity(_:) caches full bodies so a second lookup is free.
    func testEntityCacheIsMemoised() async throws {
        let api = FakeSyncAPI()
        let entity: Entity = try decodeFixture("""
        {"id":"n1","name":"Cicada","type":"project","status":"active","confidence":0.9,
         "created":"2026-01-01","lastReferenced":"2026-01-02","decayRate":0.05,
         "markdownContent":"# Cicada"}
        """)
        api.entities["n1"] = entity
        let store = Store(cache: tempCache(), api: api)

        let first = await store.entity("n1")
        let second = await store.entity("n1")
        XCTAssertEqual(first?.id, "n1")
        XCTAssertEqual(second?.id, "n1")
        XCTAssertEqual(api.entityFetches, 1)
    }

    // MARK: - Final review fixes

    /// (F1) Entity ids are only unique *within* a bank, so a memoised body must
    /// not survive a bank switch — bank A's `capstone` would otherwise render
    /// under bank B's node of the same id.
    func testEntityCacheIsClearedOnBankSwitch() async throws {
        let api = FakeSyncAPI()
        let bodyA: Entity = try decodeFixture("""
        {"id":"x","name":"A's X","type":"project","status":"active","confidence":0.9,
         "created":"2026-01-01","lastReferenced":"2026-01-02","decayRate":0.05,
         "markdownContent":"# From bank A"}
        """)
        api.entities["x"] = bodyA
        let store = Store(cache: tempCache(), api: api)

        let readA = await store.entity("x")
        XCTAssertEqual(readA?.markdownContent, "# From bank A")
        XCTAssertEqual(api.entityFetches, 1)
        XCTAssertNotNil(store.entities["x"])

        // Switch banks. `ActivateBank.optimistic` runs `hydrate(bank:)`, which
        // is where the cache must be dropped.
        let bodyB: Entity = try decodeFixture("""
        {"id":"x","name":"B's X","type":"project","status":"active","confidence":0.4,
         "created":"2026-02-01","lastReferenced":"2026-02-02","decayRate":0.05,
         "markdownContent":"# From bank B"}
        """)
        api.entities["x"] = bodyB
        _ = await store.perform(ActivateBank(name: "B"))

        XCTAssertTrue(store.entities.isEmpty, "the entity cache must not cross banks")
        let readB = await store.entity("x")
        XCTAssertEqual(readB?.markdownContent, "# From bank B")
        XCTAssertEqual(api.entityFetches, 2, "the post-switch read must refetch")
    }

    /// (F6) A 404 on a conditional fetch means "this backend has no such
    /// endpoint", not "the list is empty". It must never blank — or persist an
    /// empty value over — a populated snapshot.
    func testNotFoundKeepsExistingValue() async throws {
        let api = FakeSyncAPI()
        api.replies[.feeds] = .value([FeedSubscription(url: "https://example.com/rss")])
        let store = Store(cache: tempCache(), api: api)
        await store.refresh([.feeds])
        XCTAssertEqual(store.feeds.value?.count, 1)
        let etag = store.feeds.etag

        api.replies[.feeds] = .notFound
        await store.refresh([.feeds])
        XCTAssertEqual(store.feeds.value?.count, 1, "a 404 must not blank the snapshot")
        XCTAssertEqual(store.feeds.etag, etag)
        XCTAssertNil(store.toast)
    }

    /// (F6) `/banks` is not exempt: an empty roster is indistinguishable from a
    /// real one, so a 404 there would blank the dropdown *and* persist the blank
    /// under `_roster` — and `BanksViewModel.load()`, which reads a missing
    /// roster as its error path, would never surface the failure.
    func testNotFoundKeepsExistingBanksRoster() async throws {
        let cache = tempCache()
        let api = FakeSyncAPI()
        let store = Store(cache: cache, api: api)

        await store.refresh([.banks])
        XCTAssertEqual(store.banks.value?.active, "work")
        let etag = store.banks.etag
        await cache.flush()
        let saved: (value: BanksResponse, etag: String?)? =
            await cache.load(.banks, bank: Store.rosterBank, as: BanksResponse.self)
        XCTAssertEqual(saved?.value.active, "work")

        api.replies[.banks] = .notFound
        await store.refresh([.banks])

        XCTAssertEqual(store.banks.value?.active, "work", "a 404 must not blank the roster")
        XCTAssertEqual(store.banks.value?.banks.count, saved?.value.banks.count)
        XCTAssertEqual(store.banks.etag, etag)
        XCTAssertNil(store.toast)

        await cache.flush()
        let after: (value: BanksResponse, etag: String?)? =
            await cache.load(.banks, bank: Store.rosterBank, as: BanksResponse.self)
        XCTAssertEqual(after?.value.active, "work", "nothing empty may be persisted under _roster")
    }

    /// (F6) The helper every 404 branch in `APIClient` returns.
    func testConditionalUnavailableIsANoChange() {
        let c = Conditional<[FeedSubscription]>.unavailable(etag: "\"e\"")
        XCTAssertNil(c.value)
        XCTAssertTrue(c.notModified)
        XCTAssertEqual(c.etag, "\"e\"")
    }

    // MARK: - Review fixes

    /// (1) A bank switch must stick even when the roster we just fetched is
    /// still inside the cache's 500 ms write debounce. Re-reading the roster
    /// there used to flip `bank` straight back to the old one.
    func testBankSwitchSticksOnAWarmCache() async throws {
        let cache = tempCache()
        let rosterA: BanksResponse = try decodeFixture(
            #"{"banks":[{"name":"A"},{"name":"B"}],"active":"A"}"#)
        let rosterB: BanksResponse = try decodeFixture(
            #"{"banks":[{"name":"A"},{"name":"B"}],"active":"B"}"#)
        let inboxA: [InboxItem] = try decodeFixture(inboxJSON)
        await cache.save(rosterA, etag: "\"a\"", domain: .banks, bank: Store.rosterBank)
        await cache.save(inboxA, etag: "\"ia\"", domain: .inbox, bank: "A")
        await cache.save(inboxA, etag: "\"ib\"", domain: .inbox, bank: "B")
        await cache.flush()

        let api = FakeSyncAPI()
        api.replies[.banks] = .value(rosterA)
        let store = Store(cache: cache, api: api)
        await store.bootstrap()
        XCTAssertEqual(store.bank, "A")

        // The backend switches the active bank.
        api.replies[.banks] = .value(rosterB)
        await store.refresh([.banks])

        XCTAssertEqual(store.bank, "B", "the switch must not be reverted by a stale roster read")
        await cache.flush()
        let saved = await cache.load(.inbox, bank: "B", as: [InboxItem].self)
        XCTAssertEqual(saved?.etag, "\"inbox\"", "post-switch refreshes must persist under bank B")
    }

    /// (2) A domain whose refresh failed stays pending, so the next version
    /// event retries it even though the version vector already moved on.
    func testFailedDomainIsRetriedOnNextVersion() async throws {
        let api = FakeSyncAPI()
        api.onceReplies[.graph] = [.failure]
        let store = Store(cache: tempCache(), api: api)
        store.version = VersionVector(version: "v1", components: ["entities": "a"])

        await store.apply(version: VersionVector(version: "v2", components: ["entities": "b"]))
        XCTAssertNil(store.graph.value, "the fetch failed, so there is nothing yet")

        api.calls.removeAll()
        // Same vector as last time: nothing "changed", but .graph is still owed.
        await store.apply(version: VersionVector(version: "v2", components: ["entities": "b"]))
        XCTAssertTrue(api.calls.contains(.graph), "a still-pending domain must be retried")
        XCTAssertNotNil(store.graph.value)

        // Once it succeeded it stops being retried.
        api.calls.removeAll()
        await store.apply(version: VersionVector(version: "v2", components: ["entities": "b"]))
        XCTAssertFalse(api.calls.contains(.graph))
    }

    /// (3) The Store is the single owner of the sleep running→idle edge:
    /// exactly one `justFinishedAt` per finished cycle, none while idle.
    func testSleepEdgeProducesExactlyOneJustFinished() async throws {
        let store = Store(cache: tempCache(), api: FakeSyncAPI())
        var seen: [Date?] = []
        store.onStatus = { _, justFinishedAt in seen.append(justFinishedAt) }

        store.applySleepEvent(SleepEventPayload(status: "running", stage: 2))
        store.applySleepEvent(SleepEventPayload(status: "idle"))
        store.applySleepEvent(SleepEventPayload(status: "idle"))

        XCTAssertEqual(seen.count, 3, "every sleep event must push status")
        XCTAssertNil(seen[0], "no edge while the cycle is running")
        XCTAssertNotNil(seen[1], "running -> idle is the edge")
        XCTAssertEqual(seen[2], seen[1], "idle -> idle must not fire a second edge")
    }

    /// (4) Overlapping refreshes of one domain coalesce: one GET in flight,
    /// then exactly one re-run for the request that arrived meanwhile.
    func testOverlappingRefreshCoalesces() async throws {
        let api = FakeSyncAPI()
        api.gatedDomains = [.inbox]
        let store = Store(cache: tempCache(), api: api)

        let inFlight = Task { await store.refresh([.inbox]) }
        await waitForGate(api, .inbox)
        XCTAssertEqual(api.calls.count, 1)

        await store.refresh([.inbox])   // coalesced — must not issue a second GET
        XCTAssertEqual(api.calls.count, 1, "an in-flight domain must not be fetched twice")

        api.gatedDomains = []
        api.releaseGate(.inbox)
        await inFlight.value
        XCTAssertEqual(api.calls.count, 2, "the coalesced request re-runs exactly once")
        XCTAssertEqual(store.inbox.value?.count, 1)
        XCTAssertFalse(store.inbox.isRefreshing)
    }

    /// Spin the main actor until the fake has parked on `domain`'s gate.
    private func waitForGate(_ api: FakeSyncAPI, _ domain: SyncDomain) async {
        var spins = 0
        while api.gates[domain] == nil, spins < 100_000 {
            await Task.yield()
            spins += 1
        }
        XCTAssertNotNil(api.gates[domain], "the fake never reached the \(domain.rawValue) gate")
    }

    /// A bank switch must not leave the previous bank's data on screen under
    /// the new bank's label. Bank B has no cached graph, so `graph` must go
    /// empty the moment we switch — not linger as A's graph until the
    /// sequential reconcile happens to reach it.
    func testBankSwitchDoesNotBleedSnapshots() async throws {
        let cache = tempCache()
        let rosterA: BanksResponse = try decodeFixture(
            #"{"banks":[{"name":"A"},{"name":"B"}],"active":"A"}"#)
        let rosterB: BanksResponse = try decodeFixture(
            #"{"banks":[{"name":"A"},{"name":"B"}],"active":"B"}"#)
        let graphA: GraphResponse = try decodeFixture(graphJSON)
        let inboxItems: [InboxItem] = try decodeFixture(inboxJSON)
        await cache.save(rosterA, etag: "\"a\"", domain: .banks, bank: Store.rosterBank)
        await cache.save(graphA, etag: "\"ga\"", domain: .graph, bank: "A")
        await cache.save(inboxItems, etag: "\"ia\"", domain: .inbox, bank: "A")
        // Bank B has an inbox cached but NO graph.
        await cache.save(inboxItems, etag: "\"ib\"", domain: .inbox, bank: "B")
        await cache.flush()

        let api = FakeSyncAPI()
        api.replies[.banks] = .value(rosterA)
        let store = Store(cache: cache, api: api)
        await store.bootstrap()
        XCTAssertEqual(store.bank, "A")
        XCTAssertNotNil(store.graph.value, "bank A has a graph")

        // Switch to B, holding the post-switch graph refresh in flight so we can
        // observe the window between hydrate and reconcile.
        api.gatedDomains = [.graph]
        api.replies[.banks] = .value(rosterB)
        let switching = Task { await store.refresh([.banks]) }
        await waitForGate(api, .graph)

        XCTAssertEqual(store.bank, "B")
        XCTAssertNil(store.graph.value, "bank A's graph must not render under bank B")
        XCTAssertNil(store.graph.etag, "and A's etag must not be sent to B (a 304 would hide B's data)")
        XCTAssertEqual(store.inbox.etag, "\"ib\"", "B's own cached inbox is kept")
        XCTAssertEqual(store.inbox.value?.count, 1)

        api.gatedDomains = []
        api.releaseGate(.graph)
        await switching.value
        XCTAssertNotNil(store.graph.value, "the reconcile then fills B's graph in")
    }

    /// A `/graph` GET issued while bank A was active must not land in bank B's
    /// slot when it completes after a switch. Without the epoch guard the
    /// response (and A's etag) overwrite B's freshly-reset snapshot, and the
    /// etag makes the next real fetch answer 304 — A's graph then sticks under
    /// B's label indefinitely.
    func testStaleBankResponseIsDiscarded() async throws {
        let api = FakeSyncAPI()
        api.gatedDomains = [.graph]
        let store = Store(cache: tempCache(), api: api)
        await store.hydrate(bank: "A")

        let inFlight = Task { await store.refresh([.graph]) }
        await waitForGate(api, .graph)

        // The switch happens while A's graph response is in flight.
        store.bank = "B"

        api.gatedDomains = []
        api.releaseGate(.graph)
        await inFlight.value

        XCTAssertNil(store.graph.value, "bank A's response must not be written into bank B's slot")
        XCTAssertNil(store.graph.etag, "and A's etag must not be sent to B")
        XCTAssertFalse(store.graph.isRefreshing, "the discarded refresh still clears its flag")
    }

    /// A parked request must not make its domain permanently unrefreshable.
    ///
    /// This is the backend-restart stall: a `/graph` request issued against a
    /// connection that never answers holds `graph.isRefreshing`, so every
    /// later version event coalesces into it and issues no GET at all. The SSE
    /// reconnect calls `resetInFlight()`, which must break that hold.
    func testResetInFlightUnblocksAParkedDomain() async throws {
        let api = FakeSyncAPI()
        api.gatedDomains = [.graph]
        let store = Store(cache: tempCache(), api: api)

        let parked = Task { await store.refresh([.graph]) }
        await waitForGate(api, .graph)
        XCTAssertEqual(api.calls.count, 1)
        XCTAssertTrue(store.graph.isRefreshing)

        // The bug, pinned: while the request is parked, nothing gets through.
        await store.refresh([.graph])
        XCTAssertEqual(api.calls.count, 1, "a parked domain swallows every later refresh")

        // The reconnect clears the decks.
        store.resetInFlight()
        XCTAssertFalse(store.graph.isRefreshing)

        api.gatedDomains = []
        await store.refresh([.graph])
        XCTAssertEqual(api.calls.count, 2, "after resetInFlight the domain is fetchable again")
        XCTAssertEqual(store.graph.value?.nodes.count, 1)

        // The abandoned request finally unwinds: it must not clear the flag or
        // steal the queue from the attempt that replaced it.
        api.releaseGate(.graph)
        await parked.value
        XCTAssertEqual(api.calls.count, 2, "the abandoned loop must not re-run itself")
        XCTAssertFalse(store.graph.isRefreshing)
    }

    /// `resetInFlight()` re-arms what the abandoned requests owed, so the next
    /// version event refreshes them even when the vector itself did not move.
    func testResetInFlightReArmsCoalescedDomains() async throws {
        let api = FakeSyncAPI()
        api.gatedDomains = [.graph]
        let store = Store(cache: tempCache(), api: api)

        let parked = Task { await store.refresh([.graph]) }
        await waitForGate(api, .graph)
        await store.refresh([.graph])          // queued behind the parked one
        XCTAssertEqual(api.calls.count, 1)

        store.resetInFlight()
        api.gatedDomains = []

        // Same version vector as the Store already holds: `changedDomains` is
        // empty, so only the re-armed pending set can drive this refresh.
        store.version = VersionVector(version: "v0", components: [:])
        await store.apply(version: VersionVector(version: "v0", components: [:]))
        XCTAssertTrue(api.calls.contains(.graph))
        XCTAssertEqual(api.calls.count, 2, "the re-armed domain is fetched exactly once")

        api.releaseGate(.graph)
        await parked.value
        XCTAssertFalse(store.graph.isRefreshing)
    }

    /// The usage dashboard (G51) is machine-global like the banks roster —
    /// it must persist under `Store.rosterBank`, not whichever bank is
    /// active, and must survive a bank switch instead of going blank like
    /// `graph` does (see `testBankSwitchDoesNotBleedSnapshots`).
    func testConsumptionIsCachedGloballyAndSurvivesABankSwitch() async throws {
        let cache = tempCache()
        let bundle: ConsumptionBundle = try decodeFixture(consumptionJSON)
        let rosterA: BanksResponse = try decodeFixture(
            #"{"banks":[{"name":"A"},{"name":"B"}],"active":"A"}"#)
        let api = FakeSyncAPI()
        api.replies[.banks] = .value(rosterA)
        api.replies[.consumption] = .value(bundle)
        // `hydrate()` + `refresh()` directly, not `bootstrap()` — `bootstrap()`
        // also starts the live `SyncEngine`, whose background version check
        // (`store.version` starts nil, so `changedDomains(since: nil)` is
        // everything) races a second reconcile against this test's own
        // `cache.flush()`, cancelling the first save before it lands.
        let store = Store(cache: cache, api: api)
        await store.hydrate()
        await store.refreshAll()
        XCTAssertEqual(store.bank, "A")
        XCTAssertEqual(store.consumption.value?.summary.costUsd, 1.5)

        // Persisted under the global pseudo-bank, not "A".
        await cache.flush()
        let onDisk = await cache.load(.consumption, bank: Store.rosterBank, as: ConsumptionBundle.self)
        XCTAssertEqual(onDisk?.value.summary.costUsd, 1.5)
        let underA = await cache.load(.consumption, bank: "A", as: ConsumptionBundle.self)
        XCTAssertNil(underA, "consumption must not be written under the active bank")

        // Switching banks must not blank it (unlike `graph`, which has no
        // cached value for bank B in this test and goes nil).
        let rosterB: BanksResponse = try decodeFixture(
            #"{"banks":[{"name":"A"},{"name":"B"}],"active":"B"}"#)
        api.replies[.banks] = .value(rosterB)
        await store.refresh([.banks])
        XCTAssertEqual(store.bank, "B")
        XCTAssertEqual(store.consumption.value?.summary.costUsd, 1.5, "consumption survives the bank switch")
    }
}
