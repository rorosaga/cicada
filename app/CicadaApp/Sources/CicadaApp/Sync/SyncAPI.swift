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
    func fetchRecentConversations(limit: Int) async throws -> [ConversationSummary]
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
    func setConnectionKey(_ id: String, key: String) async throws -> ConnectionStatus
    func removeConnectionKey(_ id: String) async throws -> ConnectionStatus
    func logoutConnection(_ id: String) async throws -> ConnectionStatus
    func subscribeFeed(url: String, tags: [String]) async throws -> FeedSubscription
    func unsubscribeFeed(url: String) async throws
    func subscribeCalendar(url: String, tags: [String]) async throws -> CalendarSubscription
    func unsubscribeCalendar(url: String) async throws
    func activateBank(name: String) async throws
    func triggerSleep() async throws -> SleepTriggerResponse

    /// `GET /sync/version` — the current version vector.
    func fetchSyncVersion() async throws -> VersionVector
    /// `GET /sync/events` — a long-lived SSE line stream (bearer attached).
    ///
    /// Lines are produced by `SSELineSplitter`, not `AsyncBytes.lines`: the
    /// latter drops empty lines, which are SSE's frame terminators.
    func syncEventLines() async throws -> (AsyncThrowingStream<String, any Error>, HTTPURLResponse)
}

/// The `event: sleep` payload pushed over `/sync/events`. Decode-tolerant so a
/// backend that adds or drops a field doesn't kill the stream.
struct SleepEventPayload: Codable, Equatable {
    var status: String
    var cycleId: String?
    var stage: Int
    var totalStages: Int
    var progress: Double?
    var error: String?

    enum CodingKeys: String, CodingKey { case status, cycleId, stage, totalStages, progress, error }

    init(status: String, cycleId: String? = nil, stage: Int = 0,
         totalStages: Int = 5, progress: Double? = nil, error: String? = nil) {
        self.status = status; self.cycleId = cycleId; self.stage = stage
        self.totalStages = totalStages; self.progress = progress; self.error = error
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = (try? c.decode(String.self, forKey: .status)) ?? "idle"
        cycleId = try? c.decodeIfPresent(String.self, forKey: .cycleId)
        stage = (try? c.decode(Int.self, forKey: .stage)) ?? 0
        totalStages = (try? c.decode(Int.self, forKey: .totalStages)) ?? 5
        progress = try? c.decodeIfPresent(Double.self, forKey: .progress)
        error = try? c.decodeIfPresent(String.self, forKey: .error)
    }
}
