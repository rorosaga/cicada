import Foundation

/// Result of a conditional (`If-None-Match`) GET.
///
/// `notModified == true` means the server answered 304 and `value` is nil —
/// callers MUST keep whatever they already had rather than blanking it. On a
/// 200, `value` is the fresh payload and `etag` the new validator to send next
/// time (nil when the endpoint doesn't emit one).
struct Conditional<T> {
    let value: T?
    let etag: String?
    let notModified: Bool

    /// Unwrap a wrapper response (`{"contributors": [...]}`) into its payload
    /// while preserving the etag/304 state.
    func map<U>(_ transform: (T) -> U) -> Conditional<U> {
        Conditional<U>(value: value.map(transform), etag: etag, notModified: notModified)
    }

    /// The answer to "this backend doesn't ship that endpoint" (a 404 on a
    /// conditional fetch).
    ///
    /// It must NOT be an empty payload: `Store.refreshOne` writes any non-nil
    /// value straight into the snapshot *and* persists it, so returning `[]`
    /// would blank a populated feed/sources/origins list on disk the moment one
    /// request 404s. Reported as a no-change instead, so the caller keeps
    /// whatever it already has — exactly like a 304.
    static func unavailable(etag: String?) -> Conditional<T> {
        Conditional<T>(value: nil, etag: etag, notModified: true)
    }
}

/// The slice of `APIClient` the `Store`/`SyncEngine` depend on. Exists so the
/// Store can be driven by a fake in tests — `APIClient` conforms via an
/// extension in `Services/APIClient.swift`.
///
/// Every domain gets one conditional fetch keyed by the caller's cached etag.
/// `.status` is deliberately unconditional: it is small, changes constantly,
/// and drives the menu-bar bookworm.
protocol SyncAPI: Sendable {
    func fetchGraph(etag: String?) async throws -> Conditional<GraphResponse>
    func fetchInbox(etag: String?) async throws -> Conditional<[InboxItem]>
    func fetchBanks(etag: String?) async throws -> Conditional<BanksResponse>
    func fetchSources(etag: String?) async throws -> Conditional<[MediaFeedItem]>
    func fetchChannels(etag: String?) async throws -> Conditional<[SourceChannel]>
    func fetchFeeds(etag: String?) async throws -> Conditional<[FeedSubscription]>
    func fetchCalendars(etag: String?) async throws -> Conditional<[CalendarSubscription]>
    func fetchContributors(etag: String?) async throws -> Conditional<[Contributor]>
    func fetchOrigins(etag: String?) async throws -> Conditional<[OriginStat]>
    /// G124 — `GET /sources/overview`, one row per memory source.
    func fetchSourcesOverview(etag: String?) async throws -> Conditional<[SourceOverview]>
    func fetchConnections(etag: String?) async throws -> Conditional<[ConnectionStatus]>
    /// Usage dashboard (G51) default view — fans out to all five
    /// `/consumption/*` endpoints and folds them into one bundle. See
    /// `ConsumptionBundle`.
    ///
    /// `current` is the caller's already-cached bundle (if any): `/connections`
    /// and `/harness` carry no ETag and are always refetched fresh, so a 304
    /// on `/summary`/`/calendar`/`/stats` must reuse `current`'s matching
    /// section rather than either an empty placeholder or discarding the
    /// whole response — see `fetchConsumption`'s doc comment in `APIClient`.
    func fetchConsumption(etag: String?, current: ConsumptionBundle?) async throws -> Conditional<ConsumptionBundle>

    func fetchStatus() async throws -> StatusSnapshot
    func fetchEntity(id: String) async throws -> Entity

