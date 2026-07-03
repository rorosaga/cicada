import Foundation

struct UploadResponse: Codable {
    let status: String
    let episodesCreated: Int
    /// Threads that already existed but grew/changed since last import and were
    /// re-staged in place (G20 delta re-import). Absent on legacy backends → 0.
    let episodesUpdated: Int
    let duplicatesSkipped: Int
    let message: String
    let source: String

    enum CodingKeys: String, CodingKey {
        case status, episodesCreated, episodesUpdated, duplicatesSkipped, message, source
    }

    init(
        status: String,
        episodesCreated: Int,
        episodesUpdated: Int = 0,
        duplicatesSkipped: Int,
        message: String,
        source: String
    ) {
        self.status = status
        self.episodesCreated = episodesCreated
        self.episodesUpdated = episodesUpdated
        self.duplicatesSkipped = duplicatesSkipped
        self.message = message
        self.source = source
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = (try? c.decode(String.self, forKey: .status)) ?? "ok"
        episodesCreated = (try? c.decode(Int.self, forKey: .episodesCreated)) ?? 0
        episodesUpdated = (try? c.decode(Int.self, forKey: .episodesUpdated)) ?? 0
        duplicatesSkipped = (try? c.decode(Int.self, forKey: .duplicatesSkipped)) ?? 0
        message = (try? c.decode(String.self, forKey: .message)) ?? ""
        source = (try? c.decode(String.self, forKey: .source)) ?? ""
    }
}

// MARK: - Memory banks (M6/M7)

/// One memory bank from `GET /banks`. Decode-tolerant — a legacy backend that
/// omits the count/date fields still decodes (they default to 0 / "").
struct MemoryBank: Codable, Identifiable {
    let name: String
    let active: Bool
    let entityCount: Int
    let episodeCount: Int
    let createdAt: String
    let description: String?

    var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name, active, entityCount, episodeCount, createdAt, description
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        active = (try? c.decode(Bool.self, forKey: .active)) ?? false
        entityCount = (try? c.decode(Int.self, forKey: .entityCount)) ?? 0
        episodeCount = (try? c.decode(Int.self, forKey: .episodeCount)) ?? 0
        createdAt = (try? c.decode(String.self, forKey: .createdAt)) ?? ""
        description = try c.decodeIfPresent(String.self, forKey: .description)
    }
}

struct BanksResponse: Codable {
    let banks: [MemoryBank]
    let active: String?

    enum CodingKeys: String, CodingKey { case banks, active }

    init(banks: [MemoryBank], active: String?) {
        self.banks = banks
        // The backend's `active` defaults to "" (never null) when nothing is
        // active; normalize that to nil so callers can treat "no active bank"
        // uniformly and don't try to activate/duplicate the empty string.
        self.active = (active?.isEmpty == true) ? nil : active
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        banks = (try? c.decode([MemoryBank].self, forKey: .banks)) ?? []
        let rawActive = try c.decodeIfPresent(String.self, forKey: .active)
        active = (rawActive?.isEmpty == true) ? nil : rawActive
    }
}

/// Mirror of the backend's `sanitize_id` (`api/services/id_utils.py`): banks are
/// keyed on disk by this slug, and `POST /banks/{name}/import` looks the bank up
/// by the *exact* slug — it does NOT re-sanitize. So a name like "My Project" is
/// created as `my-project`, and the import call must target `my-project`, not the
/// raw typed string, or it 404s. Lowercases, replaces filesystem-unsafe chars and
/// whitespace with hyphens, collapses runs, trims, falls back to "unnamed".
func sanitizeBankSlug(_ name: String) -> String {
    var s = name.lowercased()
    // Filesystem-unsafe characters: / \ : * ? " < > | .
    let unsafe = CharacterSet(charactersIn: "/\\:*?\"<>|.")
    s = String(s.unicodeScalars.map { unsafe.contains($0) ? "-" : Character($0) })
    s = s.replacingOccurrences(of: " ", with: "-")
    // Collapse runs of hyphens.
    while s.contains("--") { s = s.replacingOccurrences(of: "--", with: "-") }
    s = s.trimmingCharacters(in: CharacterSet(charactersIn: "-"))
    return s.isEmpty ? "unnamed" : s
}

