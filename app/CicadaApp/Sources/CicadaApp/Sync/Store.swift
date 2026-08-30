import Foundation
import Observation
import os

/// Single source of truth for every screen (§5.1).
///
/// Holds one `Snapshot<T>` per sync domain. The contract every view can rely on:
/// a snapshot's `value` is only ever *replaced by something better* — a 304, a
/// network error or a decode failure never blanks it. Views therefore render
/// from disk-hydrated data on the very first frame and never flash empty.
@Observable
@MainActor
final class Store {
    /// The bank roster (`GET /banks`) is global — it lists every bank — so it
    /// is cached under a fixed pseudo-bank rather than inside whichever bank
    /// happened to be active. `hydrate()` reads it first to learn which bank's
    /// snapshots to load.
    static let rosterBank = "_roster"

    static let logger = Logger(subsystem: "com.cicada.app", category: "sync")

    // MARK: Snapshots

    var bank: String = "default"
    var graph = Snapshot<GraphResponse>()
    var inbox = Snapshot<[InboxItem]>()
    var banks = Snapshot<BanksResponse>()
    var sources = Snapshot<[MediaFeedItem]>()
    var feeds = Snapshot<[FeedSubscription]>()
    var calendars = Snapshot<[CalendarSubscription]>()
    var contributors = Snapshot<[Contributor]>()
    var origins = Snapshot<[OriginStat]>()
    var connections = Snapshot<[ConnectionStatus]>()
    var status = Snapshot<StatusSnapshot>()

    /// Full entity bodies, memoised. Bounded to `entityCacheLimit` in LRU order.
    var entities: [String: Entity] = [:]
    private var entityLRU: [String] = []
    private let entityCacheLimit = 200

    /// Inbox item ids hidden by an optimistic `InboxResolve` (§5.4). An id is
    /// dropped only once a refreshed snapshot no longer contains it — if a 304
    /// races the server-side delete, the item is still in `inbox.value` and
    /// un-hiding it here would flash the card back for one refresh cycle.
    var hiddenInboxIds: Set<String> = []

    /// The inbox as the UI should see it: the snapshot minus anything hidden
    /// by an in-flight or already-confirmed resolve.
    var visibleInbox: [InboxItem] {
        (inbox.value ?? []).filter { !hiddenInboxIds.contains($0.id) }
    }

    /// Transient one-line error surfaced by the UI. Set only when a refresh
    /// fails *and* we had nothing to show — a failed background refresh over
    /// good data stays silent.
    var toast: String?

    /// Last version vector seen from `/sync/version` or an SSE `version` event.
    var version: VersionVector?
    /// True while the SSE stream is connected.
    var isConnected: Bool = false
    /// Latest `event: sleep` payload; SleepViewModel observes this.
    var sleepEvent: SleepEventPayload?

    /// Pushed on every status change, carrying the running→idle edge timestamp
    /// so the menu-bar bookworm can show `digesting`. Wired in `CicadaApp`.
    @ObservationIgnored var onStatus: ((StatusSnapshot, Date?) -> Void)?
    @ObservationIgnored private var wasSleepRunning = false
    @ObservationIgnored private var justFinishedAt: Date?

    /// Domains that still owe us a successful reconcile. A domain enters on
    /// every refresh request and only leaves on a 200 or a 304, so a refresh
    /// that failed is retried by the next version event or poll tick instead
    /// of being stranded behind an already-committed version vector.
    @ObservationIgnored private var pendingDomains: Set<SyncDomain> = []
    /// Domains whose refresh was coalesced into an in-flight one and must
    /// re-run once it finishes.
    @ObservationIgnored private var wantsRefresh: Set<SyncDomain> = []

    // MARK: Collaborators

    @ObservationIgnored let cache: SnapshotCache
    @ObservationIgnored let api: any SyncAPI
    @ObservationIgnored let engine: SyncEngine

    init(cache: SnapshotCache = SnapshotCache(), api: any SyncAPI = APIClient.shared) {
        self.cache = cache
        self.api = api
        self.engine = SyncEngine(api: api)
        self.engine.attach(store: self)
    }

    // MARK: - Hydration

    @ObservationIgnored private var didBootstrap = false

    /// Launch sequence: disk first (instant frame), network second, then live.
    /// Idempotent — SwiftUI can fire `.onAppear` more than once for the same
    /// window and we must not double-hydrate or open two SSE streams.
    func bootstrap() async {
        if !didBootstrap {
            didBootstrap = true
            await hydrate()
            // The engine starts only AFTER the first full reconcile: an SSE
            // `version` event arriving mid-`refreshAll` would otherwise race
            // the same conditional GETs against themselves.
            await refreshAll()
        }
        // Cheap to call again: a window that reappears after `stop()` gets a
        // live stream back without re-running the whole launch sequence.
        if !engine.isRunning { engine.start() }
    }

