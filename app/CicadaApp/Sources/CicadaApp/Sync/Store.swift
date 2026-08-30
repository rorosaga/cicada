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
            await refreshAll()
        }
        // Cheap to call again: a window that reappears after `stop()` gets a
        // live stream back without re-running the whole launch sequence.
        if !engine.isRunning { engine.start() }
    }

    /// Load every domain from disk. Called before the first frame: no network,
    /// no awaiting the backend, so the window opens on real data.
    func hydrate() async {
        if let roster = await cache.load(.banks, bank: Self.rosterBank, as: BanksResponse.self) {
            banks.value = roster.value
            banks.etag = roster.etag
            banks.loadedAt = Date()
            if let active = roster.value.active, !active.isEmpty { bank = active }
        }
        var loaded: [String] = banks.value == nil ? [] : ["banks"]
        func take<T: Codable>(_ domain: SyncDomain, _ kp: ReferenceWritableKeyPath<Store, Snapshot<T>>) async {
            guard let hit = await cache.load(domain, bank: bank, as: T.self) else { return }
            self[keyPath: kp].value = hit.value
            self[keyPath: kp].etag = hit.etag
            self[keyPath: kp].loadedAt = Date()
            loaded.append(domain.rawValue)
        }
        await take(.graph, \.graph)
        await take(.inbox, \.inbox)
        await take(.sources, \.sources)
        await take(.feeds, \.feeds)
        await take(.calendars, \.calendars)
        await take(.contributors, \.contributors)
        await take(.origins, \.origins)
        await take(.connections, \.connections)
        await take(.status, \.status)
        if let s = status.value { pushStatus(s) }
        let summary = "hydrate bank=\(bank) loaded=[\(loaded.joined(separator: ","))]"
        Self.logger.notice("\(summary, privacy: .public)")
        FileHandle.standardError.write(Data("[cicada.sync] \(summary)\n".utf8))
    }

    // MARK: - Refresh

    func refreshAll() async {
        await refresh(Set(SyncDomain.allCases))
    }

    /// Conditionally refresh the given domains. `.banks` is handled first: if
    /// the active bank moved, we re-hydrate that bank from disk (instant swap)
    /// and then reconcile every domain against the network.
    func refresh(_ domains: Set<SyncDomain>) async {
        var remaining = domains
        if remaining.remove(.banks) != nil {
            let previous = bank
            await refreshOne(.banks, \.banks) { [api] etag in try await api.fetchBanks(etag: etag) }
            if let active = banks.value?.active, !active.isEmpty, active != previous {
                bank = active
                Self.logger.notice("bank switched \(previous, privacy: .public) → \(active, privacy: .public)")
                await hydrate()
                remaining = Set(SyncDomain.allCases).subtracting([.banks])
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
            }
        }
    }

    /// One domain: conditional GET → assign → persist. Never blanks a value.
    private func refreshOne<T: Codable>(
        _ domain: SyncDomain,
        _ kp: ReferenceWritableKeyPath<Store, Snapshot<T>>,
        fetch: (String?) async throws -> Conditional<T>
    ) async {
        self[keyPath: kp].isRefreshing = true
        do {
            let result = try await fetch(self[keyPath: kp].etag)
            defer { self[keyPath: kp].isRefreshing = false }
            guard !result.notModified, let value = result.value else { return }
            self[keyPath: kp].value = value
            self[keyPath: kp].etag = result.etag
            self[keyPath: kp].loadedAt = Date()
            await cache.save(value, etag: result.etag,
                             domain: domain, bank: domain == .banks ? Self.rosterBank : bank)
        } catch {
            let wasEmpty = self[keyPath: kp].isEmpty
            self[keyPath: kp].isRefreshing = false
            if wasEmpty { toast = "Couldn't load \(domain.rawValue)" }
            Self.logger.debug("refresh \(domain.rawValue, privacy: .public) failed: \(String(describing: error))")
        }
    }

    /// `/status` is small and volatile — plain GET, no etag.
    private func refreshStatus() async {
        status.isRefreshing = true
        do {
            let snapshot = try await api.fetchStatus()
            status.value = snapshot
            status.loadedAt = Date()
            status.isRefreshing = false
            await cache.save(snapshot, etag: nil, domain: .status, bank: bank)
            pushStatus(snapshot)
        } catch {
            let wasEmpty = status.isEmpty
            status.isRefreshing = false
            if wasEmpty { toast = "Couldn't load status" }
        }
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
        guard var snapshot = status.value else { return }
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

    // MARK: - Version diffing

    /// Apply a new version vector: refresh only the domains whose components
    /// moved. A `bank` component change fans out to everything (see
    /// `VersionVector.changedDomains`).
    func apply(version newVersion: VersionVector) async {
        let changed = newVersion.changedDomains(since: version)
        version = newVersion
        guard !changed.isEmpty else { return }
        await refresh(changed)
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