/// `POST /banks/{name}/import` result. The date range may be absent (empty
/// import), so both ends are optional.
struct BankImportResponse: Codable {
    let episodesStaged: Int
    /// Existing threads re-staged in place after they grew/changed (G20 delta
    /// re-import). Absent on legacy backends → 0.
    let episodesUpdated: Int
    let duplicatesSkipped: Int
    let format: String?
    let dateRange: BankImportDateRange?

    enum CodingKeys: String, CodingKey {
        case episodesStaged, episodesUpdated, duplicatesSkipped, format, dateRange
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episodesStaged = (try? c.decode(Int.self, forKey: .episodesStaged)) ?? 0
        episodesUpdated = (try? c.decode(Int.self, forKey: .episodesUpdated)) ?? 0
        duplicatesSkipped = (try? c.decode(Int.self, forKey: .duplicatesSkipped)) ?? 0
        format = try c.decodeIfPresent(String.self, forKey: .format)
        dateRange = try c.decodeIfPresent(BankImportDateRange.self, forKey: .dateRange)
    }
}

struct BankImportDateRange: Codable {
    let from: String?
    let to: String?

    enum CodingKeys: String, CodingKey { case from, to }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        from = try c.decodeIfPresent(String.self, forKey: .from)
        to = try c.decodeIfPresent(String.self, forKey: .to)
    }
}

// MARK: - Media feed (sources)

/// One saved media item from `GET /sources` (camelCase decodes 1:1).
struct MediaFeedItem: Codable, Identifiable {
    let mediaEntityId: String
    let url: String
    let title: String
    let mediaType: String
    let site: String?
    let channel: String?
    let thumbnail: String?
    let savedAt: String
    let tags: [String]
    let status: String
    let relatedCount: Int
    let relevance: Double
    let personalRelevance: String?

    var id: String { mediaEntityId }

    enum CodingKeys: String, CodingKey {
        case mediaEntityId, url, title, mediaType, site, channel, thumbnail
        case savedAt, tags, status, relatedCount, relevance, personalRelevance
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        mediaEntityId = try c.decode(String.self, forKey: .mediaEntityId)
        url = try c.decode(String.self, forKey: .url)
        title = try c.decode(String.self, forKey: .title)
        mediaType = try c.decode(String.self, forKey: .mediaType)
        site = try c.decodeIfPresent(String.self, forKey: .site)
        channel = try c.decodeIfPresent(String.self, forKey: .channel)
        thumbnail = try c.decodeIfPresent(String.self, forKey: .thumbnail)
        savedAt = (try? c.decode(String.self, forKey: .savedAt)) ?? ""
        tags = (try? c.decode([String].self, forKey: .tags)) ?? []
        status = (try? c.decode(String.self, forKey: .status)) ?? "active"
        relatedCount = (try? c.decode(Int.self, forKey: .relatedCount)) ?? 0
        relevance = (try? c.decode(Double.self, forKey: .relevance)) ?? 0
        personalRelevance = try c.decodeIfPresent(String.self, forKey: .personalRelevance)
    }
}

struct SourceListResponse: Codable {
    let items: [MediaFeedItem]
    let total: Int
}

/// `POST /sources/save` full result — richer than the `saveSource(url:)`
/// throws-only helper. Used by the Capture page's "Paste URL" tile so it can
/// surface the resolved title/dedup status, not just success/failure.
struct SourceSaveResult: Codable {
    let status: String
    let mediaEntityId: String
    let episodeId: String
    let title: String
    let mediaType: String
    let thumbnail: String?
    let message: String
}

/// One source's tally from `POST /sources/sync-bookmarks` (`origin` is
/// "chrome" or "safari").
struct BookmarkSyncSourceSummary: Codable {
    let origin: String
    let found: Int
    let new: Int
    let skipped: Int
}

/// `POST /sources/sync-bookmarks` result — aggregate new/skipped plus the
/// per-browser breakdown.
struct BookmarkSyncResult: Codable {
    let new: Int
    let skipped: Int
    let sources: [BookmarkSyncSourceSummary]
}