    // G48 — on-demand, like `/contributors/commits`: no SyncDomain, no
    // SnapshotCache entry. On the protocol purely so tests can fake them.
    /// G124 R5: `harness`/`origin` filter server-side, BEFORE the cap — a
    /// client-side filter over a capped page would silently drop an older
    /// conversation of the selected harness. `harness: "unknown"` matches rows
    /// whose harness is empty.
    /// `query` (G136 R-SU22) is a title filter the backend applies before the same cap (G136 R17).
    func fetchRecentConversations(limit: Int, harness: String?, origin: String?, query: String?) async throws -> [ConversationSummary]
    /// Exact by-id lookup over the whole bank; `nil` = the bank has no episode
    /// carrying that id. NEVER resolve an id inside `fetchRecentConversations`'
    /// capped page — absence there means "not recent", not "not known".
    func fetchConversation(id: String) async throws -> ConversationSummary?
    func resumeConversation(id: String) async throws -> ResumeDescriptor

    // MARK: Writes (§5.4)
    //
    // Every mutation routed through `Store.perform` goes out through this
    // protocol rather than `APIClient.shared` directly, so a test can drive
    // the optimistic/rollback paths with a fake that throws on demand.
    // Signatures mirror `APIClient`'s existing methods (return values and
    // all) so `APIClient` conforms without wrapper indirection; the mutations
    // themselves ignore the returned bodies — the authoritative state arrives
    // with the follow-up refresh.

    func resolveInbox(id: String, action: String, answer: String?,
                      optionKey: String?, remindDays: Int?,
                      mergeTarget: String?, mergeSurvivor: String?) async throws
    func setConnectionTier(_ id: String, tier: String?) async throws -> ConnectionStatus
    /// G74(a) — make (or unmake) the Claude plan the Sleep engine.
    func setUseForSleep(_ id: String, on: Bool) async throws -> ConnectionStatus
    func setConnectionKey(_ id: String, key: String) async throws -> ConnectionStatus
    func removeConnectionKey(_ id: String) async throws -> ConnectionStatus
    func logoutConnection(_ id: String) async throws -> ConnectionStatus
    func subscribeFeed(url: String, tags: [String]) async throws -> FeedSubscription
    func unsubscribeFeed(url: String) async throws
    func subscribeCalendar(url: String, tags: [String]) async throws -> CalendarSubscription
    func unsubscribeCalendar(url: String) async throws
    /// R8 — browser syncs ride `Store.perform` too, so the panel gets the
    /// same failure toast + channel reconcile as every other write. Unlike
    /// the rest, the mutations DO keep the returned body: `{new, skipped}`
    /// is the honest result the panel shows.
    func syncSafariTabs(db: Data, wal: Data?, devices: [String]?) async throws -> SafariTabsSyncResult
    func syncBookmarks(chromeData: Data?, safariData: Data?, folders: [String]?) async throws -> BookmarkSyncResult
    /// Round 4 (C9) — one Chromium-family browser beyond Chrome, posted as `chromium: [{browser, dataB64}]`.
    func syncChromiumBookmarks(browser: String, data: Data) async throws -> BookmarkSyncResult
    func activateBank(name: String) async throws
    func triggerSleep() async throws -> SleepTriggerResponse
    /// Sleep page v5 — `POST /sleep/trigger {"continue": true}`: resume the paused run. Only the Sleep page's
    /// Continue sends it (`SleepViewModel.continueRun`, pinned by `SleepV5DoorsTests`). No default: a conformer that
    /// forgot it must not turn Continue into a fresh trigger, which clears the pause on the server.
    func continueSleepRun() async throws -> SleepTriggerResponse
    /// G141 PJ-5 (R-PP19) — the Projects page's five writes (`routers/projects.py`), each answering the claim it wrote,
    /// the day and how that day was decided. Every day sent is `YYYY-MM-DD`: nothing relative is sent as a value
    /// (R-PJ6). All answer 409 while a Sleep cycle runs.
    func addProjectMilestone(project: String, name: String, target: String?) async throws -> ProjectWriteResponse
    func changeProjectMilestone(project: String, slug: String, change: MilestoneChange) async throws -> ProjectWriteResponse
    func logProjectHappening(project: String, text: String, status: String, when: String?) async throws -> ProjectWriteResponse
    func settleProjectThread(project: String, claimId: String, status: String) async throws -> ProjectWriteResponse
    func withdrawProjectHappening(project: String, claimId: String) async throws -> ProjectWriteResponse
    /// C11 (G146) — the three picture writes (`routers/entities.py`): each answers the page's picture after it and the
    /// inputs the twin re-resolves from; each answers 409 while Sleep runs.
    func setEntityPicture(entityId: String, data: Data, ext: String) async throws -> EntityPictureAnswer
    func useEntityInitials(entityId: String) async throws -> EntityPictureAnswer
    func clearEntityPicture(entityId: String) async throws -> EntityPictureAnswer
    /// G61 S3-a — one edit to one of a page's sources, keyed by the entry's current `(ref, predicate)`; answers the
    /// page's sources after it (`POST /entities/{id}/sources/change`).
    func changeEntitySource(entityId: String, source: EntitySource, change: SourceChange) async throws -> [EntitySource]
    /// G61 — add a source to a page (`POST /entities/{id}/sources`); answers the page's sources after it (audit A06).
    func addEntitySource(entityId: String, ref: String, predicate: String?) async throws -> [EntitySource]
    /// G150 — the Backlog section's three writes (`routers/backlog.py`), each answering the item as it now stands. All
    /// answer 409 while a Sleep cycle runs, and an add whose idea is already open answers 409 naming the item.
    func addBacklogItem(project: String, title: String, description: String) async throws -> BacklogItem
    func addBacklogNote(project: String, item: String, note: String, status: String?) async throws -> BacklogItem
    func updateBacklogItem(project: String, item: String, change: BacklogChange) async throws -> BacklogItem

