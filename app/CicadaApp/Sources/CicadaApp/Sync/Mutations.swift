import Foundation

/// A user action that changes server state (§5.4).
///
/// The contract: `optimistic` paints the intended result into the `Store`
/// immediately so the UI reacts within a frame; `request` sends it; `rollback`
/// undoes exactly what `optimistic` did if the request never landed. Nothing
/// here decides *what the server said* — the authoritative state arrives with
/// the follow-up refresh of `refreshDomains` (or, for the connection paths, a
/// `fresh: true` probe the view model already owns).
///
/// `optimistic`/`rollback` are `async` (the brief's sketch had them sync)
/// because `ActivateBank` has to `await store.hydrate(bank:)` to swap the
/// target bank's cached snapshots in — everything else awaits nothing.
@MainActor
protocol Mutation {
    func optimistic(_ store: Store) async
    func request(_ api: any SyncAPI) async throws
    func rollback(_ store: Store) async
    /// Shown as a toast when the request fails and the change is reverted.
    var failureMessage: String { get }
    /// Reconciled after the server confirms. Empty when the caller owns the
    /// follow-up refresh itself.
    var refreshDomains: Set<SyncDomain> { get }
}

extension Mutation {
    var refreshDomains: Set<SyncDomain> { [] }
}

/// Reference cell letting a value-type `Mutation` stash the state it captured
/// in `optimistic` so `rollback` can restore it. Everything touching it is
/// `@MainActor`-isolated through the protocol, so no locking is needed.
@MainActor
final class MutationMemo<T> {
    var value: T?
    init() {}
}

// MARK: - Inbox

/// Resolve one inbox item. Every action but `skip` removes the item from the
/// queue server-side, so the card is hidden the moment the user clicks.
///
/// The hide is recorded in `Store.hiddenInboxIds` rather than by deleting the
/// element from `store.inbox.value`: the snapshot's value must stay in lockstep
/// with its ETag (a locally-edited array paired with the server's validator
/// would be silently wrong on the next 304), and keeping the element in place
/// makes "reinsert at its original index" on rollback free.
struct InboxResolve: Mutation {
    let id: String
    let action: String
    var answer: String? = nil
    /// G60: the key of the option the user picked ("a", "b", "both", "neither").
    var optionKey: String? = nil
    /// G60: with `action == "defer"`, how far out to push the reminder.
    var remindDays: Int? = nil
    var mergeTarget: String? = nil
    var mergeSurvivor: String? = nil

    /// `skip` deliberately keeps the item in the queue — nothing to hide.
    /// `defer` DOES hide: the server sets `remind_after`, so the card is gone
    /// from the pending list either way.
    private var hides: Bool { action != "skip" }

    func optimistic(_ store: Store) async {
        if hides { store.hiddenInboxIds.insert(id) }
    }

    func request(_ api: any SyncAPI) async throws {
        try await api.resolveInbox(id: id, action: action, answer: answer,
                                   optionKey: optionKey, remindDays: remindDays,
                                   mergeTarget: mergeTarget, mergeSurvivor: mergeSurvivor)
    }

    func rollback(_ store: Store) async {
        store.hiddenInboxIds.remove(id)
    }

    var failureMessage: String { "Couldn't resolve that item — reverted" }
    var refreshDomains: Set<SyncDomain> { [.inbox] }
}

// MARK: - Connections

/// Client-side mirror of `api/services/pricing.py`, used only to paint the
/// price/label a tier change *will* produce. The server's own answer replaces
/// it on the next probe — this table existing is a latency optimisation, not a
/// source of truth, so a drift shows for one round-trip at worst.
enum ClientPricing {
    static let subscriptionPrices: [String: [String: Double]] = [
        "claude-plan": ["pro": 20, "max-5x": 100, "max-20x": 200],
        "chatgpt-plan": ["free": 0, "go": 8, "plus": 20, "pro-5x": 100, "pro-20x": 200],
        "gemini-plan": ["pro": 19.99, "ultra-5x": 99.99, "ultra-20x": 199.99],
        "copilot-plan": ["pro": 10, "pro-plus": 39, "max": 100],
    ]