struct SleepStatusResponse: Codable {
    let status: String
    let cycleId: String?
    let startedAt: String?
    let progress: String?
    let error: String?
    let indexWarning: String?
    let stage: Int
    let totalStages: Int
    let episodesTotal: Int
    let entitiesCreated: Int
    let entitiesUpdated: Int
    let relationshipsCreated: Int
    let skillsDetected: Int

    enum CodingKeys: String, CodingKey {
        case status, cycleId, startedAt, progress, error, indexWarning, stage, totalStages
        case episodesTotal, entitiesCreated, entitiesUpdated
        case relationshipsCreated, skillsDetected
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = try c.decode(String.self, forKey: .status)
        cycleId = try c.decodeIfPresent(String.self, forKey: .cycleId)
        startedAt = try c.decodeIfPresent(String.self, forKey: .startedAt)
        progress = try c.decodeIfPresent(String.self, forKey: .progress)
        error = try c.decodeIfPresent(String.self, forKey: .error)
        indexWarning = try c.decodeIfPresent(String.self, forKey: .indexWarning)
        stage = try c.decodeIfPresent(Int.self, forKey: .stage) ?? 0
        totalStages = try c.decodeIfPresent(Int.self, forKey: .totalStages) ?? 5
        episodesTotal = try c.decodeIfPresent(Int.self, forKey: .episodesTotal) ?? 0
        entitiesCreated = try c.decodeIfPresent(Int.self, forKey: .entitiesCreated) ?? 0
        entitiesUpdated = try c.decodeIfPresent(Int.self, forKey: .entitiesUpdated) ?? 0
        relationshipsCreated = try c.decodeIfPresent(Int.self, forKey: .relationshipsCreated) ?? 0
        skillsDetected = try c.decodeIfPresent(Int.self, forKey: .skillsDetected) ?? 0
    }
}

struct SleepTriggerResponse: Codable {
    let status: String
    let message: String
    let cycleId: String?
}

struct EpisodeQueueItem: Codable, Identifiable {
    let id: String
    let timestamp: String
    let source: String
    let title: String?
    let preview: String
    let processed: Bool
}

struct ScheduleConfig: Codable, Equatable {
    var enabled: Bool
    var hour: Int
    var minute: Int
}

/// Minimal mirror of the API's `SleepHistoryEntry` (camelCase on the wire). Only
/// `date` is consumed by the status compose fallback; the rest are decoded for
/// completeness so a future caller can reuse the model.
struct SleepHistoryEntry: Codable {
    let commitHash: String
    let date: String
    let message: String
    let filesChanged: [String]
}

enum APIError: Error, LocalizedError {
    case serverUnreachable
    case httpError(Int, String)
    case decodingError(String)

    var errorDescription: String? {
        switch self {
        case .serverUnreachable:
            "Cannot reach Cicada backend"
        case .httpError(let code, let msg):
            "HTTP \(code): \(msg)"
        case .decodingError(let msg):
            "Decoding error: \(msg)"
        }
    }
}