    /// `GET /sync/version` — the current version vector.
    func fetchSyncVersion() async throws -> VersionVector
    /// `GET /sync/events` — a long-lived SSE line stream (bearer attached).
    ///
    /// Lines are produced by `SSELineSplitter`, not `AsyncBytes.lines`: the
    /// latter drops empty lines, which are SSE's frame terminators.
    func syncEventLines() async throws -> (AsyncThrowingStream<String, any Error>, HTTPURLResponse)
}

/// The compact `drain` block on the `sleep` SSE event (`sleep_drain.to_sse`, G163): where a
/// person-started run is, in counts, and why it stopped — the reason only, never the sentence
/// (that is `GET /sleep/status`'s). Lenient like every field here.
struct SleepDrainSSE: Codable, Equatable {
    var batch: Int
    var batches: Int
    var filed: Int
    var frozen: Int
    var active: Bool
    var stop: String?
    // Sleep page v5 — `nil` on an older backend (never a fabricated 0).
    var calls: Int? = nil
    /// Read / failed in the running batch.
    var read: Int? = nil
    var failed: Int? = nil
    /// Sort's and Decide's finished counts in the running batch.
    var sort: Int? = nil
    var decide: Int? = nil
    var parked: Int? = nil
    /// Conversations that arrived since the run began — live while it reads.
    var arrived: Int? = nil

    init(batch: Int = 0, batches: Int = 0, filed: Int = 0, frozen: Int = 0, active: Bool = false, stop: String? = nil,
         calls: Int? = nil, read: Int? = nil, failed: Int? = nil, sort: Int? = nil, decide: Int? = nil,
         parked: Int? = nil, arrived: Int? = nil) {
        self.batch = batch; self.batches = batches; self.filed = filed; self.frozen = frozen
        self.active = active; self.stop = stop
        self.calls = calls; self.read = read; self.failed = failed; self.sort = sort; self.decide = decide
        self.parked = parked; self.arrived = arrived
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func int(_ key: CodingKeys) -> Int { (try? c.decodeIfPresent(Int.self, forKey: key)) ?? 0 }
        func opt(_ key: CodingKeys) -> Int? { (try? c.decodeIfPresent(Int.self, forKey: key)) ?? nil }
        batch = int(.batch); batches = int(.batches); filed = int(.filed); frozen = int(.frozen)
        active = (try? c.decodeIfPresent(Bool.self, forKey: .active)) ?? false
        stop = try? c.decodeIfPresent(String.self, forKey: .stop)
        calls = opt(.calls); read = opt(.read); failed = opt(.failed); sort = opt(.sort); decide = opt(.decide)
        parked = opt(.parked); arrived = opt(.arrived)
    }