    /// (connection, plan) → the tiers the user must choose between.
    static let tiered: [String: [String: [String]]] = [
        "claude-plan": ["max": ["5x", "20x"]],
        "chatgpt-plan": ["pro": ["5x", "20x"]],
        "gemini-plan": ["ultra": ["5x", "20x"]],
    ]

    static let brands = [
        "claude-plan": "Claude", "chatgpt-plan": "ChatGPT",
        "gemini-plan": "Google AI", "copilot-plan": "Copilot",
    ]

    static func isTiered(_ connectionId: String, plan: String?) -> Bool {
        guard let plan else { return false }
        return tiered[connectionId]?[plan.lowercased()] != nil
    }

    /// USD/month for a (connection, plan, tier), or nil when the plan is
    /// tiered and no tier is chosen (matching `pricing.price_for`).
    static func price(_ connectionId: String, plan: String?, tier: String?) -> Double? {
        guard let plan else { return nil }
        let table = subscriptionPrices[connectionId] ?? [:]
        let key = plan.lowercased()
        if let tiers = tiered[connectionId]?[key] {
            guard let tier, tiers.contains(tier) else { return nil }
            return table["\(key)-\(tier)"]
        }
        return table[key]
    }

    /// "Claude Max 20x" — mirrors `pricing.plan_label`.
    static func planLabel(_ connectionId: String, plan: String?, tier: String?) -> String? {
        guard let plan else { return nil }
        let brand = brands[connectionId] ?? connectionId
        var label = "\(brand) \(plan.replacingOccurrences(of: "-", with: " ").capitalized)"
        if let tier, isTiered(connectionId, plan: plan) { label += " \(tier)" }
        return label
    }
}

/// Base for the four connection mutations: replaces one row in
/// `store.connections`, returning the row as it was so `rollback` can put
/// *that row* back without touching the rest of the array.
///
/// Restoring the whole memoised array would clobber anything that landed while
/// the request was in flight (an SSE-driven refresh, another mutation) — the
/// rollback must be as narrow as the optimistic change was.
@MainActor
@discardableResult
private func patchConnection(_ store: Store, id: String,
                             _ transform: (ConnectionStatus) -> ConnectionStatus) -> ConnectionStatus? {
    guard var rows = store.connections.value,
          let index = rows.firstIndex(where: { $0.id == id }) else { return nil }
    let before = rows[index]
    rows[index] = transform(rows[index])
    store.connections.value = rows
    return before
}

/// Put one row back exactly as it was, leaving every other row alone. A row
/// that vanished from the array meanwhile (a refresh dropped it) is not
/// resurrected — the follow-up reconcile in `Store.perform` is authoritative.
@MainActor
private func restoreConnection(_ store: Store, _ row: ConnectionStatus?) {
    guard let row, var rows = store.connections.value,
          let index = rows.firstIndex(where: { $0.id == row.id }) else { return }
    rows[index] = row
    store.connections.value = rows
}

/// Pick a subscription tier (Claude Max 5x/20x, ChatGPT Pro 5x/20x). The price
/// and label are computed locally so the card updates instantly.
struct SetConnectionTier: Mutation {
    let id: String
    let tier: String?
    private let memo = MutationMemo<ConnectionStatus>()

    init(id: String, tier: String?) {
        self.id = id
        self.tier = tier
    }

    func optimistic(_ store: Store) async {
        memo.value = patchConnection(store, id: id) { row in
            row.patching(
                tier: .some(tier),
                planLabel: .some(ClientPricing.planLabel(id, plan: row.plan, tier: tier)),
                priceUsdMonth: .some(ClientPricing.price(id, plan: row.plan, tier: tier)),
                priceNote: .some(tier == nil ? "pick your tier" : "verified locally")
            )
        }
    }

    func request(_ api: any SyncAPI) async throws {
        _ = try await api.setConnectionTier(id, tier: tier)
    }

    func rollback(_ store: Store) async {
        restoreConnection(store, memo.value)
    }

    var failureMessage: String { "Couldn't change the plan tier — reverted" }
    /// Reconciled on both paths: on success the server's real row (account,
    /// price note) replaces the locally-painted one; on failure it settles
    /// whatever else moved while the write was in flight.
    var refreshDomains: Set<SyncDomain> { [.connections] }
}