    /// Load every domain from disk. Called before the first frame: no network,
    /// no awaiting the backend, so the window opens on real data.
    ///
    /// Pass `bank:` when the caller already knows which bank to load (the
    /// bank-switch path does). Without it we read the cached roster to find
    /// the active bank — and must `flush()` first, because the roster we just
    /// fetched is still sitting in the cache's 500 ms debounce and reading
    /// past it would flip `bank` straight back to the previous one.
    func hydrate(bank explicitBank: String? = nil) async {
        // Optimistic inbox hides are per-bank: ids are only unique *within* a
        // bank (`inbox-001` exists in every one), so a hide carried across a
        // switch would blank an unrelated item in the new bank.
        hiddenInboxIds.removeAll()
        if let explicitBank {
            bank = explicitBank
        } else {
            await cache.flush()
            if let roster = await cache.load(.banks, bank: Self.rosterBank, as: BanksResponse.self) {
                banks.value = roster.value
                banks.etag = roster.etag
                banks.loadedAt = Date()
                if let active = roster.value.active, !active.isEmpty { bank = active }
            }
        }
        var loaded: [String] = banks.value == nil ? [] : ["banks"]
        /// Load one domain for `bank`. On a MISS the snapshot is **reset**, not
        /// left alone: after a bank switch the in-memory value belongs to the
        /// previous bank, and keeping it would render A's graph under B's label
        /// (and send A's etag to B, earning a 304 that hides the real data)
        /// for the whole window until the sequential reconcile catches up.
        /// An empty snapshot makes views show their own empty/loading state.
        @discardableResult
        func take<T: Codable>(_ domain: SyncDomain, _ kp: ReferenceWritableKeyPath<Store, Snapshot<T>>) async -> Bool {
            guard let hit = await cache.load(domain, bank: bank, as: T.self) else {
                self[keyPath: kp] = Snapshot<T>()
                return false
            }
            self[keyPath: kp].value = hit.value
            self[keyPath: kp].etag = hit.etag
            self[keyPath: kp].loadedAt = Date()
            self[keyPath: kp].isRefreshing = false
            loaded.append(domain.rawValue)
            return true
        }
        await take(.graph, \.graph)
        await take(.inbox, \.inbox)
        await take(.sources, \.sources)
        await take(.feeds, \.feeds)
        await take(.calendars, \.calendars)
        await take(.contributors, \.contributors)
        await take(.origins, \.origins)
        await take(.connections, \.connections)
        // Only feed the menu bar when this bank actually had a cached status —
        // otherwise the bookworm would render the previous bank's mood.
        let hasStatus = await take(.status, \.status)
        if hasStatus, let s = status.value { pushStatus(s) }
        let summary = "hydrate bank=\(bank) loaded=[\(loaded.joined(separator: ","))]"
        Self.logger.notice("\(summary, privacy: .public)")
    }

    // MARK: - Refresh

    func refreshAll() async {
        await refresh(Set(SyncDomain.allCases))
    }

    /// Conditionally refresh the given domains. `.banks` is handled first: if
    /// the active bank moved, we re-hydrate that bank from disk (instant swap)
    /// and then reconcile every domain against the network.
    func refresh(_ domains: Set<SyncDomain>) async {
        pendingDomains.formUnion(domains)
        var remaining = domains
        if remaining.remove(.banks) != nil {
            let previous = bank
            await refreshOne(.banks, \.banks) { [api] etag in try await api.fetchBanks(etag: etag) }
            if let active = banks.value?.active, !active.isEmpty, active != previous {
                Self.logger.notice("bank switched \(previous, privacy: .public) → \(active, privacy: .public)")
                // Hydrate the target bank explicitly — re-reading the roster
                // here would race the debounced write we just queued.
                await hydrate(bank: active)
                remaining = Set(SyncDomain.allCases).subtracting([.banks])
                pendingDomains.formUnion(remaining)
            }
        }
        // Deterministic order keeps test assertions and log lines readable.
        for domain in SyncDomain.allCases where remaining.contains(domain) {
            switch domain {
            case .banks: continue
            case .graph: await refreshOne(domain, \.graph) { [api] e in try await api.fetchGraph(etag: e) }
            case .inbox: await refreshOne(domain, \.inbox) { [api] e in try await api.fetchInbox(etag: e) }
            case .sources: await refreshOne(domain, \.sources) { [api] e in try await api.fetchSources(etag: e) }
            case .feeds: await refreshOne(domain, \.feeds) { [api] e in try await api.fetchFeeds(etag: e) }
            case .calendars: await refreshOne(domain, \.calendars) { [api] e in try await api.fetchCalendars(etag: e) }
            case .contributors: await refreshOne(domain, \.contributors) { [api] e in try await api.fetchContributors(etag: e) }
            case .origins: await refreshOne(domain, \.origins) { [api] e in try await api.fetchOrigins(etag: e) }
            case .connections: await refreshOne(domain, \.connections) { [api] e in try await api.fetchConnections(etag: e) }
            case .status: await refreshStatus()
            // Ask (G52) history has no server endpoint to reconcile against —
            // `AskViewModel` owns its own read/write through `store.cache`
            // directly. Nothing to do here; just don't let it fall through
            // to a case that doesn't exist.
            case .askHistory:
                pendingDomains.remove(.askHistory)
                continue
            }
        }
    }