    enum CodingKeys: String, CodingKey {
        case batch, batches, filed, frozen, active, stop, calls, read, failed, sort, decide, parked, arrived
    }
}

/// The `event: sleep` payload pushed over `/sync/events`. Decode-tolerant so a
/// backend that adds or drops a field doesn't kill the stream.
///
/// G106 amendment: also carries the Sleep debt block + live progress —
/// Rested % and Progress % are both "SSE-driven, continuous" per that spec,
/// so the Sleep page's mood/rested/progress readout can update every tick
/// without running its own separate poll loop while idle. All seven new
/// fields are optional and `nil`-tolerant on decode, same posture as every
/// existing field here; `SleepViewModel`/the Sleep page fall back to the
/// REST-polled `SleepStatusResponse.debt`/`.progressPct` whenever a field
/// here is `nil` (see `resolveSleepDebt`/`resolveProgressPct` in SleepMood.swift).
struct SleepEventPayload: Codable, Equatable {
    var status: String
    var cycleId: String?
    var stage: Int
    var totalStages: Int
    /// The backend has always sent `state.progress`, the stage SENTENCE
    /// ("Stage 1/5: Extracting entities from 12 episodes…" —
    /// `sleep_cycle.py` -> `sync.py`), but this field was typed `Double?` and
    /// decoded with `try?`, so it silently decoded to `nil` on every event
    /// since it shipped. Typed to match the wire; the `try?` stays so an older
    /// backend sending a number degrades to `nil` rather than dropping the
    /// whole event.
    var progress: String?
    var error: String?
    var progressPct: Int?
    var restedPct: Int?
    var volumePct: Int?
    var agePct: Int?
    var unprocessedCount: Int?
    var hasRunBefore: Bool?
    var hoursSinceLastCycle: Double?
    /// G125 R3 — this cycle's selected episodes by source, and how many of
    /// each Stage 1 has finished. `nil` (never a fabricated `[:]`) on an
    /// older backend that predates these keys; `SleepViewModel`/the Sleep
    /// page fall back to the REST-polled `SleepStatusResponse` fields.
    var queueByOrigin: [String: Int]?
    var readByOrigin: [String: Int]?
    /// G163 — a person-started run's compact progress (`sleep_drain.to_sse`): counts, a flag and the
    /// stop's reason only. `nil` on a scheduled cycle and on an older backend.
    var drain: SleepDrainSSE?
    /// Sleep page v5 — parked conversations and what a run would read now; `nil` on an older backend.
    var parkedCount: Int? = nil
    var readableCount: Int? = nil
    /// The paused run in brief. `pausedKnown` says the backend sent the key at all, so a `nil` `paused` from a
    /// current backend means "no paused run" while an older one's means "unknown" (the REST status then decides).
    var paused: SleepPausedSSE? = nil
    var pausedKnown: Bool = false

    enum CodingKeys: String, CodingKey {
        case status, cycleId, stage, totalStages, progress, error
        case progressPct, restedPct, volumePct, agePct
        case unprocessedCount, hasRunBefore, hoursSinceLastCycle
        case queueByOrigin, readByOrigin, drain
        case parkedCount, readableCount, paused
    }

