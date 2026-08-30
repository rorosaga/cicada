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
/// answers. `@unchecked Sendable` is safe here: XCTest drives it serially and
/// every touch happens from the Store's main-actor context.
final class FakeSyncAPI: SyncAPI, @unchecked Sendable {
    enum Reply {
        case value(Any)          // a fresh payload
        case notModified
        case failure
    }

    var calls: [SyncDomain] = []
    var replies: [SyncDomain: Reply] = [:]
    var syncVersion = VersionVector(version: "v0", components: [:])
    var entities: [String: Entity] = [:]
    var entityFetches = 0

    private func answer<T>(_ domain: SyncDomain, fallback: T) throws -> Conditional<T> {
        calls.append(domain)
        switch replies[domain] {
        case .notModified: return Conditional(value: nil, etag: nil, notModified: true)
        case .failure: throw APIError.serverUnreachable
        case .value(let v): return Conditional(value: (v as! T), etag: "\"\(domain.rawValue)\"", notModified: false)
        case nil: return Conditional(value: fallback, etag: "\"\(domain.rawValue)\"", notModified: false)
        }
    }

    func fetchGraph(etag: String?) async throws -> Conditional<GraphResponse> {
        try answer(.graph, fallback: try decodeFixture(graphJSON))
    }
    func fetchInbox(etag: String?) async throws -> Conditional<[InboxItem]> {
        try answer(.inbox, fallback: try decodeFixture(inboxJSON))
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
}
