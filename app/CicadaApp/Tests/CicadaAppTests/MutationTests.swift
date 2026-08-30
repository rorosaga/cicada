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
                         billing: "subscription", engineRole: nil, detail: nil, login: nil)
    }

    // MARK: - Inbox

    /// The card disappears the instant the user clicks, and a failed request
    /// puts it back exactly where it was.
    func testInboxResolveHidesOptimisticallyAndRollsBackInPlace() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: tempCache(), api: api)
        store.inbox.value = try inboxItems(["a", "b", "c"])

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
        XCTAssertEqual(api.writes, ["resolveInbox:b:archive"])
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
}