actor APIClient {
    static let shared = APIClient()

    private let baseURL = "http://127.0.0.1:8000"
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        return d
    }()

    // MARK: - Graph

    func fetchGraph() async throws -> GraphResponse {
        return try await get("/graph")
    }

    // MARK: - Memory banks (M6/M7)

    /// Bank names are user-supplied slugs; percent-encode as a path component
    /// in case a name carries a space or stray character.
    private func encodedBank(_ name: String) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "#$&+,/:;=?@")
        return name.addingPercentEncoding(withAllowedCharacters: allowed) ?? name
    }

    /// `GET /banks` → all banks plus the active one. Returns an empty roster on
    /// a 404 so the dropdown degrades gracefully on a pre-M6 backend.
    func fetchBanks() async throws -> BanksResponse {
        do {
            return try await get("/banks")
        } catch APIError.httpError(404, _) {
            return BanksResponse(banks: [], active: nil)
        }
    }

    /// `POST /banks` `{name, description?}` → create a NEW EMPTY bank. Returns
    /// the on-disk **slug** the backend keyed the bank under (e.g. "My Project"
    /// → "my-project"), which is what `activate`/`import` must target. The
    /// backend echoes the full roster (`BankListResponse`); we prefer the
    /// matching slug found in that roster, falling back to the locally-mirrored
    /// `sanitizeBankSlug` if the roster decode is unusable.
    @discardableResult
    func createBank(name: String, description: String? = nil) async throws -> String {
        var body: [String: Any] = ["name": name]
        if let description, !description.isEmpty { body["description"] = description }
        let expectedSlug = sanitizeBankSlug(name)
        // The backend echoes the full roster; decode it (and ignore the value).
        // The just-created bank is keyed under `sanitizeBankSlug(name)`, which
        // deterministically matches the backend's `sanitize_id`, so that slug is
        // authoritative whether or not the roster decode is usable.
        let resp: BanksResponse = try await post("/banks", body: body)
        if let landed = resp.banks.first(where: { $0.name == expectedSlug })?.name {
            return landed
        }
        return expectedSlug
    }

    /// `POST /banks/{name}/activate` → switch the active bank.
    func activateBank(name: String) async throws {
        try await post("/banks/\(encodedBank(name))/activate")
    }

    /// `POST /banks/{name}/duplicate` `{newName}` → "save current under a name".
    @discardableResult
    func duplicateBank(name: String, newName: String) async throws -> Data {
        return try await post("/banks/\(encodedBank(name))/duplicate", body: ["newName": newName])
    }

    /// `POST /banks/{name}/rename` `{newName}` → rename a bank in place (moves
    /// `banks/<old>`, rekeys `banks.yaml`, repoints `active` if it was active).
    /// Returns the on-disk **slug** the bank was rekeyed under (the backend
    /// slugifies `newName` the same way create/duplicate do), captured from the
    /// echoed roster so callers can re-target a subsequent activate/import. Falls
    /// back to the locally-mirrored `sanitizeBankSlug` when the roster decode is
    /// unusable.
    @discardableResult
    func renameBank(name: String, newName: String) async throws -> String {
        let expectedSlug = sanitizeBankSlug(newName)
        let resp: BanksResponse = try await post(
            "/banks/\(encodedBank(name))/rename", body: ["newName": newName]
        )
        if let landed = resp.banks.first(where: { $0.name == expectedSlug })?.name {
            return landed
        }
        return expectedSlug
    }

    /// `POST /banks/{name}/import` (multipart file) → stage parsed conversations
    /// into bank `name` as dated episodes. Format is auto-detected server-side.
    func importToBank(name: String, fileURL: URL) async throws -> BankImportResponse {
        let url = URL(string: "\(baseURL)/banks/\(encodedBank(name))/import")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"

        let boundary = UUID().uuidString
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        let fileData = try Data(contentsOf: fileURL)
        let filename = fileURL.lastPathComponent

        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: application/octet-stream\r\n\r\n".data(using: .utf8)!)
        body.append(fileData)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }
        do {
            return try decoder.decode(BankImportResponse.self, from: data)
        } catch {
            throw APIError.decodingError("\(error)")
        }
    }

    // MARK: - Entities

    /// Legacy entity ids can contain `#`, `$`, parens, etc. — `#` silently
    /// truncates the URL into a fragment and other characters nil out
    /// `URL(string:)`, so the id must be percent-encoded as a path component.
    private func encodedID(_ id: String) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "#$&+,/:;=?@")
        return id.addingPercentEncoding(withAllowedCharacters: allowed) ?? id
    }

    func fetchEntity(id: String) async throws -> Entity {
        return try await get("/entities/\(encodedID(id))")
    }

    func fetchEntityHistory(id: String, includeDiff: Bool = false) async throws -> [EntityHistoryEntry] {
        // FastAPI query params use the snake_case Python name (not the
        // camelCase body/response alias), so this is include_diff, not includeDiff.
        let suffix = includeDiff ? "?include_diff=true" : ""
        return try await get("/entities/\(encodedID(id))/history\(suffix)")
    }

    /// Per-commit add/remove diff for one entity file (backlog A1). NOT BUILD-VERIFIED.
    /// The backend validates commitHash against ^[0-9a-fA-F]{7,40}$ and rejects
    /// anything else, but we still percent-encode it (like the id) for consistency
    /// and defense-in-depth against a malformed value in the path.
    func fetchEntityCommitDiff(id: String, commitHash: String) async throws -> EntityDiff {
        return try await get("/entities/\(encodedID(id))/history/\(encodedID(commitHash))/diff")
    }

    /// `GET /entities/{id}/location` (issue #7) — the directory a location
    /// entity declares in its frontmatter, plus a bounded listing of immediate
    /// children. Returns `nil` on a 404 (endpoint not shipped yet) or any other
    /// error so the detail card degrades quietly to just the description. The
    /// backend reads ONLY the entity's own declared path — never a request path.
    func fetchLocationListing(id: String) async throws -> LocationListing? {
        do {
            return try await get("/entities/\(encodedID(id))/location")
        } catch APIError.httpError(404, _) {
            return nil
        }
    }

    // MARK: - Claims (CPCG claim layer)

    /// `GET /entities/{id}/claims` — the subject's claims. By default only
    /// currently-valid claims; `includeSuperseded` lifts the filter. Returns
    /// `[]` on a 404 so the perspective tab / claim chips degrade gracefully
    /// against a backend that hasn't shipped the endpoint yet.
    func fetchClaims(subject: String, includeSuperseded: Bool = false) async throws -> [Claim] {
        let q = includeSuperseded ? "?include_superseded=true" : ""
        do {
            let r: ClaimListResponse = try await get("/entities/\(encodedID(subject))/claims\(q)")
            return r.claims
        } catch APIError.httpError(404, _) {
            return []
        }
    }

    /// `GET /entities/{id}/timeline?predicate=&context=` — one
    /// `(subject, predicate, context)` key's bi-temporal supersede chain,
    /// newest first, including superseded claims. The FastAPI query params use
    /// the snake_case Python names; `predicate`/`context` here happen to match.
    func fetchClaimTimeline(subject: String, predicate: String, context: String) async throws -> ClaimTimeline {
        let p = predicate.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? predicate
        let c = context.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? context
        return try await get("/entities/\(encodedID(subject))/timeline?predicate=\(p)&context=\(c)")
    }

    /// `GET /transclude?ref=<urlencoded>` — resolve one `![[…]]` embed.
    /// Returns an unresolved soft-stub payload on a 404 so the embed renders a
    /// "missing embed" stub rather than throwing up the whole card.
    func resolveTransclusion(_ ref: String) async throws -> TransclusionPayload {
        let r = ref.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ref
        do {
            return try await get("/transclude?ref=\(r)")
        } catch APIError.httpError(404, _) {
            return TransclusionPayload(
                kind: "entity", ref: ref, title: ref, summary: "", claims: [], resolved: false
            )
        }
    }

    // MARK: - Contributors

    /// Repo-wide model/user attribution (backlog A2). NOT BUILD-VERIFIED.
    func fetchContributors() async throws -> [Contributor] {
        let resp: ContributorsResponse = try await get("/contributors")
        return resp.contributors
    }

    // MARK: - Inbox

    /// Fetch the unified inbox (`GET /inbox`). Optionally filter by kinds —
    /// comma-separated on the wire.
    func fetchInbox(kinds: [InboxKind]? = nil) async throws -> [InboxItem] {
        if let kinds, !kinds.isEmpty {
            let q = kinds.map(\.rawValue).joined(separator: ",")
            return try await get("/inbox?kind=\(q)")
        }
        return try await get("/inbox")
    }

    /// Resolve an inbox item. Dispatches server-side on the item's `kind`. The
    /// freetext clarification path sends `{action:"answer", answer:text}` — the
    /// resolution body shape from `api/routers/inbox.py`.
    /// `mergeSurvivor` (issue #1) names the id the user wants to KEEP as the
    /// canonical entity. When omitted the backend defaults to the legacy
    /// behavior (survivor = `mergeTarget`, the existing entity), so existing
    /// callers are unaffected.
    func resolveInboxItem(
        id: String,
        action: String,
        answer: String? = nil,
        mergeTarget: String? = nil,
        mergeSurvivor: String? = nil
    ) async throws {
        var body: [String: Any] = ["action": action]
        if let answer { body["answer"] = answer }
        if let mergeTarget { body["mergeTarget"] = mergeTarget }
        if let mergeSurvivor { body["mergeSurvivor"] = mergeSurvivor }
        try await post("/inbox/\(id)/resolve", body: body)
    }

    // MARK: - Status (menu-bar tamagotchi)

    /// Fetch the aggregate status snapshot (`GET /status`). The endpoint is live
    /// (wave 1); a `StatusSnapshot` decodes straight from the nested
    /// sleep/inbox/episodes wire shape.
    func fetchStatus() async throws -> StatusSnapshot {
        return try await get("/status")
    }

    // MARK: - Sources (media / bookmark ingestion — ships in a later wave)

    /// Post a single URL to the sources ingest endpoint. A 404 means the wave-3
    /// endpoint isn't merged yet; callers surface a friendly "coming soon".
    func saveSource(url: String) async throws {
        try await post("/sources/save", body: ["url": url])
    }

    /// Upload a single source file (bookmarks HTML/JSON, Takeout) to
    /// `POST /sources/upload`. Multipart, same envelope as conversation upload.
    func uploadSource(fileURL: URL) async throws -> UploadResponse {
        return try await uploadMultipart(path: "/sources/upload", fileURL: fileURL)
    }

    /// Fetch the saved-media feed (`GET /sources`). `sort` is `relevance` (the
    /// §3.4 metric) or `recent` (newest-first). Returns `[]` on a 404 so the
    /// feed view degrades gracefully on an older backend.
    func fetchSources(sort: String = "relevance") async throws -> [MediaFeedItem] {
        do {
            let resp: SourceListResponse = try await get("/sources?sort=\(sort)")
            return resp.items
        } catch APIError.httpError(404, _) {
            return []
        }
    }

    /// Ingest an RSS/Atom feed by pasted XML (`POST /sources/rss`).
    @discardableResult
    func ingestRSS(feedXml: String, tags: [String] = []) async throws -> UploadResponse {
        return try await post("/sources/rss", body: ["feedXml": feedXml, "tags": tags])
    }

    /// Ingest an RSS/Atom feed by URL (`POST /sources/rss`, the `feedUrl`
    /// variant). Live network fetch is off by default server-side
    /// (`CICADA_ALLOW_FEED_FETCH`), so a fresh install throws a 422 the caller
    /// should surface as a friendly "disabled" message rather than swallow.
    @discardableResult
    func ingestRSS(feedUrl: String, tags: [String] = []) async throws -> UploadResponse {
        return try await post("/sources/rss", body: ["feedUrl": feedUrl, "tags": tags])
    }

    /// Save a single URL with an optional note, returning the full save
    /// result (title, thumbnail, dedup status) — richer than `saveSource(url:)`
    /// above, which only throws on failure. Used by the Capture page's
    /// "Paste URL" import tile.
    @discardableResult
    func saveURL(_ url: String, note: String? = nil) async throws -> SourceSaveResult {
        var body: [String: Any] = ["url": url]
        if let note, !note.isEmpty { body["note"] = note }
        return try await post("/sources/save", body: body)
    }

    /// Keyless bookmark sync (`POST /sources/sync-bookmarks`). Called with no
    /// arguments, it reads the real local Chrome/Safari bookmark files
    /// (`bookmark_sync.sync_from_local_files`) — the Capture page's
    /// "Sync bookmarks now" action. Passing base64 data instead syncs against
    /// that inline payload (a future file-picker flow / what the backend tests
    /// use). The dedup diff is the same `url_index.json` hash check every
    /// other source path uses, so already-saved bookmarks come back as
    /// `skipped`, not re-ingested.
    @discardableResult
    func syncBookmarks(chromeData: Data? = nil, safariData: Data? = nil) async throws -> BookmarkSyncResult {
        var body: [String: Any] = [:]
        if let chromeData { body["chromeDataB64"] = chromeData.base64EncodedString() }
        if let safariData { body["safariDataB64"] = safariData.base64EncodedString() }
        return try await post("/sources/sync-bookmarks", body: body.isEmpty ? nil : body)
    }

    /// Shared multipart POST for file ingestion endpoints. Mirrors `uploadFile`
    /// but takes the target path so both `/conversations/upload` and
    /// `/sources/upload` reuse it.
    private func uploadMultipart(path: String, fileURL: URL) async throws -> UploadResponse {
        let url = URL(string: "\(baseURL)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"

        let boundary = UUID().uuidString
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        let fileData = try Data(contentsOf: fileURL)
        let filename = fileURL.lastPathComponent

        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: application/octet-stream\r\n\r\n".data(using: .utf8)!)
        body.append(fileData)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }
        return try decoder.decode(UploadResponse.self, from: data)
    }

    /// Convenience: upload several source files, aggregating the counts.
    func uploadSources(fileURLs: [URL]) async throws -> UploadResponse {
        var created = 0, updated = 0, skipped = 0
        var lastMessage = ""
        var source = "sources"
        for url in fileURLs {
            let r = try await uploadSource(fileURL: url)
            created += r.episodesCreated
            updated += r.episodesUpdated
            skipped += r.duplicatesSkipped
            lastMessage = r.message
            source = r.source
        }
        return UploadResponse(
            status: "ok",
            episodesCreated: created,
            episodesUpdated: updated,
            duplicatesSkipped: skipped,
            message: lastMessage,
            source: source
        )
    }

    // MARK: - Search (graph toolbar)

    /// Search entities for the graph toolbar (`GET /search`). Returns `[]` on a
    /// 404 so the caller can fall back to a local substring match before the
    /// LEANN endpoint lands.
    func search(q: String, topK: Int = 8) async throws -> [GraphSearchHit] {
        let encoded = q.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? q
        let resp: GraphSearchResponse = try await get("/search?q=\(encoded)&top_k=\(topK)&indexes=entities")
        return resp.results
    }

    // MARK: - Sleep

    func fetchSleepStatus() async throws -> SleepStatusResponse {
        return try await get("/sleep/status")
    }

    func triggerSleep() async throws -> SleepTriggerResponse {
        return try await post("/sleep/trigger")
    }

    func fetchEpisodeQueue() async throws -> [EpisodeQueueItem] {
        return try await get("/sleep/episodes")
    }

    func fetchSchedule() async throws -> ScheduleConfig {
        return try await get("/sleep/schedule")
    }

    func updateSchedule(_ cfg: ScheduleConfig) async throws -> ScheduleConfig {
        return try await put("/sleep/schedule", body: [
            "enabled": cfg.enabled,
            "hour": cfg.hour,
            "minute": cfg.minute,
        ])
    }

    // MARK: - Upload

    func uploadFile(fileURL: URL) async throws -> UploadResponse {
        let url = URL(string: "\(baseURL)/conversations/upload")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"

        let boundary = UUID().uuidString
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        let fileData = try Data(contentsOf: fileURL)
        let filename = fileURL.lastPathComponent

        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: application/octet-stream\r\n\r\n".data(using: .utf8)!)
        body.append(fileData)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

        request.httpBody = body

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }

        return try decoder.decode(UploadResponse.self, from: data)
    }

    // MARK: - Generic Helpers

    private func get<T: Decodable>(_ path: String) async throws -> T {
        let url = URL(string: "\(baseURL)\(path)")!
        let (data, response) = try await URLSession.shared.data(from: url)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decodingError("\(error)")
        }
    }

    @discardableResult
    private func post<T: Decodable>(_ path: String, body: [String: Any]? = nil) async throws -> T {
        let url = URL(string: "\(baseURL)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }
        return try decoder.decode(T.self, from: data)
    }

    @discardableResult
    private func post(_ path: String, body: [String: Any]? = nil) async throws -> Data {
        let url = URL(string: "\(baseURL)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }
        return data
    }

    private func put<T: Decodable>(_ path: String, body: [String: Any]? = nil) async throws -> T {
        let url = URL(string: "\(baseURL)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decodingError("\(error)")
        }
    }
}