    /// One domain: conditional GET → assign → persist. Never blanks a value.
    ///
    /// Coalescing: a request for a domain already in flight does not issue a
    /// second GET — it records `wantsRefresh` and the in-flight call re-runs
    /// itself once, so the newest state is still picked up exactly once.
    ///
    /// `fetch` is `@escaping` and the re-run is a loop rather than recursion:
    /// suspending inside a *non-escaping* async closure parameter and resuming
    /// it from another task tripped Swift's task allocator ("freed pointer was
    /// not the last allocation") intermittently.
    private func refreshOne<T: Codable>(
        _ domain: SyncDomain,
        _ kp: ReferenceWritableKeyPath<Store, Snapshot<T>>,
        fetch: @escaping (String?) async throws -> Conditional<T>
    ) async {
        guard !self[keyPath: kp].isRefreshing else {
            wantsRefresh.insert(domain)
            return
        }
        self[keyPath: kp].isRefreshing = true
        repeat {
            // The bank this request belongs to. A GET issued for bank A can
            // land after the user switched to B; writing A's payload (and A's
            // etag) into B's slot is the same cross-bank bleed `hydrate`
            // guards against, just arriving from the network instead of disk.
            let epoch = bank
            do {
                let result = try await fetch(self[keyPath: kp].etag)
                // `.banks` is global (cached under `rosterBank`) — a roster
                // response is valid whichever bank is active, and discarding
                // it would strand the switch that this very response reports.
                if domain != .banks, bank != epoch {
                    Self.logger.debug("discarding stale \(domain.rawValue, privacy: .public) response from bank \(epoch, privacy: .public)")
                    self[keyPath: kp].isRefreshing = false
                    wantsRefresh.remove(domain)
                    return  // still pending: the post-switch reconcile refetches it
                }
                if !result.notModified, let value = result.value {
                    self[keyPath: kp].value = value
                    self[keyPath: kp].etag = result.etag
                    self[keyPath: kp].loadedAt = Date()
                    if domain == .inbox { pruneHiddenInboxIds() }
                    await cache.save(value, etag: result.etag,
                                     domain: domain, bank: domain == .banks ? Self.rosterBank : bank)
                }
                // 200 and 304 both mean "we are in sync with the server".
                pendingDomains.remove(domain)
            } catch {
                if self[keyPath: kp].isEmpty { toast = "Couldn't load \(domain.rawValue)" }
                Self.logger.debug("refresh \(domain.rawValue, privacy: .public) failed: \(String(describing: error))")
            }
            // `isRefreshing` stays true across the re-run so requests arriving
            // mid-loop keep coalescing instead of starting a parallel fetch.
        } while wantsRefresh.remove(domain) != nil
        self[keyPath: kp].isRefreshing = false
    }

    /// `/status` is small and volatile — plain GET, no etag.
    private func refreshStatus() async {
        guard !status.isRefreshing else {
            wantsRefresh.insert(.status)
            return
        }
        status.isRefreshing = true
        repeat {
            let epoch = bank
            do {
                let snapshot = try await api.fetchStatus()
                // Same epoch guard as `refreshOne`: a status fetched for the
                // previous bank must not feed the menu-bar bookworm the wrong
                // bank's mood after a switch.
                if bank != epoch {
                    status.isRefreshing = false
                    wantsRefresh.remove(.status)
                    return
                }
                status.value = snapshot
                status.loadedAt = Date()
                await cache.save(snapshot, etag: nil, domain: .status, bank: bank)
                pendingDomains.remove(.status)
                pushStatus(snapshot)
            } catch {
                if status.isEmpty { toast = "Couldn't load status" }
            }
        } while wantsRefresh.remove(.status) != nil
        status.isRefreshing = false
    }

