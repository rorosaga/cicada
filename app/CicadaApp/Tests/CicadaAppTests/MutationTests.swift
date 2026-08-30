import XCTest
@testable import CicadaApp

/// §5.4 — optimistic mutations. Every case drives `Store.perform` with the
/// shared `FakeSyncAPI` (declared in `StoreTests.swift`), which records writes
/// and can throw or park on demand.
@MainActor
final class MutationTests: XCTestCase {

    private func tempCache() -> SnapshotCache {
        SnapshotCache(root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString))
    }

    private func inboxItems(_ ids: [String]) throws -> [InboxItem] {
        let json = ids.map { #"{"id":"\#($0)","kind":"decay","requiredInput":"choice","title":"\#($0)"}"# }
        return try JSONDecoder().decode([InboxItem].self,
                                        from: Data("[\(json.joined(separator: ","))]".utf8))
    }

    private func connection(id: String, plan: String?, tier: String?) -> ConnectionStatus {
        ConnectionStatus(id: id, label: id, kind: "subscription", available: true,
                         connected: true, plan: plan, planLabel: nil, tier: tier,
                         account: "me@example.com", priceUsdMonth: nil, priceNote: nil,
                         billing: "subscription", engineRole: nil, detail: nil,
                         how: nil, powers: [], login: nil)
    }

    // MARK: - Inbox

    /// The card disappears the instant the user clicks, and a failed request
    /// puts it back exactly where it was.
    func testInboxResolveHidesOptimisticallyAndRollsBackInPlace() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: tempCache(), api: api)
        store.inbox.value = try inboxItems(["a", "b", "c"])

        // `Store.perform` reconciles on the failure path too; answer it 304 so
        // what we observe is exactly what `rollback` left behind.
        api.replies[.inbox] = .notModified
        api.gateWrites = true
        api.failWrites = true
        let inFlight = Task { await store.perform(InboxResolve(id: "b", action: "archive")) }
        await api.waitForParkedWrite()

        XCTAssertEqual(store.visibleInbox.map(\.id), ["a", "c"], "the card is hidden before the round-trip")

        api.releaseWriteGate()
        let ok = await inFlight.value

        XCTAssertFalse(ok)
        XCTAssertEqual(store.visibleInbox.map(\.id), ["a", "b", "c"], "rollback restores it at its index")
        XCTAssertEqual(store.toast, "Couldn't resolve that item — reverted")
        XCTAssertEqual(api.writes, ["resolveInbox:b:archive:nil:nil"])
    }

    /// `skip` keeps the item in the queue by design — nothing is hidden.
    func testInboxSkipDoesNotHideTheCard() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: tempCache(), api: api)
        store.inbox.value = try inboxItems(["a", "b"])
        // `skip` leaves the item in the queue server-side, so the follow-up
        // refresh returns it unchanged.
        api.replies[.inbox] = .value(try inboxItems(["a", "b"]))

        let ok = await store.perform(InboxResolve(id: "a", action: "skip"))
        XCTAssertTrue(ok)
        XCTAssertEqual(store.visibleInbox.map(\.id), ["a", "b"])
        XCTAssertTrue(store.hiddenInboxIds.isEmpty)
    }

    /// The flash-back guard: if the refresh that follows a *successful* resolve
    /// still lists the item (a 304, or a snapshot taken just before the
    /// server-side delete), the card must stay hidden until a snapshot without
    /// it arrives.
    func testResolvedItemStaysHiddenUntilTheSnapshotDropsIt() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: tempCache(), api: api)
        // The post-resolve refresh still returns the resolved item.
        api.replies[.inbox] = .value(try inboxItems(["a", "b"]))

        let ok = await store.perform(InboxResolve(id: "b", action: "archive"))
        XCTAssertTrue(ok)
        XCTAssertEqual(store.visibleInbox.map(\.id), ["a"], "a stale snapshot must not flash the card back")
        XCTAssertTrue(store.hiddenInboxIds.contains("b"))

        // The next snapshot no longer has it — the item is genuinely gone and
        // the hide can be forgotten.
        api.replies[.inbox] = .value(try inboxItems(["a"]))
        await store.refresh([.inbox])
        XCTAssertEqual(store.visibleInbox.map(\.id), ["a"])
        XCTAssertTrue(store.hiddenInboxIds.isEmpty, "the hide is dropped once the server agrees")
    }

    // MARK: - Connections

    func testSetConnectionTierPatchesPriceAndLabelLocally() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: tempCache(), api: api)
        store.connections.value = [connection(id: "claude-plan", plan: "max", tier: nil)]

        api.gateWrites = true
        let inFlight = Task { await store.perform(SetConnectionTier(id: "claude-plan", tier: "20x")) }
        await api.waitForParkedWrite()

        let row = store.connections.value?.first
        XCTAssertEqual(row?.tier, "20x")
        XCTAssertEqual(row?.planLabel, "Claude Max 20x")
        XCTAssertEqual(row?.priceUsdMonth, 200)

        api.releaseWriteGate()
        let ok = await inFlight.value
        XCTAssertTrue(ok)
        XCTAssertEqual(api.writes, ["setConnectionTier:claude-plan:20x"])
    }

    /// ChatGPT Pro uses the same 5x/20x → $100/$200 table.
    func testChatGPTProTierPricing() {
        XCTAssertEqual(ClientPricing.price("chatgpt-plan", plan: "pro", tier: "5x"), 100)
        XCTAssertEqual(ClientPricing.price("chatgpt-plan", plan: "pro", tier: "20x"), 200)
        XCTAssertEqual(ClientPricing.planLabel("chatgpt-plan", plan: "pro", tier: "5x"), "ChatGPT Pro 5x")
        XCTAssertNil(ClientPricing.price("claude-plan", plan: "max", tier: nil),
                     "a tiered plan with no tier has no price, exactly as the server says")
    }

    func testTierChangeRollsBackToThePreviousRow() async throws {
        let api = FakeSyncAPI()
        api.failWrites = true
        api.replies[.connections] = .notModified
        let store = Store(cache: tempCache(), api: api)
        store.connections.value = [connection(id: "claude-plan", plan: "max", tier: "5x")]

        let ok = await store.perform(SetConnectionTier(id: "claude-plan", tier: "20x"))
        XCTAssertFalse(ok)
        XCTAssertEqual(store.connections.value?.first?.tier, "5x")
        XCTAssertNil(store.connections.value?.first?.priceUsdMonth)
        XCTAssertEqual(store.toast, "Couldn't change the plan tier — reverted")
    }

    func testLogoutFlipsConnectedAndRollsBack() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: tempCache(), api: api)
        store.connections.value = [connection(id: "claude-plan", plan: "max", tier: "20x")]
        api.replies[.connections] = .notModified

        api.gateWrites = true
        api.failWrites = true
        let inFlight = Task { await store.perform(LogoutConnection(id: "claude-plan")) }
        await api.waitForParkedWrite()
        XCTAssertEqual(store.connections.value?.first?.connected, false)

        api.releaseWriteGate()
        let ok = await inFlight.value
        XCTAssertFalse(ok)
        XCTAssertEqual(store.connections.value?.first?.connected, true, "rollback restores the row")
    }

    // MARK: - Feeds & calendars

    func testSubscribeFeedAppendsThenRollsBack() async throws {
        let api = FakeSyncAPI()
        api.failWrites = true
        api.replies[.feeds] = .notModified
        let store = Store(cache: tempCache(), api: api)
        store.feeds.value = [FeedSubscription(url: "https://a.example/rss")]

        let ok = await store.perform(SubscribeFeed(url: "https://b.example/rss"))
        XCTAssertFalse(ok)
        XCTAssertEqual(store.feeds.value?.map(\.url), ["https://a.example/rss"])
        XCTAssertEqual(store.toast, "Couldn't subscribe to that feed — reverted")
    }

    func testUnsubscribeCalendarReinsertsAtTheSameIndex() async throws {
        let api = FakeSyncAPI()
        api.failWrites = true
        api.replies[.calendars] = .notModified
        let store = Store(cache: tempCache(), api: api)
        store.calendars.value = [
            CalendarSubscription(url: "webcal://one"),
            CalendarSubscription(url: "webcal://two"),
            CalendarSubscription(url: "webcal://three"),
        ]

        let ok = await store.perform(UnsubscribeCalendar(url: "webcal://two"))
        XCTAssertFalse(ok)
        XCTAssertEqual(store.calendars.value?.map(\.url),
                       ["webcal://one", "webcal://two", "webcal://three"])
    }

    // MARK: - Banks

    /// The bank swap is instant (target bank's cached snapshots), and a failed
    /// activate puts the previous bank — data and roster flag — back.
    func testActivateBankSwapsImmediatelyAndRollsBack() async throws {
        let cache = tempCache()
        let roster: BanksResponse = try JSONDecoder().decode(
            BanksResponse.self,
            from: Data(#"{"banks":[{"name":"A","active":true},{"name":"B"}],"active":"A"}"#.utf8))
        let inboxA = try inboxItems(["a1"])
        let inboxB = try inboxItems(["b1", "b2"])
        await cache.save(roster, etag: "\"r\"", domain: .banks, bank: Store.rosterBank)
        await cache.save(inboxA, etag: "\"ia\"", domain: .inbox, bank: "A")
        await cache.save(inboxB, etag: "\"ib\"", domain: .inbox, bank: "B")
        await cache.flush()

        let api = FakeSyncAPI()
        api.replies[.banks] = .value(roster)
        let store = Store(cache: cache, api: api)
        await store.hydrate()
        XCTAssertEqual(store.bank, "A")
        XCTAssertEqual(store.inbox.value?.map(\.id), ["a1"])

        // The reconcile that follows (success or failure) must not overwrite
        // the hydrated inbox with the fake's default fixture.
        api.replies[.inbox] = .notModified
        api.gateWrites = true
        let inFlight = Task { await store.perform(ActivateBank(name: "B")) }
        await api.waitForParkedWrite()

        XCTAssertEqual(store.bank, "B", "the swap happens before the POST is answered")
        XCTAssertEqual(store.inbox.value?.map(\.id), ["b1", "b2"], "B's cached inbox is already on screen")
        XCTAssertEqual(store.banks.value?.active, "B")
        XCTAssertEqual(store.banks.value?.banks.first(where: { $0.name == "B" })?.active, true)

        // Now fail it: everything must go back to A.
        api.failWrites = true
        api.releaseWriteGate()
        let ok = await inFlight.value
        XCTAssertFalse(ok)

        XCTAssertEqual(store.bank, "A")
        XCTAssertEqual(store.inbox.value?.map(\.id), ["a1"], "A's snapshots are re-hydrated")
        XCTAssertEqual(store.banks.value?.active, "A")
        XCTAssertEqual(store.toast, "Couldn't switch project — reverted")
    }

    // MARK: - Sleep

    func testTriggerSleepFlipsStatusRunningAndRollsBack() async throws {
        let api = FakeSyncAPI()
        api.failWrites = true
        // `/status` is unconditional (no 304); make the failure-path reconcile
        // throw instead, which leaves the snapshot untouched.
        api.replies[.status] = .failure
        let store = Store(cache: tempCache(), api: api)
        store.status.value = StatusSnapshot(
            sleep: .init(status: "idle", stage: 0, totalStages: 5, cycleId: nil, error: nil),
            inbox: .init(total: 0, byKind: [:]),
            episodes: .init(unprocessed: 3, lastIngestedAt: nil),
            lastSleepAt: nil, nextSleepAt: nil)

        api.gateWrites = true
        let inFlight = Task { await store.perform(TriggerSleep()) }
        await api.waitForParkedWrite()
        XCTAssertEqual(store.status.value?.sleep.status, "running", "the dashboard reacts on the click")

        api.releaseWriteGate()
        let ok = await inFlight.value
        XCTAssertFalse(ok)
        XCTAssertEqual(store.status.value?.sleep.status, "idle", "a failed trigger restores the status")
        XCTAssertEqual(store.toast, "Couldn't start the sleep cycle — reverted")
    }

    // MARK: - Review fixes

    /// Inbox ids are only unique within a bank (`inbox-001` exists in every
    /// one), so an optimistic hide must not survive a bank switch — otherwise
    /// resolving A's `inbox-001` permanently blanks B's.
    func testHiddenInboxIdsDoNotSurviveABankSwitch() async throws {
        let cache = tempCache()
        let shared = try inboxItems(["inbox-001", "inbox-002"])
        await cache.save(shared, etag: "\"ib\"", domain: .inbox, bank: "B")
        await cache.flush()

        let api = FakeSyncAPI()
        let store = Store(cache: cache, api: api)
        await store.hydrate(bank: "A")
        store.inbox.value = shared
        store.hiddenInboxIds.insert("inbox-001")
        XCTAssertEqual(store.visibleInbox.map(\.id), ["inbox-002"])

        await store.hydrate(bank: "B")

        XCTAssertTrue(store.hiddenInboxIds.isEmpty, "hides are per-bank")
        XCTAssertEqual(store.visibleInbox.map(\.id), ["inbox-001", "inbox-002"],
                       "bank B's own item with the same id must be visible")
    }

    /// `optimistic` moves `store.bank` before the `.banks` refresh runs, so
    /// `Store.refresh`'s own `active != previous` fan-out can never fire for an
    /// activate — the mutation has to ask for every domain itself.
    func testActivateBankReconcilesEveryDomain() async throws {
        let cache = tempCache()
        let roster: BanksResponse = try JSONDecoder().decode(
            BanksResponse.self,
            from: Data(#"{"banks":[{"name":"A","active":true},{"name":"B"}],"active":"A"}"#.utf8))
        await cache.save(roster, etag: "\"r\"", domain: .banks, bank: Store.rosterBank)
        await cache.flush()

        let api = FakeSyncAPI()
        api.replies[.banks] = .value(roster)
        let store = Store(cache: cache, api: api)
        await store.hydrate()

        // The server agrees B is active by the time the reconcile asks, so
        // `Store.refresh`'s own `active != previous` fan-out stays silent —
        // whatever gets fetched here is what this mutation asked for.
        api.replies[.banks] = .value(try JSONDecoder().decode(
            BanksResponse.self,
            from: Data(#"{"banks":[{"name":"A"},{"name":"B","active":true}],"active":"B"}"#.utf8)))
        api.calls.removeAll()

        let ok = await store.perform(ActivateBank(name: "B"))
        XCTAssertTrue(ok)
        // `.askHistory` (G52) has no server endpoint to reconcile against —
        // `Store.refresh` skips it explicitly — so it never generates an API
        // call even though it's part of `allCases`.
        XCTAssertEqual(Set(api.calls), Set(SyncDomain.allCases).subtracting([.askHistory]),
                       "a successful activate reconciles the whole bank")
        XCTAssertEqual(api.calls.first, .banks, "the roster is refreshed first")
    }

    /// A refresh landing while the write is parked must survive the rollback:
    /// only the row this mutation touched is put back, and `perform` reconciles
    /// `.connections` afterwards so the server has the last word either way.
    func testRollbackKeepsConcurrentServerStateAndRefreshes() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: tempCache(), api: api)
        store.connections.value = [connection(id: "claude-plan", plan: "max", tier: "5x")]

        api.gateWrites = true
        api.failWrites = true
        let inFlight = Task { await store.perform(SetConnectionTier(id: "claude-plan", tier: "20x")) }
        await api.waitForParkedWrite()
        XCTAssertEqual(store.connections.value?.first?.tier, "20x")

        // An SSE-driven refresh lands mid-flight: a newer array, with a row
        // this mutation knows nothing about.
        api.replies[.connections] = .value([
            connection(id: "claude-plan", plan: "max", tier: "20x"),
            connection(id: "chatgpt-plan", plan: "pro", tier: "5x"),
        ])
        await store.refresh([.connections])
        XCTAssertEqual(store.connections.value?.count, 2)

        // Now fail the write. The post-rollback reconcile is answered 304, so
        // what we observe is exactly what the rollback left behind.
        api.replies[.connections] = .notModified
        let callsBefore = api.calls.filter { $0 == .connections }.count
        api.releaseWriteGate()
        let ok = await inFlight.value

        XCTAssertFalse(ok)
        XCTAssertEqual(store.connections.value?.count, 2,
                       "the row that arrived mid-flight must not be clobbered")
        XCTAssertEqual(store.connections.value?.first(where: { $0.id == "chatgpt-plan" })?.tier, "5x")
        XCTAssertEqual(store.connections.value?.first(where: { $0.id == "claude-plan" })?.tier, "5x",
                       "only the affected row is reverted, to its pre-mutation value")
        XCTAssertGreaterThan(api.calls.filter { $0 == .connections }.count, callsBefore,
                             "the failure path reconciles with the server")
    }

    /// The same narrowness for the sleep status: a `/status` refresh that
    /// landed mid-flight keeps its inbox/episode counters through the rollback.
    func testTriggerSleepRollbackKeepsTheRestOfTheSnapshot() async throws {
        let api = FakeSyncAPI()
        api.replies[.status] = .failure
        let store = Store(cache: tempCache(), api: api)
        store.status.value = StatusSnapshot(
            sleep: .init(status: "idle", stage: 0, totalStages: 5, cycleId: nil, error: nil),
            inbox: .init(total: 0, byKind: [:]),
            episodes: .init(unprocessed: 0, lastIngestedAt: nil),
            lastSleepAt: nil, nextSleepAt: nil)

        api.gateWrites = true
        api.failWrites = true
        let inFlight = Task { await store.perform(TriggerSleep()) }
        await api.waitForParkedWrite()

        // A newer status lands while the trigger is in flight.
        store.status.value?.episodes.unprocessed = 7

        api.releaseWriteGate()
        let ok = await inFlight.value

        XCTAssertFalse(ok)
        XCTAssertEqual(store.status.value?.sleep.status, "idle", "our own flip is undone")
        XCTAssertEqual(store.status.value?.episodes.unprocessed, 7,
                       "everything else the snapshot learned meanwhile is kept")
    }
}