/// Make (or unmake) the Claude plan the Sleep engine. Optimistic: the toggle
/// moves at once and rolls back with a toast if the write fails.
struct SetUseForSleep: Mutation {
    let id: String
    let on: Bool
    private let memo = MutationMemo<ConnectionStatus>()

    func optimistic(_ store: Store) async {
        memo.value = patchConnection(store, id: id) { row in
            row.patching(useForSleep: on)
        }
    }

    func request(_ api: any SyncAPI) async throws {
        _ = try await api.setUseForSleep(id, on: on)
    }

    func rollback(_ store: Store) async {
        restoreConnection(store, memo.value)
    }

    var failureMessage: String { "Couldn't change the Sleep engine — reverted" }
    var refreshDomains: Set<SyncDomain> { [.connections] }
}

/// Save an API key for a key-based connection: it reads as connected at once.
struct SetConnectionKey: Mutation {
    let id: String
    let key: String
    private let memo = MutationMemo<ConnectionStatus>()

    init(id: String, key: String) {
        self.id = id
        self.key = key
    }

    func optimistic(_ store: Store) async {
        memo.value = patchConnection(store, id: id) { $0.patching(connected: true) }
    }

    func request(_ api: any SyncAPI) async throws {
        _ = try await api.setConnectionKey(id, key: key)
    }

    func rollback(_ store: Store) async {
        restoreConnection(store, memo.value)
    }

    var failureMessage: String { "Couldn't save that key — reverted" }
    /// Reconciled on both paths: on success the server's real row (account,
    /// price note) replaces the locally-painted one; on failure it settles
    /// whatever else moved while the write was in flight.
    var refreshDomains: Set<SyncDomain> { [.connections] }
}

struct RemoveConnectionKey: Mutation {
    let id: String
    private let memo = MutationMemo<ConnectionStatus>()

    init(id: String) { self.id = id }

    func optimistic(_ store: Store) async {
        memo.value = patchConnection(store, id: id) { $0.patching(connected: false) }
    }

    func request(_ api: any SyncAPI) async throws {
        _ = try await api.removeConnectionKey(id)
    }

    func rollback(_ store: Store) async {
        restoreConnection(store, memo.value)
    }

    var failureMessage: String { "Couldn't remove that key — reverted" }
    /// Reconciled on both paths: on success the server's real row (account,
    /// price note) replaces the locally-painted one; on failure it settles
    /// whatever else moved while the write was in flight.
    var refreshDomains: Set<SyncDomain> { [.connections] }
}

struct LogoutConnection: Mutation {
    let id: String
    private let memo = MutationMemo<ConnectionStatus>()

    init(id: String) { self.id = id }

    func optimistic(_ store: Store) async {
        memo.value = patchConnection(store, id: id) { $0.patching(connected: false) }
    }

    func request(_ api: any SyncAPI) async throws {
        _ = try await api.logoutConnection(id)
    }

    func rollback(_ store: Store) async {
        restoreConnection(store, memo.value)
    }

    var failureMessage: String { "Couldn't disconnect — reverted" }
    /// Reconciled on both paths: on success the server's real row (account,
    /// price note) replaces the locally-painted one; on failure it settles
    /// whatever else moved while the write was in flight.
    var refreshDomains: Set<SyncDomain> { [.connections] }
}

// MARK: - Feeds & calendars

struct SubscribeFeed: Mutation {
    let url: String
    var tags: [String] = []

    func optimistic(_ store: Store) async {
        var rows = store.feeds.value ?? []
        guard !rows.contains(where: { $0.url == url }) else { return }
        rows.append(FeedSubscription(url: url, tags: tags))
        store.feeds.value = rows
    }

    func request(_ api: any SyncAPI) async throws {
        _ = try await api.subscribeFeed(url: url, tags: tags)
    }

    func rollback(_ store: Store) async {
        store.feeds.value?.removeAll { $0.url == url }
    }

    var failureMessage: String { "Couldn't subscribe to that feed — reverted" }
    var refreshDomains: Set<SyncDomain> { [.feeds] }
}