    /// Tracks the sleep running→idle edge (so the bookworm can `digest`) and
    /// forwards the snapshot to whoever is listening (the menu bar).
    private func pushStatus(_ snapshot: StatusSnapshot) {
        let nowRunning = snapshot.sleep.status == "running"
        if wasSleepRunning, !nowRunning { justFinishedAt = Date() }
        wasSleepRunning = nowRunning
        onStatus?(snapshot, justFinishedAt)
    }

    /// Merge a live `event: sleep` payload into the status snapshot without
    /// waiting for the next `/status` fetch.
    func applySleepEvent(_ event: SleepEventPayload) {
        sleepEvent = event
        // Push on EVERY sleep event, even before the first `/status` landed —
        // otherwise a cycle that starts and ends between two status refreshes
        // never shows its running→idle edge and the worm never digests.
        var snapshot = status.value ?? Self.blankStatus
        snapshot.sleep = StatusSnapshot.Sleep(
            status: event.status,
            stage: event.stage,
            totalStages: event.totalStages,
            cycleId: event.cycleId,
            error: event.error
        )
        status.value = snapshot
        pushStatus(snapshot)
    }

    /// Neutral snapshot used when a sleep event arrives before `/status` has
    /// ever resolved. Mirrors `MenuBarManager`'s own unknown snapshot.
    private static let blankStatus = StatusSnapshot(
        sleep: .init(status: "idle", stage: 0, totalStages: 5, cycleId: nil, error: nil),
        inbox: .init(total: 0, byKind: [:]),
        episodes: .init(unprocessed: 0, lastIngestedAt: nil),
        lastSleepAt: nil,
        nextSleepAt: nil
    )

    // MARK: - Mutations (§5.4)

    /// Apply a mutation optimistically, then send it. On failure the change is
    /// rolled back and a toast explains why; on success the mutation's own
    /// domains are reconciled so the server's authoritative version replaces
    /// the locally-painted one.
    ///
    /// Returns whether the request landed, so callers can reset per-row UI
    /// state (a spinner, a dimmed card) instead of leaving it stuck.
    @discardableResult
    func perform(_ mutation: any Mutation) async -> Bool {
        await mutation.optimistic(self)
        do {
            try await mutation.request(api)
            let domains = mutation.refreshDomains
            if !domains.isEmpty { await refresh(domains) }
            return true
        } catch {
            await mutation.rollback(self)
            toast = mutation.failureMessage
            Self.logger.debug("mutation failed: \(String(describing: error))")
            // The rollback restores what this mutation changed, but it cannot
            // know what else moved while the request was in flight (an SSE
            // refresh, another mutation). Reconcile the same domains so the
            // server's view wins within one round-trip either way.
            let domains = mutation.refreshDomains
            if !domains.isEmpty { await refresh(domains) }
            return false
        }
    }

    /// Drop hidden inbox ids the server has actually removed. Ids still
    /// present in the fresh snapshot stay hidden — a 304 or a snapshot taken
    /// just before the delete would otherwise flash a resolved card back.
    private func pruneHiddenInboxIds() {
        guard !hiddenInboxIds.isEmpty, let items = inbox.value else { return }
        hiddenInboxIds.formIntersection(Set(items.map(\.id)))
    }

    // MARK: - Version diffing

    /// Apply a new version vector: refresh only the domains whose components
    /// moved. A `bank` component change fans out to everything (see
    /// `VersionVector.changedDomains`).
    func apply(version newVersion: VersionVector) async {
        pendingDomains.formUnion(newVersion.changedDomains(since: version))
        version = newVersion
        // Domains left over from a failed earlier refresh ride along: the
        // version is already committed, so this is their only retry path.
        guard !pendingDomains.isEmpty else { return }
        await refresh(pendingDomains)
    }

    // MARK: - Entities

    /// Full entity body, memoised (LRU, 200 entries).
    func entity(_ id: String) async -> Entity? {
        if let cached = entities[id] {
            touchEntity(id)
            return cached
        }
        do {
            let entity = try await api.fetchEntity(id: id)
            entities[id] = entity
            touchEntity(id)
            return entity
        } catch {
            return nil
        }
    }

    /// Drop a cached entity so the next read refetches (post-mutation).
    func invalidateEntity(_ id: String) {
        entities[id] = nil
        entityLRU.removeAll { $0 == id }
    }

    private func touchEntity(_ id: String) {
        entityLRU.removeAll { $0 == id }
        entityLRU.append(id)
        while entityLRU.count > entityCacheLimit {
            let evicted = entityLRU.removeFirst()
            entities[evicted] = nil
        }
    }
}