    init(status: String, cycleId: String? = nil, stage: Int = 0,
         totalStages: Int = 5, progress: String? = nil, error: String? = nil,
         progressPct: Int? = nil, restedPct: Int? = nil, volumePct: Int? = nil,
         agePct: Int? = nil, unprocessedCount: Int? = nil, hasRunBefore: Bool? = nil,
         hoursSinceLastCycle: Double? = nil, queueByOrigin: [String: Int]? = nil,
         readByOrigin: [String: Int]? = nil, drain: SleepDrainSSE? = nil) {
        self.drain = drain
        self.status = status; self.cycleId = cycleId; self.stage = stage
        self.totalStages = totalStages; self.progress = progress; self.error = error
        self.progressPct = progressPct; self.restedPct = restedPct; self.volumePct = volumePct
        self.agePct = agePct; self.unprocessedCount = unprocessedCount
        self.hasRunBefore = hasRunBefore; self.hoursSinceLastCycle = hoursSinceLastCycle
        self.queueByOrigin = queueByOrigin; self.readByOrigin = readByOrigin
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = (try? c.decode(String.self, forKey: .status)) ?? "idle"
        cycleId = try? c.decodeIfPresent(String.self, forKey: .cycleId)
        stage = (try? c.decode(Int.self, forKey: .stage)) ?? 0
        totalStages = (try? c.decode(Int.self, forKey: .totalStages)) ?? 5
        progress = try? c.decodeIfPresent(String.self, forKey: .progress)
        error = try? c.decodeIfPresent(String.self, forKey: .error)
        progressPct = try? c.decodeIfPresent(Int.self, forKey: .progressPct)
        restedPct = try? c.decodeIfPresent(Int.self, forKey: .restedPct)
        volumePct = try? c.decodeIfPresent(Int.self, forKey: .volumePct)
        agePct = try? c.decodeIfPresent(Int.self, forKey: .agePct)
        unprocessedCount = try? c.decodeIfPresent(Int.self, forKey: .unprocessedCount)
        hasRunBefore = try? c.decodeIfPresent(Bool.self, forKey: .hasRunBefore)
        hoursSinceLastCycle = try? c.decodeIfPresent(Double.self, forKey: .hoursSinceLastCycle)
        queueByOrigin = try? c.decodeIfPresent([String: Int].self, forKey: .queueByOrigin)
        readByOrigin = try? c.decodeIfPresent([String: Int].self, forKey: .readByOrigin)
        drain = try? c.decodeIfPresent(SleepDrainSSE.self, forKey: .drain)
        parkedCount = (try? c.decodeIfPresent(Int.self, forKey: .parkedCount)) ?? nil
        readableCount = (try? c.decodeIfPresent(Int.self, forKey: .readableCount)) ?? nil
        pausedKnown = c.contains(.paused)
        paused = (try? c.decodeIfPresent(SleepPausedSSE.self, forKey: .paused)) ?? nil
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(status, forKey: .status)
        try c.encodeIfPresent(cycleId, forKey: .cycleId)
        try c.encode(stage, forKey: .stage)
        try c.encode(totalStages, forKey: .totalStages)
        try c.encodeIfPresent(progress, forKey: .progress)
        try c.encodeIfPresent(error, forKey: .error)
        try c.encodeIfPresent(progressPct, forKey: .progressPct)
        try c.encodeIfPresent(restedPct, forKey: .restedPct)
        try c.encodeIfPresent(volumePct, forKey: .volumePct)
        try c.encodeIfPresent(agePct, forKey: .agePct)
        try c.encodeIfPresent(unprocessedCount, forKey: .unprocessedCount)
        try c.encodeIfPresent(hasRunBefore, forKey: .hasRunBefore)
        try c.encodeIfPresent(hoursSinceLastCycle, forKey: .hoursSinceLastCycle)
        try c.encodeIfPresent(queueByOrigin, forKey: .queueByOrigin)
        try c.encodeIfPresent(readByOrigin, forKey: .readByOrigin)
        try c.encodeIfPresent(drain, forKey: .drain)
        try c.encodeIfPresent(parkedCount, forKey: .parkedCount)
        try c.encodeIfPresent(readableCount, forKey: .readableCount)
        if pausedKnown { try c.encode(paused, forKey: .paused) }
    }
}