struct UnsubscribeFeed: Mutation {
    let url: String
    private let memo = MutationMemo<(Int, FeedSubscription)>()

    init(url: String) { self.url = url }

    func optimistic(_ store: Store) async {
        guard var rows = store.feeds.value,
              let index = rows.firstIndex(where: { $0.url == url }) else { return }
        memo.value = (index, rows[index])
        rows.remove(at: index)
        store.feeds.value = rows
    }

    func request(_ api: any SyncAPI) async throws {
        try await api.unsubscribeFeed(url: url)
    }

    func rollback(_ store: Store) async {
        guard let (index, row) = memo.value, var rows = store.feeds.value else { return }
        rows.insert(row, at: min(index, rows.count))
        store.feeds.value = rows
    }

    var failureMessage: String { "Couldn't unsubscribe from that feed — reverted" }
    var refreshDomains: Set<SyncDomain> { [.feeds] }
}

struct SubscribeCalendar: Mutation {
    let url: String
    var tags: [String] = []

    func optimistic(_ store: Store) async {
        var rows = store.calendars.value ?? []
        guard !rows.contains(where: { $0.url == url }) else { return }
        rows.append(CalendarSubscription(url: url, tags: tags))
        store.calendars.value = rows
    }

    func request(_ api: any SyncAPI) async throws {
        _ = try await api.subscribeCalendar(url: url, tags: tags)
    }

    func rollback(_ store: Store) async {
        store.calendars.value?.removeAll { $0.url == url }
    }

    var failureMessage: String { "Couldn't subscribe to that calendar — reverted" }
    var refreshDomains: Set<SyncDomain> { [.calendars] }
}

struct UnsubscribeCalendar: Mutation {
    let url: String
    private let memo = MutationMemo<(Int, CalendarSubscription)>()

    init(url: String) { self.url = url }

    func optimistic(_ store: Store) async {
        guard var rows = store.calendars.value,
              let index = rows.firstIndex(where: { $0.url == url }) else { return }
        memo.value = (index, rows[index])
        rows.remove(at: index)
        store.calendars.value = rows
    }

    func request(_ api: any SyncAPI) async throws {
        try await api.unsubscribeCalendar(url: url)
    }

    func rollback(_ store: Store) async {
        guard let (index, row) = memo.value, var rows = store.calendars.value else { return }
        rows.insert(row, at: min(index, rows.count))
        store.calendars.value = rows
    }

    var failureMessage: String { "Couldn't unsubscribe from that calendar — reverted" }
    var refreshDomains: Set<SyncDomain> { [.calendars] }
}

// MARK: - Banks

/// Switch the active memory bank. The optimistic apply swaps `store.bank` and
/// re-hydrates every domain from *that bank's* disk cache, so the whole app
/// repaints on the new bank before the POST is even sent.
///
/// Domains the target bank has never cached come back empty rather than
/// showing the previous bank's data (`Store.hydrate`'s reset-on-miss rule) —
/// an honest empty state for the ~one round-trip until the reconcile lands.
struct ActivateBank: Mutation {
    let name: String
    private let memo = MutationMemo<(bank: String, roster: BanksResponse?)>()

    init(name: String) { self.name = name }

    func optimistic(_ store: Store) async {
        memo.value = (store.bank, store.banks.value)
        store.bank = name
        // Instant swap from cache. Must happen before the roster flag below:
        // `hydrate(bank:)` leaves `.banks` alone, but ordering it first keeps
        // the "paint the new bank, then mark it active" reading obvious.
        await store.hydrate(bank: name)
        if let roster = store.banks.value {
            store.banks.value = BanksResponse(
                banks: roster.banks.map { $0.settingActive($0.name == name) },
                active: name
            )
        }
    }

    func request(_ api: any SyncAPI) async throws {
        try await api.activateBank(name: name)
    }

    func rollback(_ store: Store) async {
        guard let previous = memo.value else { return }
        store.bank = previous.bank
        await store.hydrate(bank: previous.bank)
        store.banks.value = previous.roster
    }

