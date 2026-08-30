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
    var entities: [String: Entity] = [:]
    var entityFetches = 0

    private func answer<T>(_ domain: SyncDomain, fallback: T) throws -> Conditional<T> {
        calls.append(domain)
        var reply = replies[domain]
        if var queued = onceReplies[domain], !queued.isEmpty {
            reply = queued.removeFirst()
            onceReplies[domain] = queued
        }
        switch reply {
        case .notModified: return Conditional(value: nil, etag: nil, notModified: true)
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
    func fetchFeeds(etag: String?) async throws -> Conditional<[FeedSubscription]> {
        try answer(.feeds, fallback: [])
    }
    func fetchCalendars(etag: String?) async throws -> Conditional<[CalendarSubscription]> {
        try answer(.calendars, fallback: [])
    }
    func fetchContributors(etag: String?) async throws -> Conditional<[Contributor]> {
        try answer(.contributors, fallback: [])
    }
    func fetchOrigins(etag: String?) async throws -> Conditional<[OriginStat]> {
        try answer(.origins, fallback: [])
    }
    func fetchConnections(etag: String?) async throws -> Conditional<[ConnectionStatus]> {
        try answer(.connections, fallback: [])
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
    func syncEventLines() async throws -> (AsyncLineSequence<URLSession.AsyncBytes>, HTTPURLResponse) {
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
}