    var failureMessage: String { "Couldn't switch project — reverted" }
    /// Every domain, not just `.banks`. `Store.refresh`'s own bank-switch
    /// fan-out keys off `active != previous`, and `optimistic` already moved
    /// `store.bank`, so that branch can never fire here — this mutation owns
    /// the post-switch reconcile itself. `refresh` walks `SyncDomain.allCases`
    /// with `.banks` first, exactly as `refreshAll` does.
    var refreshDomains: Set<SyncDomain> { Set(SyncDomain.allCases) }
}

// MARK: - Sleep

/// Kick off a sleep cycle. Flipping the status to `running` locally means the
/// dashboard and the menu-bar bookworm react on the click, not on the first
/// poll tick.
struct TriggerSleep: Mutation {
    /// Only the sleep *status string* is memoised, not the whole snapshot: a
    /// `/status` refresh or an SSE sleep event can land while the POST is in
    /// flight, and restoring a whole stale snapshot would throw its inbox and
    /// episode counts away too.
    private let memo = MutationMemo<String>()

    init() {}

    func optimistic(_ store: Store) async {
        memo.value = store.status.value?.sleep.status
        store.status.value?.sleep.status = "running"
    }

    func request(_ api: any SyncAPI) async throws {
        _ = try await api.triggerSleep()
    }

    func rollback(_ store: Store) async {
        // Only un-flip our own change, and only if nothing else has moved the
        // status on in the meantime.
        if let previous = memo.value, store.status.value?.sleep.status == "running" {
            store.status.value?.sleep.status = previous
        }
    }

    var failureMessage: String { "Couldn't start the sleep cycle — reverted" }
    /// Replace the optimistic `running` with the server's own answer as soon
    /// as the trigger returns — a cycle with nothing to do can already be
    /// idle again, and leaving a stale `running` in the Store would make the
    /// dashboard re-arm its poll on every later visit.
    var refreshDomains: Set<SyncDomain> { [.status] }
}

// MARK: - Browser syncs (R8)

/// A local-file sync has nothing to paint optimistically, but routing it
/// through `Store.perform` gives it the same failure toast and channel
/// reconcile every other write gets. The server's honest `{new, skipped}`
/// lands in `result` so the panel can show it (the `UnsubscribeFeed` memo
/// pattern — a value-type mutation stashing what its request learned).
/// `refreshDomains` covers everything a sync moves: the channel row's count
/// and last-sync, the Feed's sources list, and the status bar's queue count.
///
/// The failure copy never claims "nothing was imported": the backend ingests
/// in `MAX_BATCH` slices and re-raises on a later slice, so earlier slices
/// have already landed (`ingest_batch` can be partial for bookmarks too).
/// Pointing at the Feed is the honest statement (final review, finding 3).
struct SyncSafariTabs: Mutation {
    let db: Data
    let wal: Data?
    let devices: [String]?
    private let memo = MutationMemo<SafariTabsSyncResult>()

    init(db: Data, wal: Data?, devices: [String]?) { self.db = db; self.wal = wal; self.devices = devices }

    var result: SafariTabsSyncResult? { memo.value }
    func optimistic(_ store: Store) async {}
    func request(_ api: any SyncAPI) async throws { memo.value = try await api.syncSafariTabs(db: db, wal: wal, devices: devices) }
    func rollback(_ store: Store) async {}
    var failureMessage: String { "Couldn't finish importing those tabs — the Feed shows what landed" }
    var refreshDomains: Set<SyncDomain> { [.channels, .sources, .status] }
}

struct SyncBrowserBookmarks: Mutation {
    let chromeData: Data?
    let safariData: Data?
    let folders: [String]?
    private let memo = MutationMemo<BookmarkSyncResult>()

    init(chromeData: Data?, safariData: Data?, folders: [String]?) { self.chromeData = chromeData; self.safariData = safariData; self.folders = folders }

    var result: BookmarkSyncResult? { memo.value }
    func optimistic(_ store: Store) async {}
    func request(_ api: any SyncAPI) async throws { memo.value = try await api.syncBookmarks(chromeData: chromeData, safariData: safariData, folders: folders) }
    func rollback(_ store: Store) async {}
    var failureMessage: String { "Couldn't finish syncing those bookmarks — the Feed shows what landed" }
    var refreshDomains: Set<SyncDomain> { [.channels, .sources, .status] }
}
