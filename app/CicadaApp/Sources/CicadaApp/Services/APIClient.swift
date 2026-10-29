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
    /// G139 (R-O18) — the bank IS the memory folder (a pre-banks layout
    /// served in place). Privacy & data never offers it for deletion; an older
    /// backend that omits the field decodes as `false`.
    let legacy: Bool
    /// G117 round 4 (T-Demo) — the server's `demo_guard.is_demo` answer for this bank, never its name (R-CS10): the
    /// demo banner and the tour's demo stops key off it. An older backend that omits it decodes as `false`.
    let demo: Bool

    var id: String { name }
    /// The bank's id in the server's `banks.yaml` (G181 phase 2) — what `X-Cicada-Bank-Id` names (G202). nil from an
    /// older backend.
    var serverId: String? = nil

    enum CodingKeys: String, CodingKey {
        case name, active, entityCount, episodeCount, createdAt, description, legacy, demo
        case serverId = "id"
    }

    /// Memberwise init (the `init(from:)` below suppresses the synthesized
    /// one). `Store.activateBank` flips `active` on a roster row when the
    /// server's answer carries no roster it can read.
    init(name: String, active: Bool, entityCount: Int, episodeCount: Int,
         createdAt: String, description: String?, legacy: Bool = false, demo: Bool = false) {
        self.name = name; self.active = active
        self.entityCount = entityCount; self.episodeCount = episodeCount
        self.createdAt = createdAt; self.description = description
        self.legacy = legacy
        self.demo = demo
    }

    /// A copy with `active` replaced.
    func settingActive(_ isActive: Bool) -> MemoryBank {
        var copy = MemoryBank(name: name, active: isActive, entityCount: entityCount,
                              episodeCount: episodeCount, createdAt: createdAt, description: description,
                              legacy: legacy, demo: demo)
        copy.serverId = serverId
        return copy
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        active = (try? c.decode(Bool.self, forKey: .active)) ?? false
        entityCount = (try? c.decode(Int.self, forKey: .entityCount)) ?? 0
        episodeCount = (try? c.decode(Int.self, forKey: .episodeCount)) ?? 0
        createdAt = (try? c.decode(String.self, forKey: .createdAt)) ?? ""
        description = try c.decodeIfPresent(String.self, forKey: .description)
        legacy = (try? c.decode(Bool.self, forKey: .legacy)) ?? false
        demo = (try? c.decode(Bool.self, forKey: .demo)) ?? false
        serverId = (try? c.decodeIfPresent(String.self, forKey: .serverId)) ?? nil
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

/// Minimal decode of `GET /healthz`. Decode-tolerant: only `memoryRoot` is
/// modeled (everything else `/healthz` returns is unused here), and it's
/// optional so an older backend that hasn't shipped this field yet still
/// decodes — callers must treat `nil`/empty as "unknown, fall back".
///
/// `memoryRoot` is the raw *configured* `CICADA_MEMORY_PATH` — the container
/// of `banks.yaml` + `banks/<name>/`, not a resolved bank path. It's the
/// single source of truth for "which bank does the app's own backend
/// actually use", read by `ConnectView` instead of re-deriving a root from
/// local heuristics that can disagree depending on install layout (G88
/// follow-up).
struct HealthSnapshot: Codable {
    let memoryRoot: String?
    /// G139 — General's version line (Advanced's backend line until 2026-10-22). `/healthz` has always sent
    /// these; each is still `try?` so a probe that answers oddly never costs
    /// the `memoryRoot` read `ConnectView` depends on.
    let version: String?
    let entityCount: Int?
    let episodeCount: Int?

    enum CodingKeys: String, CodingKey { case memoryRoot, version, entityCount, episodeCount }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        memoryRoot = try? c.decode(String.self, forKey: .memoryRoot)
        version = try? c.decode(String.self, forKey: .version)
        entityCount = try? c.decode(Int.self, forKey: .entityCount)
        episodeCount = try? c.decode(Int.self, forKey: .episodeCount)
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
    /// G87 / Wave-1 1.6: whether the target bank is the one Sleep actually
    /// consolidates. Absent on a legacy backend defaults to `true` (today's
    /// silent-success behavior) rather than false, which would wrongly warn
    /// every import against a backend that hasn't shipped this field yet.
    let active: Bool

    enum CodingKeys: String, CodingKey {
        case episodesStaged, episodesUpdated, duplicatesSkipped, format, dateRange, active
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episodesStaged = (try? c.decode(Int.self, forKey: .episodesStaged)) ?? 0
        episodesUpdated = (try? c.decode(Int.self, forKey: .episodesUpdated)) ?? 0
        duplicatesSkipped = (try? c.decode(Int.self, forKey: .duplicatesSkipped)) ?? 0
        format = try c.decodeIfPresent(String.self, forKey: .format)
        dateRange = try c.decodeIfPresent(BankImportDateRange.self, forKey: .dateRange)
        active = (try? c.decode(Bool.self, forKey: .active)) ?? true
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
    /// The provider's own image URL, as the page stores it. Never loaded by the app: `preview` is.
    let thumbnail: String?
    /// The item's picture as Cicada stores it — `/entities/{id}/preview?v=…` (fetched once by the backend) or the
    /// person's own upload — loaded with the bearer through `PictureStore`. `nil` from an older backend and for an
    /// item with nothing to show (the row draws its placeholder).
    let preview: String?
    let savedAt: String
    let tags: [String]
    let status: String
    let relatedCount: Int
    let relevance: Double
    let personalRelevance: String?
    /// G99d — the user's actual save/bookmark/like date, recovered from the
    /// source export when the format allows. Distinct from `savedAt` above,
    /// which — despite its name — has always meant "when Cicada ingested
    /// this" (kept as-is for back-compat rather than renamed out from under
    /// existing readers). `nil` means unknown, never a guess. Use
    /// `recencyDate` for any "most recent first" sort.
    let contentSavedAt: String?
    /// G102: the link's own description excerpt (OpenGraph at ingest, or the
    /// nightly backfill's summary) and the ids of the entities the page is
    /// `about`. Both optional: an older backend omits them and the row still
    /// decodes; `nil` means "not described / related yet", never a guess.
    let description: String?
    let about: [String]?
    /// G124 R6 — the media page's own origin / folder (bookmark folder, board,
    /// device). Optional: an older backend or a pre-origin page has neither.
    /// The Sources page filters the Feed's items to one source by `origin`
    /// and groups them by `folder`; nothing else reads them.
    let origin: String?
    let folder: String?
    /// Track V / R-V2 — the two video keys, decoded here BEFORE the backend
    /// emits them (plan R16): an older `/sources` payload carries neither and
    /// the row must still decode, which is what `MediaBlockDecodeTests` pins.
    ///
    /// `provider` is **redundant** with what `VideoRef.resolve(url)` derives
    /// and nothing in the app dispatches on it — it rides the wire only so a
    /// non-Swift reader can see which provider's oEmbed answered. `durationS`
    /// is the one thing a url cannot tell you, which is why the Feed row's
    /// duration pill reads it; absent means absent, never an estimate (R17).
    let provider: String?
    let durationS: Int?
    /// G133 — `paper` for a paper page, with its byline; `nil` on every other
    /// row and from an older backend.
    let kind: String?
    let paper: PaperSummary?
    /// G166 — how an agent read (or was asked to read) this link and whether it may be asked: the row's `read`
    /// block. `nil` from an older backend, and for a link that is not a page to read (a video, a paper) with
    /// nothing recorded. It moves on the `reading` sync component, so a `needs_login` shows here over SSE.
    let read: MediaReadState?
    /// G191 — the person's newest answer to "What made you save this?"; v3 adds every answer (oldest first, only when
    /// there is more than one), the newest moment the link was saved and the site-capture thumbnail Cicada holds.
    /// All optional: an older backend omits them.
    var savedWhy: SavedWhyRecord? = nil
    var savedWhyHistory: [SavedWhyRecord]? = nil
    var lastSavedAt: String? = nil
    var captureThumb: String? = nil
    /// G191 v4 — the browsers this bookmark has left (one per browser whose file no longer holds it, with since when).
    /// Cicada keeps the bookmark; this is its status. Empty from an older backend.
    var leftBrowser: [BookmarkLeft] = []
    /// G181 phase 3 — the id of the person's device whose token posted the save; nil for what the server's own machine
    /// saved (`DeviceOrigin` names it on the "Saved from" line).
    var device: String? = nil
    /// Owner 2026-10-20 — the key the item's own site mark is drawn under (the backend's `reading_hosts.mark_key`: a
    /// walled family's name, else the registrable domain). Nil from an older backend: the row keeps its old mark.
    var siteKey: String? = nil

    /// Every answer, oldest first (the history when there are several, else the one answer).
    var savedWhyAnswers: [SavedWhyRecord] {
        if let history = savedWhyHistory, !history.isEmpty { return history }
        return savedWhy.map { [$0] } ?? []
    }

    // Row identity must be unique per SAVED ITEM, not per entity page: the
    // ingestor slugifies page titles into mediaEntityId, so 148 distinct
    // Google-consent bookmarks share one entity id — ForEach keyed on it
    // rendered blank row slots for every duplicate.
    var id: String { mediaEntityId + "|" + url }

    /// Prefer the true save date; fall back to the ingest timestamp when no
    /// source date was recoverable (G99d) — what "Recent" should sort by.
    ///
    /// Review finding: comparing `contentSavedAt`/`savedAt` as raw STRINGS
    /// mixed a bare `YYYY-MM-DD` against a full `YYYY-MM-DDTHH:MM:SSZ`
    /// timestamp — on the same calendar day the bare date is a string-prefix
    /// of, and therefore sorts as "less than", the full timestamp, which
    /// happened to look plausible by accident of string length, not by any
    /// documented rule. Parsing both to real `Date`s makes the rule explicit
    /// instead: a bare date has no time-of-day and is anchored to
    /// 00:00:00 UTC (the start of that day), so same-day ties still land the
    /// same way, now on purpose. Mirrors `SourceChannel.lastSyncDate`'s
    /// three-shape tolerance (fractional-seconds ISO8601, plain ISO8601,
    /// bare `yyyy-MM-dd`).
    var recencyDate: Date {
        Self.parseRecencyInstant(contentSavedAt) ?? Self.parseRecencyInstant(savedAt) ?? .distantPast
    }

    private static func parseRecencyInstant(_ value: String?) -> Date? {
        guard let value, !value.isEmpty else { return nil }
        let withFraction = ISO8601DateFormatter()
        withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = withFraction.date(from: value) { return d }
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        if let d = plain.date(from: value) { return d }
        let dayOnly = DateFormatter()
        dayOnly.dateFormat = "yyyy-MM-dd"
        dayOnly.timeZone = TimeZone(identifier: "UTC")
        return dayOnly.date(from: value)
    }

    enum CodingKeys: String, CodingKey {
        case mediaEntityId, url, title, mediaType, site, channel, thumbnail, preview
        case savedAt, tags, status, relatedCount, relevance, personalRelevance
        case contentSavedAt
        case description, about
        case origin, folder
        case provider, durationS
        case kind, paper
        case read
        case savedWhy, savedWhyHistory, lastSavedAt, captureThumb
        case leftBrowser
        case device
        case siteKey
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
        preview = try? c.decodeIfPresent(String.self, forKey: .preview)
        savedAt = (try? c.decode(String.self, forKey: .savedAt)) ?? ""
        tags = (try? c.decode([String].self, forKey: .tags)) ?? []
        status = (try? c.decode(String.self, forKey: .status)) ?? "active"
        relatedCount = (try? c.decode(Int.self, forKey: .relatedCount)) ?? 0
        relevance = (try? c.decode(Double.self, forKey: .relevance)) ?? 0
        personalRelevance = try c.decodeIfPresent(String.self, forKey: .personalRelevance)
        contentSavedAt = try c.decodeIfPresent(String.self, forKey: .contentSavedAt)
        description = try c.decodeIfPresent(String.self, forKey: .description)
        about = try c.decodeIfPresent([String].self, forKey: .about)
        origin = try c.decodeIfPresent(String.self, forKey: .origin)
        folder = try c.decodeIfPresent(String.self, forKey: .folder)
        provider = try c.decodeIfPresent(String.self, forKey: .provider)
        durationS = try c.decodeIfPresent(Int.self, forKey: .durationS)
        kind = try c.decodeIfPresent(String.self, forKey: .kind)
        paper = try c.decodeIfPresent(PaperSummary.self, forKey: .paper)
        read = try? c.decodeIfPresent(MediaReadState.self, forKey: .read)
        savedWhy = try? c.decodeIfPresent(SavedWhyRecord.self, forKey: .savedWhy)
        savedWhyHistory = try? c.decodeIfPresent([SavedWhyRecord].self, forKey: .savedWhyHistory)
        lastSavedAt = try? c.decodeIfPresent(String.self, forKey: .lastSavedAt)
        captureThumb = try? c.decodeIfPresent(String.self, forKey: .captureThumb)
        leftBrowser = (try? c.decodeIfPresent([BookmarkLeft].self, forKey: .leftBrowser)) ?? []
        device = (try? c.decodeIfPresent(String.self, forKey: .device)) ?? nil
        siteKey = (try? c.decodeIfPresent(String.self, forKey: .siteKey)) ?? nil
    }

    var isPaper: Bool { kind == "paper" }
}

/// G191 v4 — "No longer in Chrome since Oct 15": `GET /sources` → `leftBrowser[]`.
struct BookmarkLeft: Codable, Equatable, Hashable, Sendable {
    var browser: String
    var channel: String = ""
    /// When a sync first saw it gone (aware ISO).
    var since: String
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
/// `chrome-bookmark` or `safari-bookmark`). `channel` (R4) is the
/// `sync_state.json` key that sync stamped — `chrome-bookmarks` /
/// `safari-bookmarks` — optional so a backend from before the split still
/// decodes.
struct BookmarkSyncSourceSummary: Codable {
    let origin: String
    let channel: String?
    let found: Int
    let new: Int
    let skipped: Int
    /// R-SR13 — Safari's Reading List and Favorites tallies (0 for every other browser). Optional so a backend from
    /// before round 4 still decodes; declared last so the memberwise init keeps its order.
    var readingList: Int? = nil
    var favorites: Int? = nil
    /// G191 — this channel had never been synced before this pass. Optional so an older backend still decodes.
    var firstSync: Bool? = nil
}

/// G191 — one bookmark a sync newly saved (`POST /sources/sync-bookmarks` → `fresh`). `addedAt` is the browser's own
/// instant (aware UTC ISO), present only when its file records one (Chrome; Safari's Reading List).
struct FreshBookmark: Codable, Equatable, Sendable {
    let url: String
    var title: String = ""
    var origin: String = ""
    var channel: String = ""
    var episodeId: String = ""
    var addedAt: String? = nil
    /// G191 v3 — a link Cicada already held, saved again in this browser (removed and bookmarked again). Optional so
    /// an older backend still decodes.
    var resave: Bool? = nil
    /// G191 v5 — Chromium's own `date_added` (WebKit microseconds since 1601), set only by the app's diff of the file,
    /// never by the backend: the bubble watcher's teacher needs the instant to the millisecond, not floored to the
    /// second as `addedAt` is.
    var addedMicros: Int64? = nil

    /// The page's host without `www.`, lower-cased — the key "Don't ask for this site" remembers.
    var host: String? {
        guard let host = URL(string: url)?.host?.lowercased(), !host.isEmpty else { return nil }
        return host.hasPrefix("www.") ? String(host.dropFirst(4)) : host
    }

    var addedDate: Date? {
        guard let addedAt else { return nil }
        return ISO8601DateFormatter().date(from: addedAt)
    }

    /// G191 v5 — the exact instant the browser made it (`addedMicros`), when the app's diff read it.
    var addedInstant: Date? { addedMicros.flatMap(BookmarkEntry.instant(micros:)) }
}

/// `POST /sources/sync-bookmarks` result — aggregate new/skipped plus the
/// per-browser breakdown.
struct BookmarkSyncResult {
    let new: Int
    let skipped: Int
    let sources: [BookmarkSyncSourceSummary]
    /// G129 slice 2 — how many `removal` inbox items this sync proposed.
    /// Defaulted so the pre-existing 3-arg call sites still compile.
    var removalsProposed: Int = 0
    /// Non-nil only when the correctness rails refused to compute removals
    /// this sync (a folder-scope change since the last sync on some channel).
    var removalsSkipped: String? = nil
    /// G191 — the bookmarks this sync newly saved (at most a few) and how many in all. Empty from an older backend.
    var fresh: [FreshBookmark] = []
    var freshTotal: Int = 0
    /// G191 v4 — how many links this sync marked as gone from their browser (never a question).
    var leftMarked: Int = 0
}

// `Codable` conformance lives in an extension, not the primary declaration,
// for the same reason `InboxItem.InboxOption` does this: a custom
// `init(from:)` on the struct itself would suppress the synthesized
// memberwise init that `BrowserImportModelTests.swift` and call sites across
// the app construct `BookmarkSyncResult` with directly.
extension BookmarkSyncResult: Codable {
    enum CodingKeys: String, CodingKey {
        case new, skipped, sources, removalsProposed, removalsSkipped, fresh, freshTotal, leftMarked
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        new = try c.decode(Int.self, forKey: .new)
        skipped = try c.decode(Int.self, forKey: .skipped)
        sources = try c.decodeIfPresent([BookmarkSyncSourceSummary].self, forKey: .sources) ?? []
        removalsProposed = try c.decodeIfPresent(Int.self, forKey: .removalsProposed) ?? 0
        removalsSkipped = try c.decodeIfPresent(String.self, forKey: .removalsSkipped)
        fresh = (try? c.decodeIfPresent([FreshBookmark].self, forKey: .fresh)) ?? []
        freshTotal = (try? c.decodeIfPresent(Int.self, forKey: .freshTotal)) ?? fresh.count
        leftMarked = (try? c.decodeIfPresent(Int.self, forKey: .leftMarked)) ?? 0
    }
}

/// G191 — `GET /sources/saved-why/options`: the fixed one-tap reasons (G191 v4: four, and never a project —
/// `projects` stays on the wire, always empty).
struct SavedWhyOptions: Codable, Equatable, Sendable {
    struct Reason: Codable, Equatable, Sendable, Identifiable {
        let key: String
        let label: String
        var id: String { key }
    }
    struct Project: Codable, Equatable, Sendable, Identifiable {
        let id: String
        let name: String
    }
    var reasons: [Reason] = []
    var projects: [Project] = []
    var maxText: Int = 500
    /// G191 v7 — the reason bank the panel suggests a few from (`saved_why.MORE`), beside the fixed row. Empty from an
    /// older backend, which would refuse a bank key: the panel then suggests nothing.
    var more: [Reason] = []

    /// Every reason the panel can hold a tap for, in the order an answer lists them: the fixed row, then the bank.
    var order: [String] { reasons.map(\.key) + more.map(\.key) }

    /// G191 v4 — the four fixed reasons (`saved_why.REASONS` on the backend, same keys and words), so the panel can
    /// show at once before the backend's options arrive. The backend's list replaces it as soon as it answers.
    static let basic = SavedWhyOptions(reasons: [
        .init(key: "design", label: "The design"),
        .init(key: "product", label: "The product"),
        .init(key: "read_later", label: "To read later"),
        .init(key: "someday", label: "Useful someday"),
    ], projects: [], maxText: 500)
}

extension SavedWhyOptions {
    private enum CodingKeys: String, CodingKey { case reasons, projects, maxText, more }

    /// Decoded field by field so a backend older than G191 v7 (no `more`) still decodes.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        reasons = try c.decodeIfPresent([Reason].self, forKey: .reasons) ?? []
        projects = try c.decodeIfPresent([Project].self, forKey: .projects) ?? []
        maxText = try c.decodeIfPresent(Int.self, forKey: .maxText) ?? 500
        more = (try? c.decodeIfPresent([Reason].self, forKey: .more)) ?? []
    }
}

/// G191 v7 — `POST /sources/saved-why/suggest`: how close each bank reason is to the saved link, by the search model
/// only when it is already installed (`basis` `model`), else nothing (`none`) and the panel ranks on its own.
struct SavedWhyModelScores: Codable, Equatable, Sendable {
    struct Score: Codable, Equatable, Sendable {
        let key: String
        let score: Double
    }
    var basis: String = "none"
    var scores: [Score] = []

    /// The scores by key, or nil when no model scored the bank.
    var byKey: [String: Double]? {
        guard basis == "model", !scores.isEmpty else { return nil }
        return Dictionary(scores.map { ($0.key, $0.score) }, uniquingKeysWith: { first, _ in first })
    }
}

/// G191 — one answer as the source record carries it (`GET /sources` → `savedWhy` / `savedWhyHistory`): the reason
/// keys with their labels, the project, the person's words, when they said it (`at`), when the browser says that save
/// was made (`addedAt`) and when they last changed it (`editedAt`, v3).
struct SavedWhyRecord: Codable, Equatable, Sendable, Hashable {
    var reasons: [String] = []
    var labels: [String] = []
    var project: String? = nil
    var text: String? = nil
    var at: String? = nil
    var addedAt: String? = nil
    var editedAt: String? = nil

    var answer: SavedWhyAnswer { SavedWhyAnswer(reasons: reasons, project: project, text: text) }
}

/// G191 v3 — `POST`/`PUT /sources/saved-why`'s answer: the answer written and every answer on the link now.
struct SavedWhyReply: Codable, Equatable, Sendable {
    var episodeId: String = ""
    var mediaEntityId: String = ""
    var savedWhy: SavedWhyRecord
    var history: [SavedWhyRecord]? = nil
}

/// G191 v3 — `POST /sources/bookmarks/remove`'s answer.
struct BookmarkRemoveReply: Codable, Equatable, Sendable {
    var episodeId: String = ""
    var mediaEntityId: String = ""
    var status: String = "archived"
}

/// G191 — what the person answered, posted to `POST /sources/saved-why`.
struct SavedWhyAnswer: Codable, Equatable, Sendable {
    var reasons: [String] = []
    var project: String? = nil
    var text: String? = nil

    var isEmpty: Bool { reasons.isEmpty && project == nil && (text?.isEmpty ?? true) }

    var body: [String: Any] {
        var out: [String: Any] = ["reasons": reasons]
        if let project { out["project"] = project }
        if let text, !text.isEmpty { out["text"] = text }
        return out
    }
}

/// G191 live — the bytes of one browser's bookmark file, as the early look sends them.
enum BookmarkBytes: Sendable, Equatable {
    case chrome(Data)
    case safari(Data)
    /// A Chromium-family browser beyond Chrome (round 4, C9), by its catalog id.
    case chromium(browser: String, Data)

    /// The sync's own request body (`chromeDataB64` / `safariDataB64` / `chromium`), so the look and the sync can
    /// never send different shapes.
    var body: [String: Any] {
        switch self {
        case .chrome(let data): return ["chromeDataB64": data.base64EncodedString()]
        case .safari(let data): return ["safariDataB64": data.base64EncodedString()]
        case .chromium(let browser, let data):
            return ["chromium": [["browser": browser, "dataB64": data.base64EncodedString()]]]
        }
    }
}

/// G191 — the calls the panel makes; `APIClient` is the live one, tests inject their own.
protocol SavedWhyAPI: Sendable {
    /// G191 live — the early look (`POST /sources/sync-bookmarks/fresh`): which bookmarks in these bytes the bank
    /// does not hold yet, without ingesting — answered in a parse, not after the sync's page fetches and commits.
    func freshBookmarks(_ bytes: BookmarkBytes) async throws -> BookmarkSyncResult
    func savedWhyOptions() async throws -> SavedWhyOptions
    /// `at` is when the person answered — sent so an answer held through a 409 keeps its own time (review B1).
    /// `addedAt` (G191 v3) is the moment of saving it answers: a re-save's answer is a new dated reason.
    func saveWhy(url: String, answer: SavedWhyAnswer, at: Date, addedAt: String?) async throws
    /// 2026-10-19 — the star on a page already saved: change the answer said at `at` (`PUT /sources/saved-why`).
    func editSavedWhy(url: String, at: String, answer: SavedWhyAnswer) async throws -> SavedWhyReply
    /// G191 v7 — the search model's similarity of each bank reason to the saved link, only when it is installed.
    func savedWhySuggest(url: String, title: String) async throws -> SavedWhyModelScores
}

extension SavedWhyAPI {
    func savedWhySuggest(url: String, title: String) async throws -> SavedWhyModelScores { SavedWhyModelScores() }

    /// A client that cannot edit (tests that never edit): refused as the backend refuses an unknown answer.
    func editSavedWhy(url: String, at: String, answer: SavedWhyAnswer) async throws -> SavedWhyReply {
        throw APIError.httpError(422, "editing is not supported here")
    }
}

/// `POST /sources/sync-notes` result — Apple Notes one-way sync tally. Mirrors
/// `BookmarkSyncResult`'s new/skipped shape; Notes is a single local source so
/// there's no per-app breakdown to carry. Any extra fields the backend sends
/// (e.g. a `sources` echo) are simply ignored by `Decodable`.
struct NoteSyncResult: Codable {
    let new: Int
    let skipped: Int

    enum CodingKeys: String, CodingKey { case new, skipped }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        new = (try? c.decode(Int.self, forKey: .new)) ?? 0
        skipped = (try? c.decode(Int.self, forKey: .skipped)) ?? 0
    }
}

// MARK: - RSS feed subscriptions (G9 — feeds.yaml registry)

/// One subscribed RSS/Atom feed (`GET /sources/feeds` / `POST /sources/feeds`).
/// NOTE: unlike most endpoints, `/sources/feeds` echoes the raw on-disk record
/// straight from `feed_registry.py` — it is NOT run through the API's
/// CamelModel/`to_camel` alias generator, so `last_polled` stays snake_case on
/// the wire (everything else here is a single word, so it looks camelCase by
/// coincidence).
struct FeedSubscription: Codable, Identifiable {
    let url: String
    let tags: [String]
    let added: String
    let lastPolled: String?

    var id: String { url }

    enum CodingKeys: String, CodingKey {
        case url, tags, added
        case lastPolled = "last_polled"
    }

    /// Memberwise init — `SubscribeFeed`'s optimistic apply inserts a
    /// provisional row (no `lastPolled` yet) that the server's echo replaces.
    init(url: String, tags: [String] = [], added: String = "", lastPolled: String? = nil) {
        self.url = url; self.tags = tags; self.added = added; self.lastPolled = lastPolled
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        url = try c.decode(String.self, forKey: .url)
        tags = (try? c.decode([String].self, forKey: .tags)) ?? []
        added = (try? c.decode(String.self, forKey: .added)) ?? ""
        lastPolled = try c.decodeIfPresent(String.self, forKey: .lastPolled)
    }
}

/// `GET /sources/feeds` envelope — the feed list plus a count.
private struct FeedListResponse: Codable {
    let feeds: [FeedSubscription]
    let total: Int

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        feeds = (try? c.decode([FeedSubscription].self, forKey: .feeds)) ?? []
        total = (try? c.decode(Int.self, forKey: .total)) ?? 0
    }
    enum CodingKeys: String, CodingKey { case feeds, total }
}

/// One feed's outcome within a `POST /sources/poll-feeds` sweep. Snake_case
/// wire keys, same reasoning as `FeedSubscription` above.
struct PollFeedItemResult: Codable, Identifiable {
    let url: String
    let status: String
    let new: Int?
    let duplicates: Int?
    let error: String?

    var id: String { url }

    enum CodingKeys: String, CodingKey { case url, status, new, duplicates, error }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        url = try c.decode(String.self, forKey: .url)
        status = (try? c.decode(String.self, forKey: .status)) ?? ""
        new = try c.decodeIfPresent(Int.self, forKey: .new)
        duplicates = try c.decodeIfPresent(Int.self, forKey: .duplicates)
        error = try c.decodeIfPresent(String.self, forKey: .error)
    }
}

/// `POST /sources/poll-feeds` result. `skippedNoNetwork` (wire: number of
/// feeds skipped — see below) is only present when live feed fetch is gated
/// off server-side (`CICADA_ALLOW_FEED_FETCH` unset), in which case `new` and
/// `perFeed` stay at their zero/empty defaults since nothing was fetched.
struct PollFeedsResult: Codable {
    let polled: Int
    let new: Int
    let skippedNoNetwork: Int
    let perFeed: [PollFeedItemResult]

    enum CodingKeys: String, CodingKey {
        case polled, new
        case skippedNoNetwork = "skipped_no_network"
        case perFeed = "per_feed"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        polled = (try? c.decode(Int.self, forKey: .polled)) ?? 0
        new = (try? c.decode(Int.self, forKey: .new)) ?? 0
        skippedNoNetwork = (try? c.decode(Int.self, forKey: .skippedNoNetwork)) ?? 0
        perFeed = (try? c.decode([PollFeedItemResult].self, forKey: .perFeed)) ?? []
    }
}

// MARK: - Calendar subscriptions (mirrors RSS feed subscriptions above,
// same on-disk-registry reasoning — calendars.yaml in place of feeds.yaml)

/// One subscribed ICS/webcal calendar (`GET /sources/calendars` /
/// `POST /sources/calendars`). Mirrors `FeedSubscription` field-for-field:
/// echoes the raw on-disk record straight from the calendar registry, so
/// `last_polled` stays snake_case on the wire like its feed counterpart.
struct CalendarSubscription: Codable, Identifiable {
    let url: String
    let tags: [String]
    let added: String
    let lastPolled: String?

    var id: String { url }

    enum CodingKeys: String, CodingKey {
        case url, tags, added
        case lastPolled = "last_polled"
    }

    /// Memberwise init — mirrors `FeedSubscription`'s, for the optimistic
    /// `SubscribeCalendar` row.
    init(url: String, tags: [String] = [], added: String = "", lastPolled: String? = nil) {
        self.url = url; self.tags = tags; self.added = added; self.lastPolled = lastPolled
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        url = try c.decode(String.self, forKey: .url)
        tags = (try? c.decode([String].self, forKey: .tags)) ?? []
        added = (try? c.decode(String.self, forKey: .added)) ?? ""
        lastPolled = try c.decodeIfPresent(String.self, forKey: .lastPolled)
    }
}

/// `GET /sources/calendars` envelope — the calendar list plus a count.
private struct CalendarListResponse: Codable {
    let calendars: [CalendarSubscription]
    let total: Int

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        calendars = (try? c.decode([CalendarSubscription].self, forKey: .calendars)) ?? []
        total = (try? c.decode(Int.self, forKey: .total)) ?? 0
    }
    enum CodingKeys: String, CodingKey { case calendars, total }
}

/// One calendar's outcome within a `POST /sources/poll-calendars` sweep.
/// Snake_case wire keys, mirrors `PollFeedItemResult`.
struct PollCalendarItemResult: Codable, Identifiable {
    let url: String
    let status: String
    let new: Int?
    let duplicates: Int?
    let error: String?

    var id: String { url }

    enum CodingKeys: String, CodingKey { case url, status, new, duplicates, error }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        url = try c.decode(String.self, forKey: .url)
        status = (try? c.decode(String.self, forKey: .status)) ?? ""
        new = try c.decodeIfPresent(Int.self, forKey: .new)
        duplicates = try c.decodeIfPresent(Int.self, forKey: .duplicates)
        error = try c.decodeIfPresent(String.self, forKey: .error)
    }
}

/// `POST /sources/poll-calendars` result. Mirrors `PollFeedsResult` — when
/// the network gate is closed server-side, `new`/`perCalendar` stay at their
/// zero/empty defaults and `skippedNoNetwork` reports the count instead.
struct PollCalendarsResult: Codable {
    let polled: Int
    let new: Int
    let skippedNoNetwork: Int
    let perCalendar: [PollCalendarItemResult]

    enum CodingKeys: String, CodingKey {
        case polled, new
        case skippedNoNetwork = "skipped_no_network"
        case perCalendar = "per_calendar"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        polled = (try? c.decode(Int.self, forKey: .polled)) ?? 0
        new = (try? c.decode(Int.self, forKey: .new)) ?? 0
        skippedNoNetwork = (try? c.decode(Int.self, forKey: .skippedNoNetwork)) ?? 0
        perCalendar = (try? c.decode([PollCalendarItemResult].self, forKey: .perCalendar)) ?? []
    }
}

// MARK: - Origins (ORIGIN-PROVENANCE — "where did this memory come from")

/// One capture origin's tally from `GET /origins` — mirrors `Contributor`'s
/// "who authored this belief" but keyed on capture origin (mcp, telegram,
/// chrome-bookmark, safari-bookmark, claude-export, ...) rather than authoring
/// model. Runs through the API's CamelModel, so these ARE camelCase on the wire.
struct OriginStat: Codable, Identifiable {
    let origin: String
    let episodeCount: Int
    let entityCount: Int
    let lastSeen: String

    var id: String { origin }

    enum CodingKeys: String, CodingKey {
        case origin, episodeCount, entityCount, lastSeen
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        origin = try c.decode(String.self, forKey: .origin)
        episodeCount = (try? c.decode(Int.self, forKey: .episodeCount)) ?? 0
        entityCount = (try? c.decode(Int.self, forKey: .entityCount)) ?? 0
        lastSeen = (try? c.decode(String.self, forKey: .lastSeen)) ?? ""
    }
}

struct OriginsResponse: Codable {
    let origins: [OriginStat]

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        origins = (try? c.decode([OriginStat].self, forKey: .origins)) ?? []
    }
    enum CodingKeys: String, CodingKey { case origins }
}

/// How far behind Sleep is, right now — independent of whether a cycle is
/// currently running. Mirrors `api/models/schemas.py::SleepDebtResponse`;
/// see `api/services/sleep_debt.py` for the formula. Decode-tolerant (every
/// numeric field defaults to a safe value) so an older cached app build
/// reading a payload that lacks this block entirely still constructs one via
/// `SleepDebtInfo.unknown`.
struct SleepDebtInfo: Codable, Equatable {
    let unprocessedCount: Int
    let oldestUnprocessedAgeHours: Double?
    let hoursSinceLastCycle: Double?
    let hasRunBefore: Bool
    let volumePct: Int
    let agePct: Int
    /// `nil` ONLY when the queue is empty AND Sleep has never run in this
    /// bank — no baseline to call "rested" (see the backend docstring).
    let restedPct: Int?
    /// Sleep page v5 — conversations parked after failing twice for their own reasons: still waiting (they are in
    /// `unprocessedCount`), but a run's freeze skips them. 0 on an older backend.
    let parkedCount: Int
    /// What a run would read now (`unprocessed - parked`); `nil` on an older backend. Every "reads all N" string
    /// reads `readable`, never `unprocessedCount` (M7).
    let readableCount: Int?

    /// What a Consolidate would read now: the server's own count, else the queue (an older backend parks nothing).
    var readable: Int { readableCount ?? max(0, unprocessedCount - parkedCount) }

    enum CodingKeys: String, CodingKey {
        case unprocessedCount, oldestUnprocessedAgeHours, hoursSinceLastCycle
        case hasRunBefore, volumePct, agePct, restedPct, parkedCount, readableCount
    }

    init(unprocessedCount: Int, oldestUnprocessedAgeHours: Double?, hoursSinceLastCycle: Double?,
         hasRunBefore: Bool, volumePct: Int, agePct: Int, restedPct: Int?, parkedCount: Int = 0,
         readableCount: Int? = nil) {
        self.parkedCount = parkedCount
        self.readableCount = readableCount
        self.unprocessedCount = unprocessedCount
        self.oldestUnprocessedAgeHours = oldestUnprocessedAgeHours
        self.hoursSinceLastCycle = hoursSinceLastCycle
        self.hasRunBefore = hasRunBefore
        self.volumePct = volumePct
        self.agePct = agePct
        self.restedPct = restedPct
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        unprocessedCount = try c.decodeIfPresent(Int.self, forKey: .unprocessedCount) ?? 0
        oldestUnprocessedAgeHours = try c.decodeIfPresent(Double.self, forKey: .oldestUnprocessedAgeHours)
        hoursSinceLastCycle = try c.decodeIfPresent(Double.self, forKey: .hoursSinceLastCycle)
        hasRunBefore = try c.decodeIfPresent(Bool.self, forKey: .hasRunBefore) ?? false
        volumePct = try c.decodeIfPresent(Int.self, forKey: .volumePct) ?? 0
        agePct = try c.decodeIfPresent(Int.self, forKey: .agePct) ?? 0
        restedPct = try c.decodeIfPresent(Int.self, forKey: .restedPct)
        parkedCount = ((try? c.decodeIfPresent(Int.self, forKey: .parkedCount)) ?? nil) ?? 0
        readableCount = (try? c.decodeIfPresent(Int.self, forKey: .readableCount)) ?? nil
    }

    /// A backend too old to send `debt` at all — the honest "we don't know"
    /// shape, not a fabricated zero-debt reading.
    static let unknown = SleepDebtInfo(
        unprocessedCount: 0, oldestUnprocessedAgeHours: nil, hoursSinceLastCycle: nil,
        hasRunBefore: false, volumePct: 0, agePct: 0, restedPct: nil
    )
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
    /// G74(a) — which engine the last cycle ran on ("claude-cli" | "ollama" |
    /// "litellm"), and one sentence about its state. Both absent on an older
    /// backend, so both are optional.
    let lastEngine: String?
    let engineDetail: String?
    /// Sleep control — episode cap. `episodesQueued` is the FULL unprocessed
    /// count found before capping; `episodeCap` is the cap applied.
    /// `episodesQueued > episodesTotal` means this cycle was truncated.
    /// Both absent (0) on an older backend.
    let episodeCap: Int
    /// The configured batch size, served with no run behind it (`episodeCap` is 0 after a restart and after an
    /// empty-queue run). 0 on an older backend, which is when the lamp falls back to `episodeCap`.
    let batchSize: Int
    let episodesQueued: Int
    /// Sleep control — cooperative cancellation. `cancelRequested` is true
    /// while a `/sleep/cancel` is pending on the running cycle;
    /// `cancelled` is true on the first status read after a cycle actually
    /// stopped early because of one. Both absent (false) on an older backend.
    let cancelRequested: Bool
    let cancelled: Bool
    /// Sleep debt (G106) — always present on a current backend; `.unknown`
    /// on an older one that never sent the block at all.
    let debt: SleepDebtInfo
    /// Live "episodes processed / episodes in this cycle" DURING a cycle.
    /// `nil` — never a fabricated 0 — whenever there is no honest live
    /// number: idle, or Stage 1 has already finished (see the backend's
    /// `sleep_cycle.progress_pct` docstring for the full contract).
    let progressPct: Int?
    /// G125 R3 — this cycle's selected episodes by source, and how many of
    /// each Stage 1 has finished. Both `[:]` when idle, and on an older
    /// backend that predates these fields.
    let queueByOrigin: [String: Int]
    let readByOrigin: [String: Int]
    /// "Consolidate reads everything" (G163): a person-started run's measured
    /// progress — batch k of n, filed of frozen, and why it stopped. `nil` on a
    /// scheduled or idle cycle and on an older backend; never a fabricated 0.
    let drain: SleepDrainInfo?
    /// G177 — Sleep holds the bank's pages right now. A drain between batches is
    /// `running` but not `writing`; the server refuses page writes only while it is. The app's own write controls
    /// (`ProjectWriteGate`) still key off `running`, because `/status` does not carry this field.
    /// `false` on an older backend, which is why it is not read as "not running".
    let writing: Bool
    /// Sleep page v5 — a run that stopped with conversations still waiting, read from the active bank's sidecar;
    /// `nil` while a run reads, when there is none, and on an older backend. Paused is not a state of Sleep:
    /// `status` stays `idle` and nothing is held.
    let paused: SleepPausedRun?
    /// 2026-10-16 — the newest FINISHED cycle's figures, found by the backend (`last_cycle.latest`): a drain is one
    /// cycle, and a run still reading or paused is skipped however many history rows it fills. `nil` with
    /// `reportsLastFinishedCycle` = there is none; an older backend omits the key (`reportsLastFinishedCycle` false).
    var lastFinishedCycle: LastFinishedCycle? = nil
    var reportsLastFinishedCycle = false

    enum CodingKeys: String, CodingKey {
        case drain, writing, paused, lastFinishedCycle
        case status, cycleId, startedAt, progress, error, indexWarning, stage, totalStages
        case episodesTotal, entitiesCreated, entitiesUpdated
        case relationshipsCreated, skillsDetected
        case lastEngine, engineDetail
        case episodeCap, batchSize, episodesQueued, cancelRequested, cancelled
        case debt, progressPct, queueByOrigin, readByOrigin
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
        lastEngine = try c.decodeIfPresent(String.self, forKey: .lastEngine)
        engineDetail = try c.decodeIfPresent(String.self, forKey: .engineDetail)
        episodeCap = try c.decodeIfPresent(Int.self, forKey: .episodeCap) ?? 0
        batchSize = try c.decodeIfPresent(Int.self, forKey: .batchSize) ?? 0
        episodesQueued = try c.decodeIfPresent(Int.self, forKey: .episodesQueued) ?? 0
        cancelRequested = try c.decodeIfPresent(Bool.self, forKey: .cancelRequested) ?? false
        cancelled = try c.decodeIfPresent(Bool.self, forKey: .cancelled) ?? false
        debt = try c.decodeIfPresent(SleepDebtInfo.self, forKey: .debt) ?? .unknown
        progressPct = try c.decodeIfPresent(Int.self, forKey: .progressPct)
        queueByOrigin = try c.decodeIfPresent([String: Int].self, forKey: .queueByOrigin) ?? [:]
        readByOrigin = try c.decodeIfPresent([String: Int].self, forKey: .readByOrigin) ?? [:]
        drain = try? c.decodeIfPresent(SleepDrainInfo.self, forKey: .drain)
        writing = (try? c.decodeIfPresent(Bool.self, forKey: .writing)) ?? false
        paused = (try? c.decodeIfPresent(SleepPausedRun.self, forKey: .paused)) ?? nil
        reportsLastFinishedCycle = c.contains(.lastFinishedCycle)
        lastFinishedCycle = (try? c.decodeIfPresent(LastFinishedCycle.self, forKey: .lastFinishedCycle)) ?? nil
    }
}

/// `SleepStatusResponse.lastFinishedCycle` — ids, numbers and enums. `drainId` names the run when the cycle was one;
/// then `durationMs` is the run's reading time and `usageSummary` the whole run's cost. Unknown is `nil`, never zero.
struct LastFinishedCycle: Codable, Equatable {
    var commitHash: String
    var date: String
    var drainId: String?
    var batches: Int?
    var durationMs: Int?
    var engine: String?
    var usageSummary: CycleUsageSummary?
    var state: String?

    init(commitHash: String, date: String, drainId: String? = nil, batches: Int? = nil, durationMs: Int? = nil,
         engine: String? = nil, usageSummary: CycleUsageSummary? = nil, state: String? = nil) {
        self.commitHash = commitHash; self.date = date; self.drainId = drainId; self.batches = batches
        self.durationMs = durationMs; self.engine = engine; self.usageSummary = usageSummary; self.state = state
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        commitHash = try c.decode(String.self, forKey: .commitHash)
        date = ((try? c.decodeIfPresent(String.self, forKey: .date)) ?? nil) ?? ""
        drainId = (try? c.decodeIfPresent(String.self, forKey: .drainId)) ?? nil
        batches = (try? c.decodeIfPresent(Int.self, forKey: .batches)) ?? nil
        durationMs = (try? c.decodeIfPresent(Int.self, forKey: .durationMs)) ?? nil
        engine = (try? c.decodeIfPresent(String.self, forKey: .engine)) ?? nil
        usageSummary = (try? c.decodeIfPresent(CycleUsageSummary.self, forKey: .usageSummary)) ?? nil
        state = (try? c.decodeIfPresent(String.self, forKey: .state)) ?? nil
    }
    enum CodingKeys: String, CodingKey { case commitHash, date, drainId, batches, durationMs, engine, usageSummary, state }
}

/// The `drain` block of `GET /sleep/status` (`sleep_drain.to_wire`): counts and one
/// stop reason, never an episode id. Every field decodes leniently so a backend that
/// adds one cannot make the whole status fail to decode.
struct SleepDrainInfo: Codable, Equatable {
    struct Stop: Codable, Equatable {
        /// `cancelled | plan_limit | engine | bank_switched | error`.
        var reason: String
        /// A plain sentence for the person — the vendor's own for a plan limit.
        var sentence: String?
        /// The vendor's unix reset time, when one was measured.
        var resetsAt: Int?
        /// Which limit a plan stop was (Sleep page v5): `five_hour | seven_day | overage | unknown`.
        var limit: String?

        init(reason: String, sentence: String? = nil, resetsAt: Int? = nil, limit: String? = nil) {
            self.reason = reason; self.sentence = sentence; self.resetsAt = resetsAt; self.limit = limit
        }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            reason = (try? c.decode(String.self, forKey: .reason)) ?? "error"
            sentence = try? c.decodeIfPresent(String.self, forKey: .sentence)
            resetsAt = try? c.decodeIfPresent(Int.self, forKey: .resetsAt)
            limit = (try? c.decodeIfPresent(String.self, forKey: .limit)) ?? nil
        }
        enum CodingKeys: String, CodingKey { case reason, sentence, resetsAt, limit }

        /// A plan pause whose vendor-measured reset time has passed: the limit no longer holds, so nothing
        /// should keep saying "paused". `false` without a measured time (it is never guessed).
        func planPauseLapsed(now: Date) -> Bool {
            guard reason == "plan_limit", let resetsAt else { return false }
            return Date(timeIntervalSince1970: TimeInterval(resetsAt)) <= now
        }
    }

    var id: String
    /// Episodes waiting when the run began — what it set out to read.
    var frozen: Int
    var batchSize: Int
    /// The batch the run is on or stopped in, a batch started and then dropped included — not "batches committed".
    var batch: Int
    /// The PLAN (`batch` plus the batches still to do), not a count of batches committed: never print it as
    /// "n batches" for a run that stopped. `filed` is the measured figure.
    var batches: Int
    var filed: Int
    var requeued: Int
    var skipped: Int
    var active: Bool
    var finished: Bool
    var stop: Stop?
    /// Episodes that arrived after the run began (they wait for the next one); `nil` until it ends.
    var arrivedSince: Int?

    // MARK: Sleep page v5 — every key optional, so an older backend reads no news.

    /// One stage of the running batch (P15 / R-A8 amended): a stage carries a fill only when it counts something
    /// that finished (Read, Sort, Decide); Notice and File carry no number.
    struct Stage: Codable, Equatable, Identifiable {
        var id: String
        var unit: String?
        var done: Int
        var total: Int?
        var failed: Int
        /// `pending | active | done`.
        var state: String

        init(id: String, unit: String? = nil, done: Int = 0, total: Int? = nil, failed: Int = 0, state: String = "pending") {
            self.id = id; self.unit = unit; self.done = done; self.total = total; self.failed = failed; self.state = state
        }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            id = ((try? c.decodeIfPresent(String.self, forKey: .id)) ?? nil) ?? ""
            unit = (try? c.decodeIfPresent(String.self, forKey: .unit)) ?? nil
            done = ((try? c.decodeIfPresent(Int.self, forKey: .done)) ?? nil) ?? 0
            total = (try? c.decodeIfPresent(Int.self, forKey: .total)) ?? nil
            failed = ((try? c.decodeIfPresent(Int.self, forKey: .failed)) ?? nil) ?? 0
            state = ((try? c.decodeIfPresent(String.self, forKey: .state)) ?? nil) ?? "pending"
        }
        enum CodingKeys: String, CodingKey { case id, unit, done, total, failed, state }
    }

    /// The running batch: `read` finished, `reading` started and not finished, `failed` this batch.
    struct BatchState: Codable, Equatable {
        var index: Int
        var of: Int
        var total: Int
        var read: Int
        var reading: Int
        var failed: Int

        init(index: Int = 0, of: Int = 0, total: Int = 0, read: Int = 0, reading: Int = 0, failed: Int = 0) {
            self.index = index; self.of = of; self.total = total; self.read = read; self.reading = reading; self.failed = failed
        }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            func int(_ key: CodingKeys) -> Int { ((try? c.decodeIfPresent(Int.self, forKey: key)) ?? nil) ?? 0 }
            index = int(.index); of = int(.of); total = int(.total); read = int(.read); reading = int(.reading)
            failed = int(.failed)
        }
        enum CodingKeys: String, CodingKey { case index, of, total, read, reading, failed }
    }

    /// Per source: `frozen = filed + read + waiting + couldNotBeRead + parked + skipped` at every step.
    struct Origin: Codable, Equatable {
        var frozen: Int
        var filed: Int
        var read: Int
        var waiting: Int
        var couldNotBeRead: Int
        var parked: Int
        var skipped: Int
        var newSince: Int

        init(frozen: Int = 0, filed: Int = 0, read: Int = 0, waiting: Int = 0, couldNotBeRead: Int = 0,
             parked: Int = 0, skipped: Int = 0, newSince: Int = 0) {
            self.frozen = frozen; self.filed = filed; self.read = read; self.waiting = waiting
            self.couldNotBeRead = couldNotBeRead; self.parked = parked; self.skipped = skipped; self.newSince = newSince
        }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            func int(_ key: CodingKeys) -> Int { ((try? c.decodeIfPresent(Int.self, forKey: key)) ?? nil) ?? 0 }
            frozen = int(.frozen); filed = int(.filed); read = int(.read); waiting = int(.waiting)
            couldNotBeRead = int(.couldNotBeRead); parked = int(.parked); skipped = int(.skipped); newSince = int(.newSince)
        }
        enum CodingKeys: String, CodingKey { case frozen, filed, read, waiting, couldNotBeRead, parked, skipped, newSince }
    }

    /// `user | schedule`.
    var startedBy: String? = nil
    /// No earlier Sleep commit in this bank when the run started.
    var firstRun: Bool? = nil
    var committedBatches: Int? = nil
    /// Engine calls made in this run; never decreases (a discarded batch's calls stay counted).
    var calls: Int? = nil
    /// Measured, never a prediction (G107).
    var elapsedMs: Int? = nil
    var pausedMs: Int? = nil
    var batchState: BatchState? = nil
    var stages: [Stage]? = nil
    var byOrigin: [String: Origin]? = nil
    /// Conversations parked in this run.
    var parked: Int? = nil
    var ownerPage: SleepOwnerPageCount? = nil
    var reserve: SleepReserveInfo? = nil
    var resumed: Bool? = nil

    init(id: String = "", frozen: Int = 0, batchSize: Int = 0, batch: Int = 0, batches: Int = 0, filed: Int = 0,
         requeued: Int = 0, skipped: Int = 0, active: Bool = false, finished: Bool = false, stop: Stop? = nil,
         arrivedSince: Int? = nil) {
        self.id = id; self.frozen = frozen; self.batchSize = batchSize; self.batch = batch; self.batches = batches
        self.filed = filed; self.requeued = requeued; self.skipped = skipped; self.active = active
        self.finished = finished; self.stop = stop; self.arrivedSince = arrivedSince
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func int(_ key: CodingKeys) -> Int { (try? c.decodeIfPresent(Int.self, forKey: key)) ?? 0 }
        func flag(_ key: CodingKeys) -> Bool { (try? c.decodeIfPresent(Bool.self, forKey: key)) ?? false }
        id = (try? c.decodeIfPresent(String.self, forKey: .id)) ?? ""
        frozen = int(.frozen); batchSize = int(.batchSize); batch = int(.batch); batches = int(.batches)
        filed = int(.filed); requeued = int(.requeued); skipped = int(.skipped)
        active = flag(.active); finished = flag(.finished)
        stop = try? c.decodeIfPresent(Stop.self, forKey: .stop)
        arrivedSince = try? c.decodeIfPresent(Int.self, forKey: .arrivedSince)
        func opt(_ key: CodingKeys) -> Int? { (try? c.decodeIfPresent(Int.self, forKey: key)) ?? nil }
        startedBy = (try? c.decodeIfPresent(String.self, forKey: .startedBy)) ?? nil
        firstRun = (try? c.decodeIfPresent(Bool.self, forKey: .firstRun)) ?? nil
        committedBatches = opt(.committedBatches); calls = opt(.calls)
        elapsedMs = opt(.elapsedMs); pausedMs = opt(.pausedMs); parked = opt(.parked)
        batchState = (try? c.decodeIfPresent(BatchState.self, forKey: .batchState)) ?? nil
        stages = (try? c.decodeIfPresent([Stage].self, forKey: .stages)) ?? nil
        byOrigin = (try? c.decodeIfPresent([String: Origin].self, forKey: .byOrigin)) ?? nil
        ownerPage = (try? c.decodeIfPresent(SleepOwnerPageCount.self, forKey: .ownerPage)) ?? nil
        reserve = (try? c.decodeIfPresent(SleepReserveInfo.self, forKey: .reserve)) ?? nil
        resumed = (try? c.decodeIfPresent(Bool.self, forKey: .resumed)) ?? nil
    }

    enum CodingKeys: String, CodingKey {
        case id, frozen, batchSize, batch, batches, filed, requeued, skipped, active, finished, stop, arrivedSince
        case startedBy, firstRun, committedBatches, calls, elapsedMs, pausedMs, batchState, stages, byOrigin
        case parked, ownerPage, reserve, resumed
    }
}

struct SleepTriggerResponse: Codable {
    let status: String
    let message: String
    let cycleId: String?
}

/// `POST /sleep/run/end` — `ended`, or `none` when there was no paused run.
struct SleepEndRunResponse: Codable {
    let status: String
    let message: String
}

/// `POST /sleep/cancel` — see `SleepCancelResponse` on the API side for the
/// full contract (idempotent, "not_running" | "cancelling", no 404/409).
struct SleepCancelResponse: Codable {
    let status: String
    let message: String
    let cycleId: String?
}

struct EpisodeQueueItem: Codable, Identifiable {
    let id: String
    let timestamp: String
    let source: String
    /// G9 origin — the harness-normalized id (`claude-code`, `chatgpt-export`,
    /// `telegram`, `pinterest`, …), used by the Sleep debt catch-up
    /// breakdown to group by the same identity the rest of the app's origin
    /// iconography keys on. `"unknown"` on an older backend that doesn't
    /// send it.
    let origin: String
    let title: String?
    let preview: String
    /// G125 R9 — body length in characters, for the Sleep page's book pile
    /// (a log-scale spine height). 0 on an older backend that predates this
    /// field, and for an episode whose body genuinely is empty.
    let chars: Int
    let processed: Bool
    /// Owner 2026-10-05 — what a click on the row copies (`episode_copy` on the backend): a page's link, a
    /// conversation's session id, a tab group's links, a folder file's path, else the episode id. Nil on an older
    /// backend, which copies the episode id.
    let copyKind: String?
    let copyValue: String?
    /// The day the row ends with: a captured conversation's last capture, else when it was added.
    let changedAt: String?
    /// Owner 2026-10-20 — a saved link's site key (a bookmark or saved post Sleep has not read yet): the row draws that
    /// site's own mark (`SavedLinkMark`), never the browser's. Nil for every other episode and from an older backend.
    let site: String?
    /// G212 — the device id that posted it (nil: this server, or an older backend), for the machines strip's queues.
    var device: String? = nil

    enum CodingKeys: String, CodingKey {
        case id, timestamp, source, origin, title, preview, chars, processed, copyKind, copyValue, changedAt, site
        case device
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        timestamp = try c.decode(String.self, forKey: .timestamp)
        source = try c.decode(String.self, forKey: .source)
        origin = try c.decodeIfPresent(String.self, forKey: .origin) ?? "unknown"
        title = try c.decodeIfPresent(String.self, forKey: .title)
        preview = try c.decode(String.self, forKey: .preview)
        chars = try c.decodeIfPresent(Int.self, forKey: .chars) ?? 0
        processed = try c.decode(Bool.self, forKey: .processed)
        copyKind = try c.decodeIfPresent(String.self, forKey: .copyKind)
        copyValue = try c.decodeIfPresent(String.self, forKey: .copyValue)
        changedAt = try c.decodeIfPresent(String.self, forKey: .changedAt)
        site = try c.decodeIfPresent(String.self, forKey: .site)
        device = try c.decodeIfPresent(String.self, forKey: .device)
    }
}

/// When Sleep runs on its own (G125 (4)). `mode` is the truth; `enabled` is a
/// WIRE convenience the backend always sends for an older reader of
/// `/status.nextSleepAt` (R6) — never this struct's own source of truth. A
/// naive `Codable` synthesis would try to assign a decoded `enabled` straight
/// into a stored property; there is none, so `init(from:)`/`encode(to:)` are
/// both hand-written below.
struct ScheduleConfig: Codable, Equatable {
    var mode: String          // manual | daily | interval | after_import
    var hour: Int
    var minute: Int
    var intervalHours: Int
    var enabled: Bool { mode != "manual" }
    /// Owner decision 2 (2026-10-16): while it runs on its own, why a scheduled run would have no engine it may use
    /// — the server's sentence, and the code the app words its fix from (`no_engine`, `plan_signed_out`,
    /// `plan_not_chosen`, `local_down`). Read only; never sent back.
    var warning: String? = nil
    var warningCode: String? = nil

    init(mode: String, hour: Int, minute: Int, intervalHours: Int = 6) {
        self.mode = mode; self.hour = hour; self.minute = minute; self.intervalHours = intervalHours
    }

    enum CodingKeys: String, CodingKey { case mode, enabled, hour, minute, intervalHours, warning, warningCode }

    /// The backend always sends `enabled` (R6), on every version — so it is
    /// read here ONLY to derive `mode` when `mode` itself is absent (a
    /// pre-G125 backend); once decoded, `mode` alone drives everything else.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let decodedEnabled = (try? c.decodeIfPresent(Bool.self, forKey: .enabled)) ?? false
        let decodedMode = (try? c.decodeIfPresent(String.self, forKey: .mode)) ?? nil   // flatten `String??`
        mode = decodedMode ?? (decodedEnabled ? "daily" : "manual")
        hour = (try? c.decodeIfPresent(Int.self, forKey: .hour)) ?? 3
        minute = (try? c.decodeIfPresent(Int.self, forKey: .minute)) ?? 0
        intervalHours = (try? c.decodeIfPresent(Int.self, forKey: .intervalHours)) ?? 6
        warning = (try? c.decodeIfPresent(String.self, forKey: .warning)) ?? nil
        warningCode = (try? c.decodeIfPresent(String.self, forKey: .warningCode)) ?? nil
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(mode, forKey: .mode)
        try c.encode(enabled, forKey: .enabled)
        try c.encode(hour, forKey: .hour)
        try c.encode(minute, forKey: .minute)
        try c.encode(intervalHours, forKey: .intervalHours)
    }
}

/// Mirror of the API's `SleepHistoryEntry` (camelCase on the wire) — one
/// consolidation as the Sleep page's history lists it (G125 R4). Counts are
/// parsed server-side; `durationMs` is joined from the `sleep_run` ledger and
/// is `nil` — never estimated — when no row exists (R5). Every field beyond
/// the original four is defaulted so an older backend still decodes.
struct SleepHistoryEntry: Codable, Identifiable, Equatable {
    let commitHash: String
    let date: String
    let message: String
    let filesChanged: [String]
    let engine: String?
    /// "sleep" | "decay" (the G85 split's `(decay)` commit) | "inbox".
    let kind: String
    let entitiesCreated: Int
    let entitiesUpdated: Int
    let episodes: Int
    let sessions: Int
    let authors: [String]
    let durationMs: Int?
    /// 2026-09-28 — what the cycle cost, one flat value; `nil` = not recorded (or an older backend).
    let usageSummary: CycleUsageSummary?
    /// Sleep page v5 — the run this commit was a batch of, and that run's own numbers (never summed from the
    /// visible page of history). `nil` for a plain cycle, an older commit, or an older backend.
    var drainId: String? = nil
    var batch: Int? = nil
    var batches: Int? = nil
    var run: SleepRunRef? = nil

    var id: String { commitHash }

    enum CodingKeys: String, CodingKey {
        case commitHash, date, message, filesChanged, engine, kind
        case entitiesCreated, entitiesUpdated, episodes, sessions, authors, durationMs, usageSummary
        case drainId, batch, batches, run
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        commitHash = try c.decode(String.self, forKey: .commitHash)
        date = try c.decode(String.self, forKey: .date)
        message = try c.decode(String.self, forKey: .message)
        filesChanged = try c.decodeIfPresent([String].self, forKey: .filesChanged) ?? []
        engine = try c.decodeIfPresent(String.self, forKey: .engine)
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "sleep"
        entitiesCreated = try c.decodeIfPresent(Int.self, forKey: .entitiesCreated) ?? 0
        entitiesUpdated = try c.decodeIfPresent(Int.self, forKey: .entitiesUpdated) ?? 0
        episodes = try c.decodeIfPresent(Int.self, forKey: .episodes) ?? 0
        sessions = try c.decodeIfPresent(Int.self, forKey: .sessions) ?? 0
        authors = try c.decodeIfPresent([String].self, forKey: .authors) ?? []
        durationMs = try c.decodeIfPresent(Int.self, forKey: .durationMs)
        usageSummary = (try? c.decodeIfPresent(CycleUsageSummary.self, forKey: .usageSummary)) ?? nil
        drainId = (try? c.decodeIfPresent(String.self, forKey: .drainId)) ?? nil
        batch = (try? c.decodeIfPresent(Int.self, forKey: .batch)) ?? nil
        batches = (try? c.decodeIfPresent(Int.self, forKey: .batches)) ?? nil
        run = (try? c.decodeIfPresent(SleepRunRef.self, forKey: .run)) ?? nil
    }
}

/// `GET /sleep/history/{commit}` — one manifest line (G125).
struct SleepCycleEntity: Codable, Identifiable, Equatable {
    let id: String
    let action: String
    let trigger: String
    let sourceEpisode: String?
}

/// `GET /sleep/history/{commit}` — what one cycle consolidated (G125). A
/// superset of `SleepHistoryEntry`'s fields (decoded independently here
/// rather than via inheritance — Swift has no struct subclassing) plus the
/// per-cycle detail: the resolved entity list, per-origin episode counts and
/// whether the entity list was capped server-side.
struct SleepCycleDetail: Codable, Identifiable, Equatable {
    let commitHash: String
    let date: String
    let message: String
    let filesChanged: [String]
    let engine: String?
    let kind: String
    let entitiesCreated: Int
    let entitiesUpdated: Int
    let episodes: Int
    let sessions: Int
    let authors: [String]
    let durationMs: Int?
    let entities: [SleepCycleEntity]
    let truncated: Bool
    let episodesByOrigin: [String: Int]
    let inboxChanges: Int
    /// 2026-09-28 — per-model usage; `nil` = not recorded (or an older backend).
    let usage: CycleUsage?
    let usageSummary: CycleUsageSummary?

    var id: String { commitHash }

    enum CodingKeys: String, CodingKey {
        case commitHash, date, message, filesChanged, engine, kind
        case entitiesCreated, entitiesUpdated, episodes, sessions, authors, durationMs
        case entities, truncated, episodesByOrigin, inboxChanges, usage, usageSummary
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        commitHash = try c.decode(String.self, forKey: .commitHash)
        date = try c.decode(String.self, forKey: .date)
        message = try c.decode(String.self, forKey: .message)
        filesChanged = try c.decodeIfPresent([String].self, forKey: .filesChanged) ?? []
        engine = try c.decodeIfPresent(String.self, forKey: .engine)
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "sleep"
        entitiesCreated = try c.decodeIfPresent(Int.self, forKey: .entitiesCreated) ?? 0
        entitiesUpdated = try c.decodeIfPresent(Int.self, forKey: .entitiesUpdated) ?? 0
        episodes = try c.decodeIfPresent(Int.self, forKey: .episodes) ?? 0
        sessions = try c.decodeIfPresent(Int.self, forKey: .sessions) ?? 0
        authors = try c.decodeIfPresent([String].self, forKey: .authors) ?? []
        durationMs = try c.decodeIfPresent(Int.self, forKey: .durationMs)
        entities = try c.decodeIfPresent([SleepCycleEntity].self, forKey: .entities) ?? []
        truncated = try c.decodeIfPresent(Bool.self, forKey: .truncated) ?? false
        episodesByOrigin = try c.decodeIfPresent([String: Int].self, forKey: .episodesByOrigin) ?? [:]
        inboxChanges = try c.decodeIfPresent(Int.self, forKey: .inboxChanges) ?? 0
        usage = (try? c.decodeIfPresent(CycleUsage.self, forKey: .usage)) ?? nil
        usageSummary = (try? c.decodeIfPresent(CycleUsageSummary.self, forKey: .usageSummary)) ?? nil
    }
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

/// `APIClient.syncBookmarks` was handed no bookmark bytes. The backend never
/// reads a browser's file itself (the `~/Library` rail), so there is nothing
/// to send — the call throws instead of posting a body the server would 422.
enum BookmarkSyncError: Error, LocalizedError, Equatable {
    case noData

    var errorDescription: String? { "No bookmark file was read, so there was nothing to sync" }
}

/// `APIClient.pointingAtNothing()`'s transport: every request fails at once with `cannotConnectToHost`, as a backend
/// that is not running would — no DNS lookup, no socket.
final class NoBackendURLProtocol: URLProtocol {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() { client?.urlProtocol(self, didFailWithError: URLError(.cannotConnectToHost)) }
    override func stopLoading() {}
}

actor APIClient {
    /// The app's one client. Under XCTest it is `pointingAtNothing()`: a unit test never reaches the backend running on
    /// this Mac, nor sends the person's token (#346 found `SleepViewModelTests` doing both through a default argument;
    /// every view model's defaults call `shared`). A test that needs answers injects a closure or builds its own
    /// `APIClient(session:)` over a fake transport.
    static let shared: APIClient = AppPasteboard.isRunningTests ? pointingAtNothing() : APIClient()

    /// The pages `fetchEntity` read, with their ETags (2026-10-28) — in memory only.
    private var entityCards = EntityCardCache()

    /// A client that reaches nothing: its session answers every request with "cannot connect" before a byte leaves the
    /// process (`NoBackendURLProtocol`), its base is `ServerConnection.unreachableBase` (a name that never resolves),
    /// and its home does not exist, so no token file is found. This Mac's connection shape (`.thisMac`) is kept so
    /// nothing that reads `connection` behaves as a server's client.
    static func pointingAtNothing() -> APIClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [NoBackendURLProtocol.self]
        config.urlCache = nil
        return APIClient(session: URLSession(configuration: config),
                         connection: ServerConnection(mode: .thisMac, source: .none),
                         runtime: .developer(codeRoot: URL(fileURLWithPath: "/nonexistent")),
                         baseOverride: ServerConnection.unreachableBase)
    }

    /// G182 — `http://127.0.0.1:<port>`, the port the backend was started on (`CICADA_PORT`, `cicada.port`, 8000) — or,
    /// G181 phase 3, the server the person chose (`ServerConnection`): the Store, its ETags and the event stream all
    /// ride this one base, so a server is this constant and nothing else. An invalid address is an unresolvable base,
    /// never this Mac's.
    nonisolated let baseURL: String
    /// Which backend this client talks to, decided at launch (`ServerConnection.current`).
    nonisolated let connection: ServerConnection
    /// Where this app keeps its state (`CicadaRuntime.cicadaHome`): the outbox and the hooks' spool live under it.
    let cicadaHome: URL
    /// G181 phase 3 — the readers' posts that could not reach the server wait here (server mode only).
    let outbox: ReaderOutbox
    /// G202 (D2) — each bank's id on this server, by the `X-Cicada-Bank` value that names it, learned from `/banks`:
    /// a write names the id too (server mode only), so a post waiting in the outbox is refused by any memory but its
    /// own, even one that shares its name.
    private var bankIds: [String: String] = [:]
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        return d
    }()

    /// Every request goes through this session, not `.shared` — it disables
    /// `URLCache` entirely (`urlCache = nil`) and forces
    /// `.reloadIgnoringLocalCacheData` at the configuration level, so no
    /// helper (get/post/put/delete/multipart uploads/`syncEventLines`) can
    /// accidentally replay a disk-persisted, process-independent cache entry
    /// — the bug `getConditional`'s old per-request `.reloadIgnoringLocalCacheData`
    /// only patched for itself. We already do our own conditional-GET
    /// caching (`etag`, `Snapshot`, `SnapshotCache`); `URLCache` must never
    /// also intercept these requests.
    private let session: URLSession

    /// `session` is an init parameter (default: the real, cache-disabled
    /// configuration below) purely so tests can hand in a
    /// `URLProtocol`-backed session instead of hitting a real backend on
    /// 127.0.0.1 — `APIClient.shared` always uses the default.
    /// `baseOverride` is `pointingAtNothing()`'s alone.
    init(session: URLSession? = nil, connection: ServerConnection = .current,
         runtime: CicadaRuntime = .current, baseOverride: String? = nil) {
        self.connection = connection
        self.cicadaHome = runtime.cicadaHome
        self.baseURL = baseOverride ?? connection.baseURL(local: runtime.backendURL)
        self.outbox = ReaderOutbox(folder: ReaderOutbox.folder(cicadaHome: runtime.cicadaHome))
        if let session {
            self.session = session
        } else {
            let config = URLSessionConfiguration.default
            config.urlCache = nil
            config.requestCachePolicy = .reloadIgnoringLocalCacheData
            // NB: deliberately NOT setting `timeoutIntervalForRequest` here. A
            // session-wide cap would also apply to the long-running writes
            // (`POST /ask` blocks on an LLM call; `/sources/sync-bookmarks`,
            // `/sources/poll-feeds`, `/conversations/upload`), where a client-side
            // timeout makes `Store.perform` roll back and toast "reverted" for
            // work the server actually completed. The cap belongs on the refresh
            // path only — see `refreshTimeout`.
            self.session = URLSession(configuration: config)
        }
    }

    /// Timeout for the *refresh* path only (`getConditional`, `fetchStatus`).
    ///
    /// A refresh request holds its domain's `Snapshot.isRefreshing` for as
    /// long as it runs, and `Store.refreshOne` coalesces into that flag — so a
    /// request parked on Foundation's 60 s default makes the app deaf to every
    /// version event for that domain for a full minute. These GETs are all
    /// small and idempotent, so capping them well below the default costs
    /// nothing and bounds the deaf window. Writes keep the 60 s default; the
    /// SSE stream sets its own 3600 (see `syncEventLines`).
    static let refreshTimeout: TimeInterval = 30

    /// Bearer token generated by the backend at `$CICADA_HOME/api_token`
    /// (see api/services/auth.py). Cached after the first successful read —
    /// re-reading the file on every request cost a disk hit per call. A *miss*
    /// is never cached: on first launch the file appears a moment after the
    /// backend boots, so caching nil would strand the app in 401s until
    /// restart. Any 401 clears the cache (`invalidateToken()`) so a rotated
    /// token is picked up on the next attempt.
    ///
    /// G181 phase 3: on a server the token is this device's own (`CICADA_API_TOKEN`, else `device_token`), never the
    /// master token; the cache is keyed by the file it came from, so a client built for one never hands out the other's.
    private nonisolated(unsafe) static var cachedToken: (key: String, token: String)?

    static func invalidateToken() { cachedToken = nil }

    /// Whether a unit test may read a token file at `file`: only inside the temporary directory, where tests build
    /// their own homes. The person's real home (`~/.cicada`, wherever `HOME` points) never is.
    static func testMayReadToken(at file: URL,
                                 temporaryDirectory: URL = FileManager.default.temporaryDirectory) -> Bool {
        let path = file.resolvingSymlinksInPath().standardizedFileURL.path
        let temp = temporaryDirectory.resolvingSymlinksInPath().standardizedFileURL.path
        return path.hasPrefix(temp.hasSuffix("/") ? temp : temp + "/")
    }

    static func loadToken(connection: ServerConnection, cicadaHome: URL) -> String? {
        let file = cicadaHome.appendingPathComponent(connection.isServer ? ServerConnection.deviceTokenFile : "api_token")
        // Under XCTest a token is read only from a test's own temporary folder — never the person's `~/.cicada` (a
        // client built with the default runtime points there), and never `CICADA_API_TOKEN` from the shell.
        if AppPasteboard.isRunningTests && !Self.testMayReadToken(at: file) { return nil }
        if let cachedToken, cachedToken.key == file.path { return cachedToken.token }
        let env = ProcessInfo.processInfo.environment
        if !AppPasteboard.isRunningTests, let t = env["CICADA_API_TOKEN"], !t.isEmpty {
            cachedToken = (file.path, t); return t
        }
        guard let raw = try? String(contentsOf: file, encoding: .utf8) else { return nil }
        let token = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !token.isEmpty else { return nil }
        cachedToken = (file.path, token)
        return token
    }

    private func makeRequest(_ path: String, method: String, json: Bool = true) -> URLRequest {
        var request = URLRequest(url: URL(string: "\(baseURL)\(path)")!)
        request.httpMethod = method
        if json { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        if let token = Self.loadToken(connection: connection, cicadaHome: cicadaHome) {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        // G183(d) — a write names the bank it started in; the server refuses it when that bank is no longer active.
        if let bank = BankScope.value(method: method) {
            request.setValue(bank, forHTTPHeaderField: BankScope.header)
            // G202 (D2): on a server, the bank's identity too — a name repeats across memories, an id does not.
            if connection.isServer, let id = bankIds[bank] {
                request.setValue(id, forHTTPHeaderField: BankScope.idHeader)
            }
        }
        return request
    }

    /// Learn each bank's id from a roster (G202). Server mode only; This Mac sends names as before.
    private func noteBankIds(_ roster: BanksResponse?) {
        guard connection.isServer, let roster else { return }
        for bank in roster.banks {
            guard let id = bank.serverId, !id.isEmpty,
                  let header = BankScope.value(method: "POST", origin: bank.name, onScreen: nil) else { continue }
            bankIds[header] = id
        }
    }

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

    /// `GET /banks` → all banks plus the active one.
    ///
    /// A 404 propagates. It used to be swallowed into an empty roster, but an
    /// empty roster is indistinguishable from a real one and every caller reads
    /// it as truth — `BanksViewModel.load()` treats a *missing* roster as its
    /// error path, so degrading turned an honest failure into a silently empty
    /// dropdown with no explanation.
    func fetchBanks() async throws -> BanksResponse {
        let roster: BanksResponse = try await get("/banks")
        noteBankIds(roster)
        return roster
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

    /// `POST /banks/demo` (G117) → one click, a populated synthetic bank
    /// (`api/services/demo_bank.py`), already ACTIVATED server-side. The
    /// echoed roster is what the first-run sheet's demo button hands to
    /// `store.refresh([.banks])`, which notices `active` moved and re-hydrates
    /// on its own (`Store.refresh`'s bank-switch fan-out) — no second
    /// activate call needed.
    @discardableResult
    func createDemoBank() async throws -> BanksResponse {
        // G181 phase 3 — a demo never reaches a server (`demo_guard`): it is a This Mac thing.
        if connection.isServer { throw ServerLinkError.demoStaysLocal }
        return try await post("/banks/demo")
    }

    /// `POST /banks/leave-demo` (G117 round 4, F-08) → the demo banner's way home: the server activates the real bank
    /// left most recently (`last_active_at`), or makes one, and echoes the roster — `createDemoBank`'s shape, so the
    /// caller hands it to `store.refresh([.banks])` the same way.
    @discardableResult
    func leaveDemo() async throws -> BanksResponse {
        try await post("/banks/leave-demo")
    }

    /// `POST /banks/{name}/activate` → switch the active bank; answers the roster as the server then has it. A body
    /// that will not decode is `nil`, never a failed switch — the server has already moved.
    func activateBank(name: String) async throws -> BanksResponse? {
        let data: Data = try await post("/banks/\(encodedBank(name))/activate")
        let roster = try? decoder.decode(BanksResponse.self, from: data)
        noteBankIds(roster)
        return roster
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

    // MARK: - Entities

    /// Legacy entity ids can contain `#`, `$`, parens, etc. — `#` silently
    /// truncates the URL into a fragment and other characters nil out
    /// `URL(string:)`, so the id must be percent-encoded as a path component.
    private func encodedID(_ id: String) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "#$&+,/:;=?@")
        return id.addingPercentEncoding(withAllowedCharacters: allowed) ?? id
    }

    /// `GET /entities/{id}`, revalidated with its ETag (2026-10-28): a page held from an earlier open is sent back as
    /// `If-None-Match` and a 304 hands back the held copy — the server answers from a few stats, never re-reading the
    /// page or its history. Not a Store domain: `EntityCardCache` holds it in memory, emptied on a bank switch.
    func fetchEntity(id: String) async throws -> Entity {
        let held = entityCards.held(id)
        do {
            let result: Conditional<Entity> = try await getConditional("/entities/\(encodedID(id))", etag: held?.etag)
            return try entityCards.settle(id, result, held: held)
        } catch APIError.httpError(404, let body) {
            entityCards.forget(id)
            throw APIError.httpError(404, body)
        }
    }

    /// A bank switch: the held pages belong to the bank they were read in (the server's ETag names the bank too).
    func resetEntityCards() {
        entityCards = EntityCardCache()
    }

    /// F4 — `GET /entities/{id}/raw`: the page verbatim, for the Source view and Copy when the card's payload left it
    /// out (`Entity.rawOmitted`). On demand only; never a Store domain.
    func fetchEntityRaw(id: String) async throws -> String {
        let response: EntityRaw = try await get("/entities/\(encodedID(id))/raw")
        return response.rawMarkdown
    }

    /// `PUT /entities/{id}/decay` (G66 §1.7) — the user's decay override.
    /// The backend writes the class plus its mapped numeric rate and commits as
    /// `Cicada-Author: user`, then returns the refreshed entity. Errors
    /// propagate so the picker can revert its optimistic selection.
    func setDecayClass(entityId: String, _ decayClass: DecayClass) async throws -> Entity {
        return try await put(
            "/entities/\(encodedID(entityId))/decay",
            body: ["decayClass": decayClass.rawValue]
        )
    }

    /// `GET /entities/{id}/logo`. Returns nil on 404 — "this entity has no
    /// logo" is an ordinary answer, not an error, and the caller draws a
    /// monogram instead.
    func fetchEntityLogo(id: String) async throws -> Data? {
        var request = makeRequest("/entities/\(encodedID(id))/logo", method: "GET", json: false)
        request.timeoutInterval = Self.refreshTimeout
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        if http.statusCode == 404 { return nil }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            throw APIError.httpError(http.statusCode, String(data: data, encoding: .utf8) ?? "Unknown error")
        }
        return data
    }

    /// C11 — `GET <path>` for a picture on this API (`/entities/{id}/picture?v=…`), with the bearer (plan R-PE6). nil on a
    /// 404 — "no picture" is an ordinary answer — and for any path that is not an entity picture.
    /// The one gate for a picture path on Cicada's own API: exactly what `PictureURL.parse` calls `.api` (an entity's
    /// picture or preview, a saved look's screenshot `/design/<id>/image`, a site capture's thumbnail). It used to
    /// accept `/entities/` alone, so every Looks screenshot answered "no picture" here, `PictureStore` remembered the
    /// miss, and the tile and the detail column drew their palette placeholder for good (looks v2).
    nonisolated static func isPicturePath(_ path: String) -> Bool {
        if case .api? = PictureURL.parse(path) { return true }
        return false
    }

    func fetchPictureBytes(path: String) async throws -> Data? {
        guard Self.isPicturePath(path) else { return nil }
        var request = makeRequest(path, method: "GET", json: false)
        request.timeoutInterval = Self.refreshTimeout
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        if http.statusCode == 404 { return nil }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            throw APIError.httpError(http.statusCode, String(data: data, encoding: .utf8) ?? "Unknown error")
        }
        return data
    }

    /// C11 — `POST /entities/{id}/picture`: bytes `PictureImport` already shrank, as multipart `file`.
    func setEntityPicture(entityId: String, data: Data, ext: String) async throws -> EntityPictureAnswer {
        var request = makeRequest("/entities/\(encodedID(entityId))/picture", method: "POST", json: false)
        let boundary = UUID().uuidString
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"picture.\(ext)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: \(ext == "png" ? "image/png" : "image/jpeg")\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body
        let (reply, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            throw APIError.httpError(http.statusCode, String(data: reply, encoding: .utf8) ?? "Unknown error")
        }
        return try decoder.decode(EntityPictureAnswer.self, from: reply)
    }

    /// A saved item's picture from a PDF the person chose: the backend renders page 1 (`POST /entities/{id}/picture/pdf`).
    func setEntityPictureFromPDF(entityId: String, data: Data) async throws -> EntityPictureAnswer {
        var request = makeRequest("/entities/\(encodedID(entityId))/picture/pdf", method: "POST", json: false)
        let boundary = UUID().uuidString
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"document.pdf\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: application/pdf\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body
        // The render runs in the backend before it answers: give it longer than a plain write.
        request.timeoutInterval = 60
        let (reply, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            throw APIError.httpError(http.statusCode, String(data: reply, encoding: .utf8) ?? "Unknown error")
        }
        return try decoder.decode(EntityPictureAnswer.self, from: reply)
    }

    /// C11 / F-12 — "Use initials instead" (plan R-PE4).
    func useEntityInitials(entityId: String) async throws -> EntityPictureAnswer {
        try await post("/entities/\(encodedID(entityId))/picture/initials")
    }

    /// C11 — back to what was detected.
    func clearEntityPicture(entityId: String) async throws -> EntityPictureAnswer {
        let data = try await delete("/entities/\(encodedID(entityId))/picture")
        return try decoder.decode(EntityPictureAnswer.self, from: data)
    }

    func fetchEntityHistory(id: String, includeDiff: Bool = false, skip: Int = 0) async throws -> [EntityHistoryEntry] {
        // FastAPI query params use the snake_case Python name (not the
        // camelCase body/response alias), so this is include_diff, not includeDiff.
        // #244: `skip` reads the changes older than the newest N.
        let query = (includeDiff ? ["include_diff=true"] : []) + (skip > 0 ? ["skip=\(skip)"] : [])
        let suffix = query.isEmpty ? "" : "?" + query.joined(separator: "&")
        return try await get("/entities/\(encodedID(id))/history\(suffix)")
    }

    /// Per-commit add/remove diff for one entity file (backlog A1). NOT BUILD-VERIFIED.
    /// The backend validates commitHash against ^[0-9a-fA-F]{7,40}$ and rejects
    /// anything else, but we still percent-encode it (like the id) for consistency
    /// and defense-in-depth against a malformed value in the path.
    func fetchEntityCommitDiff(id: String, commitHash: String) async throws -> EntityDiff {
        return try await get("/entities/\(encodedID(id))/history/\(encodedID(commitHash))/diff")
    }

    /// Ruling 48 part 14 / DR-77 (part B): one page of the History tab — each row with its filter bucket, time and
    /// summary — read only when the tab opens; `more` is the `X-History-More` header.
    func fetchEntityHistoryPage(id: String, skip: Int = 0, limit: Int = HistoryPager.pageSize)
        async throws -> (rows: [EntityHistoryEntry], more: Bool) {
        let request = makeRequest("/entities/\(encodedID(id))/history?summary=true&limit=\(limit)&skip=\(skip)",
                                  method: "GET", json: false)
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            throw APIError.httpError(http.statusCode, String(data: data, encoding: .utf8) ?? "Unknown error")
        }
        do {
            let rows = try decoder.decode([EntityHistoryEntry].self, from: data)
            return (rows, http.value(forHTTPHeaderField: "X-History-More") == "1")
        } catch {
            throw APIError.decodingError("\(error)")
        }
    }

    /// Ruling 48 part 6 (part B): what a place's map draws — read when the map draws, never on card open.
    func fetchPlace(id: String) async throws -> PlaceState {
        try await get("/entities/\(encodedID(id))/place")
    }

    /// The Mac's geocoder (or the person's click) found it: store it once. `by`: geocoder | person | none.
    func storeCoordinates(id: String, lat: Double?, lon: Double?, by: String) async throws -> PlaceState {
        var body: [String: Any] = ["by": by]
        if let lat { body["lat"] = lat }
        if let lon { body["lon"] = lon }
        return try await putData("/entities/\(encodedID(id))/coordinates",
                                 json: try JSONSerialization.data(withJSONObject: body))
    }

    /// The person takes the pin back; nothing places it again until they ask.
    func removeCoordinates(id: String) async throws -> PlaceState {
        let data = try await delete("/entities/\(encodedID(id))/coordinates")
        return try decoder.decode(PlaceState.self, from: data)
    }

    /// The app's background pass: public places it may resolve on its own.
    func fetchUnplacedPlaces(limit: Int = 20) async throws -> [UnplacedPlace] {
        try await get("/places/unplaced?limit=\(limit)")
    }

    /// `GET /entities/{id}/location` (issue #7) — the directory a location or
    /// directory entity declares (frontmatter `path:`, else a path in its body).
    /// Only `path` is filled: the backend never touches the folder, and
    /// `LocationLister` lists it on this Mac. Returns `nil` on a 404 so the
    /// detail card degrades quietly to just the description.
    func fetchLocationListing(id: String) async throws -> LocationListing? {
        do {
            return try await get("/entities/\(encodedID(id))/location")
        } catch APIError.httpError(404, _) {
            return nil
        }
    }

    /// `GET /entities/{id}/repos` (G9 companion) — the repos a project/directory page declares under `repos:`, and
    /// which device this Mac is. Declarations only: the backend never opens the folder; `GitRunner` does.
    func fetchEntityRepoDeclarations(entityId: String) async throws -> RepoDeclarationList {
        try await get("/entities/\(encodedID(entityId))/repos")
    }

    /// `POST /entities/{id}/repos/observed` — what `GitRunner` saw in each declared repo, parsed by the backend's
    /// one parser into the card's `RepoContext`s (and kept as the last look `_state.md` names).
    func postObservedRepos(entityId: String, _ observations: [GitRunner.Observation]) async throws -> [RepoContext] {
        let list: RepoContextList = try await post("/entities/\(encodedID(entityId))/repos/observed",
                                                   body: ["repos": observations.map(\.json)])
        return list.repos
    }

    // MARK: - Fact sources (G61)

    func fetchEntitySources(entityId: String) async throws -> [EntitySource] {
        let payload: EntitySourceList = try await get("/entities/\(encodedID(entityId))/sources")
        return payload.sources
    }

    func addEntitySource(entityId: String, ref: String, predicate: String? = nil) async throws -> [EntitySource] {
        var body: [String: Any] = ["ref": ref]
        if let predicate { body["predicate"] = predicate }
        let data = try await post("/entities/\(encodedID(entityId))/sources", body: body)
        return try JSONDecoder().decode(EntitySourceList.self, from: data).sources
    }

    /// G61 S3-a — `POST /entities/{id}/sources/change`: one edit, keyed by the entry's current `(ref, predicate)`.
    func changeEntitySource(entityId: String, source: EntitySource, change: SourceChange) async throws -> [EntitySource] {
        let data = try await post("/entities/\(encodedID(entityId))/sources/change", body: change.body(for: source))
        return try JSONDecoder().decode(EntitySourceList.self, from: data).sources
    }

    func deleteEntitySource(entityId: String, index: Int) async throws -> [EntitySource] {
        let data = try await delete("/entities/\(encodedID(entityId))/sources/\(index)")
        return try JSONDecoder().decode(EntitySourceList.self, from: data).sources
    }

    // MARK: - Claims (CPCG claim layer)

    /// `GET /entities/{id}/claims` — the subject's claims. By default only
    /// currently-valid claims; `includeSuperseded` lifts the filter. Returns
    /// `[]` on a 404 so the perspective tab / claim chips degrade gracefully
    /// against a backend that hasn't shipped the endpoint yet.
    /// `predicates` — only the subject's claims with one of these predicates (a person card's facts): a few rows read
    /// when the card opens, instead of every belief on an owner-sized page.
    func fetchClaims(subject: String, includeSuperseded: Bool = false, predicates: [String] = []) async throws -> [Claim] {
        var items: [String] = includeSuperseded ? ["include_superseded=true"] : []
        items += predicates.map { "predicate=\($0.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? $0)" }
        let q = items.isEmpty ? "" : "?" + items.joined(separator: "&")
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

    /// `GET /contributors/commits?author=&limit=` (G67) — one author's recent
    /// commits, for the Contributors drill-down. `author` is a QUERY value
    /// because model ids contain slashes (`anthropic/claude-opus-4`); it is
    /// percent-encoded so the slash never splits the path. On demand only — no
    /// Store domain, no ETag.
    ///
    /// THROWS on failure. It used to swallow every error into `[]`, which the
    /// drill-down then cached and rendered as "No commits found for this
    /// author" — a false claim about who wrote memory, sticky for the life of
    /// the view, and triggered by something as ordinary as collapsing the row
    /// mid-flight (a cancelled task). The one exception is a 404, which means
    /// the backend predates this endpoint rather than that the fetch failed:
    /// there is genuinely no drill-down to show, and no retry would help.
    func fetchContributorCommits(author: String, limit: Int = 50) async throws -> [ContributorCommit] {
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "&+=?/#")
        let a = author.addingPercentEncoding(withAllowedCharacters: allowed) ?? author
        do {
            let resp: ContributorCommitsResponse = try await get(
                "/contributors/commits?author=\(a)&limit=\(limit)"
            )
            return resp.commits
        } catch APIError.httpError(404, _) {
            return []
        }
    }

    /// G124 R14 — one contributor's memory-write calendar. On demand, like the
    /// commit drill-down: no Store domain, no ETag on the app side. Same
    /// author encoding as `fetchContributorCommits` so a `+` in a model id
    /// never decodes to a space server-side.
    func fetchContributorCalendar(author: String, weeks: Int = 53) async throws -> ContributorCalendar {
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "&+=?/#")
        let a = author.addingPercentEncoding(withAllowedCharacters: allowed) ?? author
        return try await get("/contributors/calendar?author=\(a)&weeks=\(weeks)")
    }

    /// G124 — most-written / most-read entity pages, counts only.
    func fetchTopEntities(limit: Int = 10, range: String = "all") async throws -> TopEntities {
        try await get("/contributors/top-entities?limit=\(limit)&range=\(range)")
    }

    /// G124 R11 — the app opened an entity card. Fire-and-forget: a ledger
    /// miss, a 404 (the page vanished between click and open) or an old
    /// backend must never surface on the card, so every error is swallowed.
    /// The body is ids-only — an entity id and the surface enum, never a
    /// title or body text — by the telemetry rail on the G124 row.
    func recordEntityRead(id: String) async {
        _ = try? await post("/entities/\(id)/read", body: ["surface": "app"]) as Data
    }

    // MARK: - Conversations (G48)

    /// `GET /conversations/recent?limit=&harness=&origin=` — conversations
    /// that wrote to memory, newest write first. On demand only, like
    /// `/contributors/commits` — no Store domain, no ETag. A 404 means the
    /// backend predates this endpoint, not that the fetch failed, so it
    /// degrades to an empty list rather than throwing.
    ///
    /// G124 R5: the filters are applied by the backend BEFORE its 200-row cap,
    /// so a harness's page never loses an older conversation to the cap.
    /// `harness: "unknown"` travels literally — the backend matches it to an
    /// empty harness. Values are percent-encoded the way
    /// `fetchContributorCommits` encodes `author`.
    ///
    /// G136 R-SU22: `query` becomes `q=`, a title filter the backend also
    /// applies before the cap (G136 R17) — how a source's conversation list
    /// finds a title older than its newest 200. Sent only when non-blank.
    func fetchRecentConversations(limit: Int = 20, harness: String? = nil, origin: String? = nil,
                                  query: String? = nil) async throws -> [ConversationSummary] {
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "&+=?/#")
        var path = "/conversations/recent?limit=\(limit)"
        if let harness {
            path += "&harness=\(harness.addingPercentEncoding(withAllowedCharacters: allowed) ?? harness)"
        }
        if let origin {
            path += "&origin=\(origin.addingPercentEncoding(withAllowedCharacters: allowed) ?? origin)"
        }
        if let query, !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            path += "&q=\(query.addingPercentEncoding(withAllowedCharacters: allowed) ?? query)"
        }
        do {
            return try await get(path)
        } catch APIError.httpError(404, _) {
            return []
        }
    }

    /// `GET /conversations/{id}` — one conversation by exact id, resolved
    /// against the WHOLE bank rather than the capped `/recent` page. `nil`
    /// means the backend genuinely has no episode carrying that id (404) — or
    /// predates the route, which is indistinguishable and equally "can't show
    /// it". Never throws on a 404, so the caller can say something honest.
    func fetchConversation(id: String) async throws -> ConversationSummary? {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        let encoded = id.addingPercentEncoding(withAllowedCharacters: allowed) ?? id
        do {
            return try await get("/conversations/\(encoded)")
        } catch APIError.httpError(404, _) {
            return nil
        }
    }

    /// `POST /conversations/{id}/resume` — validate a conversation and hand
    /// back a launch descriptor (G48 §5). 400 (not a resumable id), 404
    /// (unknown conversation) and 409 (transcript retention-cleaned) all
    /// propagate as `APIError.httpError` for the view model to interpret.
    func resumeConversation(id: String) async throws -> ResumeDescriptor {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        let encoded = id.addingPercentEncoding(withAllowedCharacters: allowed) ?? id
        return try await post("/conversations/\(encoded)/resume")
    }

    // MARK: - Connections (G50)

    func fetchConnections(fresh: Bool = false) async throws -> [ConnectionStatus] {
        let resp: ConnectionsResponse = try await get("/connections\(fresh ? "?fresh=true" : "")")
        return resp.connections
    }

    /// Fetch a single connection's status (`GET /connections/{id}`). Used by
    /// terminal-login polling so it checks only the one connection instead of
    /// sweeping all six on every tick.
    func fetchConnection(_ id: String, fresh: Bool = false) async throws -> ConnectionStatus {
        try await get("/connections/\(id)\(fresh ? "?fresh=true" : "")")
    }

    func beginLogin(_ id: String) async throws -> LoginSession {
        try await post("/connections/\(id)/login")
    }

    func loginState(_ id: String, sessionId: String) async throws -> LoginSession {
        try await get("/connections/\(id)/login/\(sessionId)")
    }

    func logout(_ id: String) async throws -> ConnectionStatus {
        try await post("/connections/\(id)/logout")
    }

    func setKey(_ id: String, key: String) async throws -> ConnectionStatus {
        try await put("/connections/\(id)/key", body: ["key": key])
    }

    func removeKey(_ id: String) async throws -> ConnectionStatus {
        let data = try await delete("/connections/\(id)/key")
        return try decoder.decode(ConnectionStatus.self, from: data)
    }

    func setTier(_ id: String, tier: String?) async throws -> ConnectionStatus {
        try await put("/connections/\(id)/prefs", body: ["tier": tier ?? NSNull()])
    }

    /// G74(a) — already matches `SyncAPI.setUseForSleep`'s signature exactly,
    /// so (like `subscribeFeed` etc. below) it satisfies the protocol from
    /// this declaration directly; no separate conformance forwarder.
    func setUseForSleep(_ id: String, on: Bool) async throws -> ConnectionStatus {
        try await put("/connections/\(id)/prefs", body: ["useForSleep": on])
    }

    // MARK: - Saved-content connectors (G71)

    func fetchConnectors() async throws -> [ConnectorStatus] {
        let response: ConnectorsResponse = try await get("/sources/connectors")
        return response.connectors
    }

    func saveConnectorCredentials(
        _ id: String, fields: [String: String]
    ) async throws -> ConnectorStatus {
        try await put("/sources/connectors/\(id)/credentials", body: ["fields": fields])
    }

    /// `delete(_:)` returns raw `Data` (mirrors `removeKey`'s DELETE-then-decode
    /// pattern) — there is no generic `delete<T: Decodable>` helper on this actor.
    func forgetConnector(_ id: String) async throws -> ConnectorStatus {
        let data = try await delete("/sources/connectors/\(id)/credentials")
        return try decoder.decode(ConnectorStatus.self, from: data)
    }

    func authorizeConnector(_ id: String) async throws -> ConnectorAuthorizeResponse {
        try await post("/sources/connectors/\(id)/authorize")
    }

    func syncConnector(_ id: String) async throws -> ConnectorSyncResult {
        try await post("/sources/connectors/\(id)/sync")
    }

    // MARK: - Consumption (G51)
    //
    // Plain (non-conditional) fetches for a range the Store's default
    // "month" bundle doesn't cover — `UsageViewModel.loadRange()` calls these
    // directly, the same way `ConnectionsViewModel` bypasses the Store for a
    // `fresh: true` probe. The Store's own default-view fetch is
    // `fetchConsumption(etag:current:)` below, in the `SyncAPI` conformance.

    func fetchConsumptionSummary(range: String) async throws -> ConsumptionSummary {
        try await get("/consumption/summary?range=\(range)")
    }

    func fetchConsumptionCalendar(weeks: Int = 53) async throws -> ConsumptionCalendar {
        try await get("/consumption/calendar?weeks=\(weeks)")
    }

    func fetchConsumptionStats(range: String) async throws -> ConsumptionStats {
        try await get("/consumption/stats?range=\(range)")
    }

    func fetchConsumptionConnections(range: String) async throws -> ConsumptionConnections {
        try await get("/consumption/connections?range=\(range)")
    }

    func fetchHarnessStats() async throws -> HarnessStats {
        try await get("/consumption/harness")
    }

    func fetchConsumptionFeedback(range: String) async throws -> ConsumptionFeedback {
        try await get("/consumption/feedback?range=\(range)")
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
        optionKey: String? = nil,
        remindDays: Int? = nil,
        mergeTarget: String? = nil,
        mergeSurvivor: String? = nil,
        quote: String? = nil,
        relayedBy: String? = nil,
        sessionId: String? = nil
    ) async throws {
        var body: [String: Any] = ["action": action]
        // Ruling 48 (8): the person's words the catch-up read this answer from, kept as the answer's evidence.
        if let quote, !quote.isEmpty { body["quote"] = quote }
        if let relayedBy { body["relayedBy"] = relayedBy }
        if let sessionId { body["sessionId"] = sessionId }
        if let answer { body["answer"] = answer }
        if let optionKey { body["optionKey"] = optionKey }
        if let remindDays { body["remindDays"] = remindDays }
        if let mergeTarget { body["mergeTarget"] = mergeTarget }
        if let mergeSurvivor { body["mergeSurvivor"] = mergeSurvivor }
        try await post("/inbox/\(id)/resolve", body: body)
    }

    /// Ruling 48 (8) — one turn of the catch-up chat: the person's own words about `itemId`, answered on their chosen
    /// engine (`POST /inbox/catchup/turn`). Writes nothing; a reading is applied through `resolveInboxItem`.
    func catchupTurn(itemId: String, message: String, history: [CatchupLine], upcoming: [String]) async throws
        -> CatchupTurnReply {
        try await post("/inbox/catchup/turn", body: [
            "itemId": itemId, "message": message, "upcoming": upcoming,
            "history": history.compactMap { line in line.wire.map { ["who": $0.who, "text": $0.text] } },
        ])
    }

    /// Ruling 48 (8) — the chat kept as one episode per catch-up session (`POST /inbox/catchup/record`).
    func catchupRecord(sessionId: String, lines: [CatchupLine]) async throws {
        let iso = ISO8601DateFormatter()
        let turns: [[String: Any]] = lines.compactMap { line in
            line.wire.map { ["who": $0.who, "text": $0.text, "at": iso.string(from: line.at)] }
        }
        try await post("/inbox/catchup/record", body: ["sessionId": sessionId, "turns": turns])
    }

    /// G61 "Where to check" (#422) — one row of the grouped review answered: `yes` takes that link on its page, `no`
    /// removes it (remembered, never proposed again). The item keeps the rows not answered.
    func resolveWhereToCheckRow(id: String, row: String, take: Bool) async throws {
        try await post("/inbox/\(encodedID(id))/resolve",
                       body: ["action": take ? "resolve" : "dismiss", "optionKey": take ? "yes" : "no", "row": row])
    }

    /// Owner ruling 2026-10-16 — "Settled by a check": the questions a web lookup or the person's agent settled
    /// (`GET /inbox/settled`). Not a Store domain: fetched when the Inbox opens and after an undo (`SettledChecks`).
    func fetchSettledChecks() async throws -> [SettledCheck] {
        try await get("/inbox/settled")
    }

    /// The one-tap undo (`POST /inbox/settled/{id}/undo`): the check's claim is withdrawn and the question returns.
    func undoSettledCheck(id: String) async throws {
        try await post("/inbox/settled/\(encodedID(id))/undo")
    }

    // MARK: - Status (menu-bar tamagotchi)

    /// Fetch the aggregate status snapshot (`GET /status`). The endpoint is live
    /// (wave 1); a `StatusSnapshot` decodes straight from the nested
    /// sleep/inbox/episodes wire shape.
    /// Refresh-path GET: capped like `getConditional`, because `refreshStatus`
    /// holds `status.isRefreshing` for the duration and coalesces behind it.
    func fetchStatus() async throws -> StatusSnapshot {
        return try await get("/status", timeout: Self.refreshTimeout)
    }

    // MARK: - Health (liveness probe; also the memory-root source of truth)

    /// Fetch `GET /healthz`. Open, but its paths and counts answer only a caller holding the token (owner decision 3,
    /// 2026-10-16) — this request carries it, so `memoryRoot` is there once the token file exists. Used by `ConnectView` to read the backend's OWN
    /// configured `memoryRoot` instead of re-deriving one locally — the two
    /// can otherwise disagree depending on install layout (G88 follow-up).
    /// Capped like the refresh path: it's retried with backoff while the
    /// backend comes up, so one attempt must never park for a full minute.
    func fetchHealth() async throws -> HealthSnapshot {
        return try await get("/healthz", timeout: Self.refreshTimeout)
    }

    // MARK: - Sources (media / bookmark ingestion — ships in a later wave)

    /// Post a single URL to the sources ingest endpoint. A 404 means the wave-3
    /// endpoint isn't merged yet; callers surface a friendly "coming soon".
    func saveSource(url: String) async throws {
        try await post("/sources/save", body: ["url": url])
    }

    /// Upload a single source file (bookmarks HTML/JSON, Takeout) to
    /// `POST /sources/upload`. Multipart, same envelope as conversation upload.
    ///
    /// `includeHistory` mirrors `previewSource`'s flag (G71 fix round 1, H2):
    /// Confirm must carry whatever toggle state the preview was shown under,
    /// or the real import's counts can silently disagree with what the
    /// preview promised.
    func uploadSource(fileURL: URL, includeHistory: Bool = false) async throws -> UploadResponse {
        let query = includeHistory ? "?include_history=true" : ""
        return try await uploadMultipart(path: "/sources/upload" + query, fileURL: fileURL)
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

    /// Keyless bookmark sync (`POST /sources/sync-bookmarks`). The app always
    /// passes the bytes it read itself (R1 — `BrowserFileReader`): the
    /// backend never reads a browser's file and answers 422 without bookmark
    /// data, so a call with neither file throws `BookmarkSyncError.noData`
    /// before any request is sent. `folders` (R5) narrows the sync to those
    /// folder-path prefixes; nil sends no key and is byte-identical to the
    /// pre-existing everything sync. The dedup diff is the same
    /// `url_index.json` hash check every other source path uses, so
    /// already-saved bookmarks come back as `skipped`, not re-ingested.
    @discardableResult
    func syncBookmarks(chromeData: Data?, safariData: Data?,
                       folders: [String]?) async throws -> BookmarkSyncResult {
        var body: [String: Any] = [:]
        if let chromeData, !chromeData.isEmpty { body["chromeDataB64"] = chromeData.base64EncodedString() }
        if let safariData, !safariData.isEmpty { body["safariDataB64"] = safariData.base64EncodedString() }
        guard !body.isEmpty else { throw BookmarkSyncError.noData }
        if let folders { body["folders"] = folders }
        return try await post("/sources/sync-bookmarks", body: body)
    }

    /// `POST /sources/sync-bookmarks` with `chromium` (round 4, C9): one Chromium-family browser's default-profile file,
    /// read by the app (the backend never opens a profile).
    @discardableResult
    func syncChromiumBookmarks(browser: String, data: Data) async throws -> BookmarkSyncResult {
        try await post("/sources/sync-bookmarks",
                       body: ["chromium": [["browser": browser, "dataB64": data.base64EncodedString()]]])
    }

    /// G191 live — the early look (`POST /sources/sync-bookmarks/fresh`): read-only, never a 409 for a sync running.
    func freshBookmarks(_ bytes: BookmarkBytes) async throws -> BookmarkSyncResult {
        try await post("/sources/sync-bookmarks/fresh", body: bytes.body)
    }

    /// G191 — the one-tap answers to "What made you save this?" (`GET /sources/saved-why/options`).
    func savedWhyOptions() async throws -> SavedWhyOptions {
        try await get("/sources/saved-why/options")
    }

    /// G191 v7 — the installed search model's similarity of each bank reason to this link (`basis: none` without it;
    /// the backend never downloads the model for this). The title and link are never logged.
    func savedWhySuggest(url: String, title: String) async throws -> SavedWhyModelScores {
        try await post("/sources/saved-why/suggest", body: ["url": url, "title": title])
    }

    /// G191 — the person's answer, attached by the backend to that bookmark's episode (`POST /sources/saved-why`).
    func saveWhy(url: String, answer: SavedWhyAnswer, at: Date, addedAt: String?) async throws {
        var body = answer.body
        body["url"] = url
        body["at"] = ISO8601DateFormatter().string(from: at)
        if let addedAt { body["addedAt"] = addedAt }
        try await post("/sources/saved-why", body: body)
    }

    /// G191 v3 — the person changes one answer (`PUT /sources/saved-why`), named by when it was given.
    func editSavedWhy(url: String, at: String, answer: SavedWhyAnswer) async throws -> SavedWhyReply {
        var body = answer.body
        body["url"] = url
        body["at"] = at
        return try await put("/sources/saved-why", body: body)
    }

    /// G191 v3 — the bookmark page's write: an edit when `at` names an answer, else a new one.
    func writeSavedWhy(url: String, at: String?, answer: SavedWhyAnswer) async throws -> SavedWhyReply {
        if let at { return try await editSavedWhy(url: url, at: at, answer: answer) }
        return try await addSavedWhy(url: url, answer: answer)
    }

    /// G191 v3 — a reason added from the bookmark's page (`POST /sources/saved-why`), answered now.
    func addSavedWhy(url: String, answer: SavedWhyAnswer) async throws -> SavedWhyReply {
        var body = answer.body
        body["url"] = url
        body["at"] = ISO8601DateFormatter().string(from: Date())
        return try await post("/sources/saved-why", body: body)
    }

    /// G191 v3 — forget a bookmark in Cicada (`POST /sources/bookmarks/remove`): the page archived, never deleted.
    func removeBookmark(url: String) async throws {
        let _: BookmarkRemoveReply = try await post("/sources/bookmarks/remove", body: ["url": url])
    }

    /// `POST /sources/sync-safari-tabs` — CloudTabs.db bytes the app read,
    /// plus the WAL sidecar when one exists (R2) and an exact-name device
    /// filter (nil = every device).
    func syncSafariTabs(db: Data, wal: Data?, devices: [String]?) async throws -> SafariTabsSyncResult {
        var body: [String: Any] = ["safariTabsDbB64": db.base64EncodedString()]
        if let wal { body["safariTabsWalB64"] = wal.base64EncodedString() }
        if let devices { body["devices"] = devices }
        return try await post("/sources/sync-safari-tabs", body: body)
    }

    /// One-way Apple Notes sync (`POST /sources/sync-notes`): the dump the APP read
    /// (`AppleNotesReader`, the `~/Library` rail), parsed and staged by the backend,
    /// which never runs `osascript` itself.
    @discardableResult
    func syncNotes(dump: String) async throws -> NoteSyncResult {
        return try await post("/sources/sync-notes", body: ["notesDump": dump])
    }

    // MARK: - Local sources (G133 / G134)

    /// `GET /sources/folders` — the active memory's watched folders.
    func fetchFolders() async throws -> [FolderRegistration] {
        let response: FolderListResponse = try await get("/sources/folders")
        return response.folders
    }

    /// `POST /sources/folders` — register (or re-pick) a folder; the backend
    /// stamps the device and anchors the project by name (R-LS9, R-LS13).
    func registerFolder(label: String, path: String, projectName: String,
                        authorship: [FolderAuthorshipRule]) async throws -> FolderRegistration {
        try await post("/sources/folders", body: [
            "label": label, "path": path, "projectName": projectName,
            "authorship": authorship.map { ["glob": $0.glob, "authorship": $0.authorship] },
        ])
    }

    func updateFolder(id: String, authorship: [FolderAuthorshipRule]) async throws -> FolderRegistration {
        try await put("/sources/folders/\(encodedID(id))", body: [
            "authorship": authorship.map { ["glob": $0.glob, "authorship": $0.authorship] },
        ])
    }

    func removeFolder(id: String) async throws {
        _ = try await delete("/sources/folders/\(encodedID(id))")
    }

    /// `POST /sources/folders/{id}/sync` — file bytes as base64 (R-LS8).
    func syncFolder(id: String, files: [FolderUpload], deleted: [String], preview: Bool,
                    resolve: Bool) async throws -> FolderSyncResult {
        let body: [String: Any] = [
            "files": files.map { ["relpath": $0.relpath, "mtime": $0.mtime, "sha256": $0.sha256,
                                  "contentB64": $0.data.base64EncodedString()] },
            "deleted": deleted,
        ]
        return try await post("/sources/folders/\(encodedID(id))/sync?preview=\(preview)&resolve=\(resolve)", body: body)
    }

    /// Ruling 43: the agents' own memory notes switch, per memory.
    func fetchAgentMemorySettings() async throws -> AgentMemorySettings {
        try await get("/capture/agent-memory/settings")
    }

    func saveAgentMemorySettings(enabled: Bool) async throws -> AgentMemorySettings {
        try await put("/capture/agent-memory/settings", body: ["enabled": enabled])
    }

    func fetchWisprSettings() async throws -> WisprFlowSettings {
        try await get("/capture/local-source/wispr-flow/settings")
    }

    func saveWisprSettings(_ settings: WisprFlowSettings) async throws -> WisprFlowSettings {
        try await put("/capture/local-source/wispr-flow/settings", body: [
            "enabled": settings.enabled, "includeDictation": settings.includeDictation,
            "ownerSpeakerNames": settings.ownerSpeakerNames,
        ])
    }

    /// `POST /capture/local-source/wispr-flow` — a projection already serialised
    /// off the main actor by `WisprFlowReader`, so only `Data` crosses into the actor.
    func postWisprFlow(_ json: Data) async throws -> WisprFlowSyncResult {
        try await postData("/capture/local-source/wispr-flow", json: json)
    }

    /// `POST /sources/calendar-local/sync` (round-4 D2, C6) — the Calendar app's events in the window, read by the
    /// app through EventKit (`CalendarReader`); the backend stages, scrubs and tombstones them like any source.
    func syncLocalCalendar(_ payload: CalendarSyncPayload) async throws -> CalendarSyncResult {
        try await postData("/sources/calendar-local/sync", json: try JSONEncoder().encode(payload))
    }

    /// G219: `POST /sources/reminders-local/sync` — the ticked lists' open reminders plus those completed in the last
    /// 90 days, read by the app through EventKit (`RemindersReader`); the backend stages, scrubs and tombstones them.
    func syncLocalReminders(_ payload: RemindersSyncPayload) async throws -> RemindersSyncResult {
        try await postData("/sources/reminders-local/sync", json: try JSONEncoder().encode(payload))
    }

    /// G154: the whole address book, as names and which facts each card holds (never a value).
    func syncLocalContacts(_ payload: ContactsSyncPayload) async throws -> ContactsSyncResult {
        try await postData("/sources/contacts-local/sync", json: try JSONEncoder().encode(payload))
    }

    /// Owner ruling 2026-10-20 (review of #391): `DELETE /sources/contacts-local/waiting` — Contacts was stopped, so the
    /// cards waiting outside every bank for a first mention are deleted, app-wide.
    func forgetWaitingContacts(connection: String?) async throws {
        let query = connection.flatMap { $0.addingPercentEncoding(withAllowedCharacters: .alphanumerics) }
            .map { "?connection=\($0)" } ?? ""
        try await delete("/sources/contacts-local/waiting" + query)
    }

    /// `DELETE /sources/linkedin-connections` — forget this memory's kept LinkedIn export; returns how many were kept.
    func forgetLinkedInConnections() async throws -> Int {
        let data = try await delete("/sources/linkedin-connections")
        return (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["forgotten"] as? Int ?? 0
    }

    /// Round 4 (G160): one browser profile's open tab groups, read by the app from Chrome's session file.
    func syncTabGroups(_ payload: TabGroupsPayload) async throws -> TabGroupsSyncResult {
        try await postData("/sources/tab-groups/sync", json: try JSONEncoder().encode(payload))
    }

    /// G71 (2026-10-16): the YouTube visits read from Chrome's History — one day episode per day on the backend.
    func syncWatchHistory(_ payload: WatchHistoryPayload) async throws -> WatchHistorySyncResult {
        try await postData("/sources/watch-history/sync", json: try JSONEncoder().encode(payload))
    }

    // MARK: - Activity traces (G218)

    /// Every traces call goes to This Mac's own backend only (`TraceBackendGate`): a client Mac's traces never leave it.
    private func traceGate() throws {
        guard TraceBackendGate.allows(connection) else { throw TraceBackendError.notThisMac }
    }

    func traceSettings() async throws -> TraceSettingsAnswer {
        try traceGate()
        return try await get("/sources/traces/settings")
    }

    func traceTurnOn(consentVersion: Int, displayedVersion: Int) async throws -> TraceSettingsAnswer {
        try traceGate()
        return try await post("/sources/traces/on",
                              body: ["consent_version": consentVersion, "displayed_version": displayedVersion])
    }

    func traceTurnOff() async throws -> TraceSettingsAnswer {
        try traceGate()
        return try await post("/sources/traces/off")
    }

    func traceUpdate(_ patch: [String: TracePatchValue]) async throws -> TraceSettingsAnswer {
        try traceGate()
        return try await putData("/sources/traces/settings", json: try JSONEncoder().encode(patch))
    }

    func tracePause(until: String?) async throws -> TraceSettingsAnswer {
        try traceGate()
        return try await postData("/sources/traces/pause", json: try JSONEncoder().encode(["until": until]))
    }

    func traceSync(_ spans: [TraceSpan]) async throws -> TraceSyncResult {
        try traceGate()
        return try await postData("/sources/traces/sync", json: try JSONEncoder().encode(["spans": spans]))
    }

    func traceAddFrame(_ frame: TraceFramePost) async throws {
        try traceGate()
        struct Kept: Decodable { let id: String }
        let _: Kept = try await postData("/sources/traces/frames", json: try JSONEncoder().encode(frame))
    }

    func traceTimeline(day: String) async throws -> TraceTimeline {
        try traceGate()
        return try await get("/sources/traces/timeline?day=\(day)")
    }

    func traceSearch(_ query: String) async throws -> [TraceSearchHit] {
        try traceGate()
        struct Hits: Decodable { let hits: [TraceSearchHit] }
        let answer: Hits = try await postData("/sources/traces/search", json: try JSONEncoder().encode(["query": query]))
        return answer.hits
    }

    func traceFrameImage(id: String) async throws -> Data {
        try traceGate()
        let request = makeRequest("/sources/traces/frames/\(id)", method: "GET", json: false)
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        guard (200...299).contains(http.statusCode) else {
            throw APIError.httpError(http.statusCode, String(data: data, encoding: .utf8) ?? "")
        }
        return data
    }

    func traceFrameText(id: String) async throws -> TraceFrameText {
        try traceGate()
        return try await get("/sources/traces/frames/\(id)/text")
    }

    func traceForget(minutes: Int) async throws {
        try traceGate()
        _ = try await post("/sources/traces/forget", body: ["minutes": minutes]) as Data
    }

    func traceWipe() async throws -> TraceSettingsAnswer {
        try traceGate()
        return try await post("/sources/traces/wipe", body: ["confirm": true])
    }

    func traceDayCards() async throws -> [TraceDayCard] {
        try traceGate()
        struct Days: Decodable { let days: [TraceDayCard] }
        let answer: Days = try await get("/sources/traces/day-cards")
        return answer.days
    }

    func traceDelete(day: String, spans: [String], frames: [String], all: Bool) async throws -> TraceDeleted {
        try traceGate()
        struct Body: Encodable { let day: String; let spans: [String]; let frames: [String]; let all: Bool }
        return try await postData("/sources/traces/delete",
                                  json: try JSONEncoder().encode(Body(day: day, spans: spans, frames: frames, all: all)))
    }

    func tracePreview(day: String?) async throws -> TraceDigestPreview {
        try traceGate()
        return try await get("/sources/traces/preview" + (day.map { "?day=\($0)" } ?? ""))
    }

    func traceAdded() async throws -> TraceAdded {
        try traceGate()
        return try await get("/sources/traces/added")
    }

    func traceRemoveFromMemory() async throws -> TraceRemoval {
        try traceGate()
        return try await post("/sources/traces/remove-from-memory")
    }

    func traceUndoRemoval(id: String) async throws -> Int {
        try traceGate()
        struct Restored: Decodable { let restored: Int }
        let answer: Restored = try await post("/sources/traces/remove-from-memory/undo", body: ["removal_id": id])
        return answer.restored
    }

    // MARK: - Messages (G179)

    /// `GET /sources/messages/settings` — which conversations this memory has ticked.
    func fetchMessagesSettings() async throws -> MessagesSettingsAnswer {
        try await get("/sources/messages/settings")
    }

    /// `POST /sources/messages/conversations` — the person's tick and mark and the detectors' suggestion for each
    /// listed conversation. The backend stores nothing.
    func describeMessagesConversations(_ conversations: [MessagesConversationPayload]) async throws
        -> MessagesConversationsAnswer {
        try await postData("/sources/messages/conversations",
                           json: try JSONEncoder().encode(["conversations": conversations]))
    }

    /// `PUT /sources/messages/settings` — tick or untick one conversation, or mark who it is with.
    func updateMessagesConversation(id: String, name: String?, ticked: Bool?, mark: MessagesMark?) async throws
        -> MessagesSettingsAnswer {
        var conversation: [String: Any] = ["id": id]
        if let name, !name.isEmpty { conversation["name"] = name }
        if let ticked { conversation["ticked"] = ticked }
        switch mark {
        case .agent?: conversation["actor"] = ["kind": "agent"]
        case .person?: conversation["actor"] = ["kind": "person"]
        case .clear?: conversation["clearActor"] = true
        case nil: break
        }
        return try await put("/sources/messages/settings", body: ["conversation": conversation])
    }

    /// `PUT /sources/messages/settings` — turn the AI-agent suggestions on or off for this memory.
    func setMessagesSuggestAgents(_ on: Bool) async throws -> MessagesSettingsAnswer {
        try await put("/sources/messages/settings", body: ["suggestAgents": on])
    }

    /// `POST /sources/messages/sync` — rows of one ticked conversation, serialised off the main actor.
    func postMessages(_ json: Data) async throws -> MessagesSyncResult {
        try await postData("/sources/messages/sync", json: json)
    }

    /// `GET /sources/messages/waiting` — the conversations Sleep has not read yet, with their message counts.
    func fetchMessagesWaiting() async throws -> MessagesWaitingAnswer {
        try await get("/sources/messages/waiting")
    }

    /// `PUT /sources/messages/photos` — the photos ticked chats share in Messages (2026-10-16), small PNG bytes the app
    /// read; the backend keeps them outside every bank and draws each at its chat's page.
    func putMessagesPhotos(_ photos: [MessagesPhotoPayload]) async throws -> MessagesPhotosAnswer {
        try await putData("/sources/messages/photos", json: try JSONEncoder().encode(["photos": photos]))
    }

    // MARK: WhatsApp and Telegram chats (G179, 2026-10-28; Telegram on the person's own account, ruling 47a)

    /// `GET /sources/{whatsapp|telegram}/settings` — the ticks of this memory.
    func fetchChatTicks(source: String) async throws -> ChatTickAnswer {
        try await get("/sources/\(source)/settings")
    }

    /// `POST /sources/whatsapp/conversations` — the person's tick for each listed chat; the backend stores nothing.
    func describeChats(source: String, ids: [(id: String, group: Bool)]) async throws -> ChatTickAnswer {
        try await post("/sources/\(source)/conversations",
                       body: ["conversations": ids.map { ["id": $0.id, "group": $0.group] }])
    }

    /// `PUT /sources/{whatsapp|telegram}/settings` — tick or untick one chat (live from now), or ask for its history.
    func updateChat(source: String, id: String, name: String?, group: Bool?, ticked: Bool?, history: Bool?) async throws
        -> ChatTickAnswer {
        var conversation: [String: Any] = ["id": id]
        if let name, !name.isEmpty { conversation["name"] = name }
        if let group { conversation["group"] = group }
        if let ticked { conversation["ticked"] = ticked }
        if let history { conversation["history"] = history }
        return try await put("/sources/\(source)/settings", body: ["conversation": conversation])
    }

    /// `POST /sources/whatsapp/sync` — one ticked chat's rows, read on this Mac.
    func postWhatsApp(_ json: Data) async throws -> ChatSyncAnswer {
        try await postData("/sources/whatsapp/sync", json: json)
    }

    func telegramStatus() async throws -> TelegramStatusAnswer { try await get("/sources/telegram/status") }

    /// chats-ux-v2 — waits server-side (≤ `wait` s) for the status to move past `since`.
    func telegramStatus(since: String, wait: Int) async throws -> TelegramStatusAnswer {
        try await get("/sources/telegram/status?since=\(since.filter(\.isHexDigit))&wait=\(max(0, min(wait, 25)))")
    }

    /// chats-ux-v2 — `GET /sources/telegram/chats/{id}/photo`: the chat's small profile photo; 404 → nil (a monogram).
    func telegramChatPhoto(id: String) async throws -> Data? {
        var request = makeRequest("/sources/telegram/chats/\(id.filter(\.isHexDigit))/photo", method: "GET", json: false)
        request.timeoutInterval = 20
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200, !data.isEmpty else { return nil }
        return data
    }

    /// The default connect (owner 2026-10-29): a QR the person scans in Telegram on their phone. The status that
    /// answers carries the `tg://login` link to draw; the backend replaces it as Telegram expires it.
    func telegramQR() async throws -> TelegramStatusAnswer { try await post("/sources/telegram/qr") }

    /// The fallback: the number goes to Telegram through the backend once, and is never kept.
    func telegramConnect(phone: String) async throws -> TelegramStatusAnswer {
        try await post("/sources/telegram/connect", body: ["phone": phone])
    }

    func telegramCode(_ code: String) async throws -> TelegramStatusAnswer {
        try await post("/sources/telegram/code", body: ["code": code])
    }

    func telegramPassword(_ password: String) async throws -> TelegramStatusAnswer {
        try await post("/sources/telegram/password", body: ["password": password])
    }

    func telegramDisconnect() async throws -> TelegramStatusAnswer { try await post("/sources/telegram/disconnect") }

    func telegramChats() async throws -> TelegramChatsAnswer { try await get("/sources/telegram/chats") }

    func telegramTick(id: String, name: String, ticked: Bool, consent: Bool) async throws -> ChatTickAnswer {
        var conversation: [String: Any] = ["id": id, "ticked": ticked, "consent": consent, "group": false]
        if !name.isEmpty { conversation["name"] = name }
        return try await put("/sources/telegram/settings", body: ["conversation": conversation])
    }

    /// `GET /entities/{id}/paper` — the paper card's two tiers (G133 / G121).
    func fetchPaperDetail(id: String) async throws -> PaperDetail {
        try await get("/entities/\(encodedID(id))/paper")
    }

    /// Ruling 48 (16), DR-80 — one citation marker's popover: reference `n` as cited by the line ending at `at`, or by
    /// the belief sentence `claim`. Read when the marker opens, never on card open.
    func fetchCitation(entityId: String, n: Int, at: Int?, claim: String?) async throws -> PageCitationDetail {
        var query: [String] = []
        if let at { query.append("at=\(at)") }
        if let claim, let escaped = claim.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) {
            query.append("claim=\(escaped)")
        }
        let suffix = query.isEmpty ? "" : "?" + query.joined(separator: "&")
        return try await get("/entities/\(encodedID(entityId))/citations/\(n)\(suffix)")
    }

    // MARK: - RSS feed subscriptions (G9)

    /// `GET /sources/feeds` → every subscribed RSS/Atom feed, in subscription order.
    func fetchFeeds() async throws -> [FeedSubscription] {
        let resp: FeedListResponse = try await get("/sources/feeds")
        return resp.feeds
    }

    /// `POST /sources/feeds` `{url, tags?}` → subscribe to a feed. Idempotent —
    /// re-subscribing an already-watched URL is a no-op on `added`/`lastPolled`
    /// and just merges in any new tags. Returns the created/existing record.
    @discardableResult
    func subscribeFeed(url: String, tags: [String] = []) async throws -> FeedSubscription {
        var body: [String: Any] = ["url": url]
        if !tags.isEmpty { body["tags"] = tags }
        return try await post("/sources/feeds", body: body)
    }

    /// `DELETE /sources/feeds` `{url}` → unsubscribe. Throws `.httpError(404, _)`
    /// if the URL wasn't subscribed — callers surface that via `friendlyError`.
    func unsubscribeFeed(url: String) async throws {
        try await delete("/sources/feeds", body: ["url": url])
    }

    /// `POST /sources/poll-feeds` → check every subscribed feed for new items.
    /// Respects the same `CICADA_ALLOW_FEED_FETCH` network gate as `ingestRSS`;
    /// with the gate closed, nothing is fetched and the result reports
    /// `skippedNoNetwork` instead of `new`.
    @discardableResult
    func pollFeeds() async throws -> PollFeedsResult {
        return try await post("/sources/poll-feeds")
    }

    // MARK: - Calendar subscriptions (mirrors RSS feed subscriptions above)

    /// `GET /sources/calendars` → every subscribed webcal/ICS calendar, in
    /// subscription order.
    func fetchCalendars() async throws -> [CalendarSubscription] {
        let resp: CalendarListResponse = try await get("/sources/calendars")
        return resp.calendars
    }

    /// `POST /sources/calendars` `{url, tags?}` → subscribe to a webcal://.ics
    /// calendar. Idempotent, mirrors `subscribeFeed`.
    @discardableResult
    func subscribeCalendar(url: String, tags: [String] = []) async throws -> CalendarSubscription {
        var body: [String: Any] = ["url": url]
        if !tags.isEmpty { body["tags"] = tags }
        return try await post("/sources/calendars", body: body)
    }

    /// `DELETE /sources/calendars` `{url}` → unsubscribe. Throws
    /// `.httpError(404, _)` if the URL wasn't subscribed, mirrors `unsubscribeFeed`.
    func unsubscribeCalendar(url: String) async throws {
        try await delete("/sources/calendars", body: ["url": url])
    }

    /// `POST /sources/poll-calendars` → check every subscribed calendar for
    /// new events. Mirrors `pollFeeds`, including the same network-gate
    /// behavior when live fetch is disabled server-side.
    @discardableResult
    func pollCalendars() async throws -> PollCalendarsResult {
        return try await post("/sources/poll-calendars")
    }

    // MARK: - Origins (ORIGIN-PROVENANCE)

    /// `GET /origins` → repo-wide episode/entity counts per capture origin.
    /// Returns `[]` on a 404 so the Capture page's origins strip degrades
    /// gracefully (hides itself) against a backend that hasn't shipped this yet.
    func fetchOrigins() async throws -> [OriginStat] {
        do {
            let resp: OriginsResponse = try await get("/origins")
            return resp.origins
        } catch APIError.httpError(404, _) {
            return []
        }
    }

    /// Shared multipart POST for file ingestion endpoints. Mirrors `uploadFile`
    /// but takes the target path so both `/conversations/upload` and
    /// `/sources/upload` reuse it. Generic over the response so the same
    /// wire-up serves the real upload (`UploadResponse`) and the staging-free
    /// preview (`UploadPreview`) without duplicating the multipart plumbing.
    /// `filename`: the name the backend sees; nil is the file's own name. A walked folder's file is named by its
    /// path inside the folder, which the backend reads as "a member of an export folder" (`saved_exports`).
    private func uploadMultipart<T: Decodable>(path: String, fileURL: URL, filename: String? = nil) async throws -> T {
        try await uploadMultipart(path: path, fileData: try Data(contentsOf: fileURL),
                                  filename: filename ?? fileURL.lastPathComponent)
    }

    private func uploadMultipart<T: Decodable>(path: String, fileData: Data, filename: String) async throws -> T {
        var request = makeRequest(path, method: "POST", json: false)

        let boundary = UUID().uuidString
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        // A quote or line break would end the header early; a path inside a folder never needs one.
        let filename = filename
            .replacingOccurrences(of: "\"", with: "'").replacingOccurrences(of: "\r", with: " ")
            .replacingOccurrences(of: "\n", with: " ")

        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: application/octet-stream\r\n\r\n".data(using: .utf8)!)
        body.append(fileData)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }
        return try decoder.decode(T.self, from: data)
    }

    /// `POST /sources/linkedin-connections/preview` — how many of the export's connections are people Cicada already
    /// knows. Writes nothing; Confirm re-posts the same bytes to `/import`. Only `Connections.csv`'s bytes are sent —
    /// an export `.zip` is opened here (`LinkedInConnectionsFile`), never posted whole.
    func previewLinkedInConnections(_ payload: LinkedInConnectionsPayload) async throws -> LinkedInConnectionsPreview {
        try await uploadMultipart(path: "/sources/linkedin-connections/preview" + Self.exportedOnQuery(payload.exportedOn),
                                  fileData: payload.data, filename: payload.filename)
    }

    /// `POST /sources/linkedin-connections/import` — enrich the people Cicada already has; never adds anyone.
    func importLinkedInConnections(_ payload: LinkedInConnectionsPayload) async throws -> LinkedInConnectionsImport {
        try await uploadMultipart(path: "/sources/linkedin-connections/import" + Self.exportedOnQuery(payload.exportedOn),
                                  fileData: payload.data, filename: payload.filename)
    }

    static func exportedOnQuery(_ day: String?) -> String {
        guard let day, day.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil else { return "" }
        return "?exported_on=\(day)"
    }

    /// `POST /sources/upload?preview=true` — describe a file without importing
    /// any of it. Safe to call on every drop: the backend stages nothing.
    func previewSource(fileURL: URL, includeHistory: Bool = false) async throws -> UploadPreview {
        let query = includeHistory ? "?preview=true&include_history=true" : "?preview=true"
        return try await uploadMultipart(path: "/sources/upload" + query, fileURL: fileURL)
    }

    /// `POST /sources/sync-safari-tabs?preview=true` — per-device tab counts
    /// from bytes the app read (R1). Stages nothing; the import re-posts the
    /// same bytes, so nothing is cached server-side between the two.
    func previewSafariTabs(db: Data, wal: Data?) async throws -> SafariTabsPreview {
        var body: [String: Any] = ["safariTabsDbB64": db.base64EncodedString()]
        if let wal { body["safariTabsWalB64"] = wal.base64EncodedString() }
        return try await post("/sources/sync-safari-tabs?preview=true", body: body)
    }

    /// `POST /sources/sync-bookmarks?preview=true` — folder trees with leaf
    /// counts (R5). Stages nothing.
    func previewBookmarks(chromeData: Data?, safariData: Data?) async throws -> BookmarkTreePreview {
        var body: [String: Any] = [:]
        if let chromeData { body["chromeDataB64"] = chromeData.base64EncodedString() }
        if let safariData { body["safariDataB64"] = safariData.base64EncodedString() }
        return try await post("/sources/sync-bookmarks?preview=true", body: body)
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

    /// G136 — the ⌘K palette's server tier (`GET /search`, "The wire" in the
    /// search-backend plan). `mode=prefix` is FTS only and never embeds;
    /// `hybrid` adds the stored vectors. The query is percent-encoded the way
    /// `fetchRecentConversations` encodes its filters, and it goes nowhere
    /// else — no log, no cache, no telemetry (design §3.8).
    func searchMemory(_ query: String, kinds: [String], mode: String, perKind: Int) async throws -> MemorySearchResponse {
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "&+=?/#")
        let q = query.addingPercentEncoding(withAllowedCharacters: allowed) ?? query
        return try await get("/search?q=\(q)&kinds=\(kinds.joined(separator: ","))&mode=\(mode)&per_kind=\(perKind)")
    }

    // MARK: - Sleep

    func fetchSleepStatus() async throws -> SleepStatusResponse {
        return try await get("/sleep/status")
    }

    func triggerSleep() async throws -> SleepTriggerResponse {
        return try await post("/sleep/trigger")
    }

    /// Sleep page v5 — resume the paused run (same run id, its counters carried). Only the Sleep page's Continue
    /// calls this (`SleepViewModel.continueRun`); every other door routes to the page while a run is paused.
    func continueSleepRun() async throws -> SleepTriggerResponse {
        return try await post("/sleep/trigger", body: ["continue": true])
    }

    /// `POST /sleep/run/end` — forget the paused run; every conversation still waits. 409 while a run reads.
    func endSleepRun() async throws -> SleepEndRunResponse {
        return try await post("/sleep/run/end")
    }

    /// `POST /sleep/parked/retry` — read exactly these parked conversations (all of them when `ids` is `nil`)
    /// in a run of their own. 409 while a run reads or is paused.
    func retryParked(ids: [String]?) async throws -> SleepTriggerResponse {
        return try await post("/sleep/parked/retry", body: ids.map { ["ids": $0] } ?? [:])
    }

    func fetchRunOptions() async throws -> SleepRunOptions {
        return try await get("/sleep/run-options")
    }

    func updateRunOptions(_ change: SleepRunOptionsChange) async throws -> SleepRunOptions {
        return try await put("/sleep/run-options", body: change.body)
    }

    /// `GET /sleep/queue` — bounded (≤ 200), frontmatter only.
    func fetchSleepQueue(origin: String? = nil, state: String? = nil, offset: Int = 0,
                         limit: Int = 50) async throws -> SleepQueueResponse {
        var query = ["offset=\(offset)", "limit=\(min(200, max(1, limit)))"]
        if let origin, let o = origin.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) {
            query.append("origin=\(o)")
        }
        if let state { query.append("state=\(state)") }
        return try await get("/sleep/queue?" + query.joined(separator: "&"))
    }

    /// `GET /sleep/runs/{id}` — one whole run (not a Store domain).
    func fetchSleepRun(_ id: String) async throws -> SleepRunDetail {
        let encoded = id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? id
        return try await get("/sleep/runs/\(encoded)")
    }

    /// `GET /sleep/runs/{id}/items` or `GET /sleep/history/{commit}/items` — what one consolidation read and wrote
    /// (the run card's dropdown; not a Store domain). Sent with the ETag the caller holds: a 304 keeps its copy.
    func fetchSleepConsolidated(_ key: SleepConsolidatedKey, etag: String?) async throws -> Conditional<SleepConsolidated> {
        try await getConditional(key.path, etag: etag)
    }

    /// Cooperative-cancel whatever cycle is currently running. See
    /// `SleepCancelResponse` — always 200, `status` says whether there was
    /// anything to cancel.
    func cancelSleep() async throws -> SleepCancelResponse {
        return try await post("/sleep/cancel")
    }

    // MARK: - Ask (G52)

    /// `POST /ask` — grounded NL synthesis over the graph
    /// (`api/routers/ask.py`). `topK` defaults to the same 6 the server uses
    /// when the field is omitted.
    func ask(query: String, topK: Int = 6) async throws -> AskResponse {
        return try await post("/ask", body: ["query": query, "topK": topK])
    }

    /// `GET /sleep/episodes?processed=false` — only the episodes still waiting for Sleep (the Sleep page's Waiting rows,
    /// a source's queue strip), revalidated with its ETag: a 304 keeps the rows held. Not a Store
    /// domain — `SleepViewModel` holds the rows and the tag in memory. Every episode, read ones too, was 8k rows and
    /// 4.5 MB on a large bank, fetched on every Sleep page load (2026-10-19). An older backend ignores the query and
    /// answers every episode without a tag; `SleepViewModel.queuedEpisodes` still keeps only the waiting ones.
    func fetchEpisodeQueue(etag: String?) async throws -> Conditional<[EpisodeQueueItem]> {
        try await getConditional(Self.waitingEpisodesPath, etag: etag)
    }

    static let waitingEpisodesPath = "/sleep/episodes?processed=false"

    func fetchSchedule() async throws -> ScheduleConfig {
        return try await get("/sleep/schedule")
    }

    /// G125: hand-builds the PUT body rather than `JSONEncoder`-ing `cfg`
    /// (this client's request helper takes `[String: Any]`, not `Encodable`).
    /// Before this fix the body only ever carried `enabled/hour/minute` —
    /// `mode`/`intervalHours` never reached the server, so picking "Every N
    /// hours" in Settings silently saved as whatever `mode` the (unsent,
    /// thus default) `enabled` field derived server-side. Every field of
    /// `ScheduleConfig` must be listed here explicitly.
    func updateSchedule(_ cfg: ScheduleConfig) async throws -> ScheduleConfig {
        return try await put("/sleep/schedule", body: [
            "mode": cfg.mode,
            "enabled": cfg.enabled,
            "hour": cfg.hour,
            "minute": cfg.minute,
            "intervalHours": cfg.intervalHours,
        ])
    }

    /// `GET /sleep/engine` — the G122 picker's current mode/model and both
    /// ruling-4 previews (`manual`/`scheduled`).
    func fetchSleepEngine() async throws -> SleepEngineResponse {
        return try await get("/sleep/engine")
    }

    /// Engine picker v2 — the person's Refresh: `POST /sleep/engine/models/refresh` re-reads one card's model list from
    /// its own harness and answers what `GET /sleep/engine` would. Only ever from a click.
    func refreshSleepEngineModels(cardId: String) async throws -> SleepEngineResponse {
        return try await post("/sleep/engine/models/refresh", body: ["id": cardId])
    }

    /// `PUT /sleep/engine`. Hand-builds the body (same reasoning as
    /// `updateSchedule`'s own doc comment: the `put<T>` helper takes
    /// `[String: Any]`, not `Encodable`) and — unlike `updateSchedule`,
    /// which always sends every field — omits `model`/`disambiguationModel`
    /// from the dict entirely when `nil` rather than sending JSON `null`.
    /// The backend tells "omitted" from "explicitly cleared" via
    /// `SleepEngineChoice.model_fields_set` (`sleep_engine_prefs.
    /// validate_and_write`'s cross-mode staleness guard), so sending a
    /// `null` here would read as "clear this field" instead of "leave it
    /// alone". `allowOverage` (R-E13) follows the same rule: the backend's
    /// `SleepEngineChoice.allow_overage` is `None` when omitted, which leaves
    /// the stored opt-in untouched.
    func updateSleepEngine(
        mode: String, model: String? = nil, disambiguationModel: String? = nil,
        allowOverage: Bool? = nil
    ) async throws -> SleepEngineResponse {
        var body: [String: Any] = ["mode": mode]
        if let model { body["model"] = model }
        if let disambiguationModel { body["disambiguationModel"] = disambiguationModel }
        if let allowOverage { body["allowOverage"] = allowOverage }
        return try await put("/sleep/engine", body: body)
    }

    /// `GET /sleep/history?limit=` — the consolidation history the Sleep
    /// page's history card lists, newest first (G125 R4).
    func fetchSleepHistory(limit: Int = 15) async throws -> [SleepHistoryEntry] {
        return try await get("/sleep/history?limit=\(limit)")
    }

    /// `GET /sleep/history/{commit}` — what one cycle consolidated (G125
    /// R12). The commit hash is `[0-9a-f]+` so no percent-encoding is
    /// actually needed, but this mirrors every other id-in-path call here.
    func fetchSleepCycleDetail(_ commit: String) async throws -> SleepCycleDetail {
        let encoded = commit.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? commit
        return try await get("/sleep/history/\(encoded)")
    }

    /// `GET /settings/owner` — the first-run sheet's identity step reads
    /// this to pre-fill the name field when "Run setup again" reopens it
    /// (G117).
    func fetchOwnerSettings() async throws -> OwnerSettings {
        return try await get("/settings/owner")
    }

    /// `PUT /settings/owner`. `handle`/`email` are omitted from the body
    /// entirely when `nil` rather than sent as JSON `null` — the same
    /// conditional-assignment shape `updateSleepEngine` uses just above,
    /// for the same reason: boxing a `nil` optional as `Any` inside a
    /// `[String: Any]` is not JSON-null, it's an
    /// `Optional<Any>.some(Optional<String>.none)`, which
    /// `JSONSerialization.data(withJSONObject:)` (`put`'s own
    /// implementation, below) cannot serialize and throws at runtime —
    /// exactly what happens every time the person leaves handle/email
    /// blank, the common case.
    func updateOwnerSettings(
        name: String, handle: String? = nil, email: String? = nil
    ) async throws -> OwnerSettings {
        var body: [String: Any] = ["name": name]
        if let handle { body["handle"] = handle }
        if let email { body["email"] = email }
        return try await put("/settings/owner", body: body)
    }

    // MARK: - Settings v3 (G139)

    /// `DELETE /banks/{name}` — moves the bank to `<root>/.trash/` (R-O19).
    /// 409 (in plain words) for the active bank and for the memory folder
    /// itself; the Privacy page hides both, this is the backstop.
    func deleteBank(name: String) async throws -> BankTrashResult {
        let data = try await delete("/banks/\(encodedBank(name))")
        do {
            return try decoder.decode(BankTrashResult.self, from: data)
        } catch {
            throw APIError.decodingError("\(error)")
        }
    }

    /// `GET /banks/{name}/export` downloaded to a temporary file the caller
    /// moves to where the person chose (R-O20). A large bank with its history
    /// can take a while, hence the long timeout.
    func exportBank(name: String) async throws -> URL {
        var request = makeRequest("/banks/\(encodedBank(name))/export", method: "GET", json: false)
        request.timeoutInterval = 300
        let (tmp, response) = try await session.download(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            let msg = (try? String(contentsOf: tmp, encoding: .utf8)) ?? "Export failed"
            try? FileManager.default.removeItem(at: tmp)
            throw APIError.httpError(http.statusCode, msg)
        }
        // URLSession deletes its download file when this call returns, so it
        // is moved somewhere this process owns first.
        let kept = FileManager.default.temporaryDirectory.appendingPathComponent("cicada-export-\(UUID().uuidString).zip")
        try FileManager.default.moveItem(at: tmp, to: kept)
        return kept
    }

    // MARK: Search model (G182 phase 3)

    /// `GET /embeddings` — which model the active bank's vectors use, what the next index sync
    /// builds with, the models this Mac can run and the larger model's install. Not a Store
    /// domain, no ETag; Settings → Privacy & data polls it only while an install runs.
    func fetchEmbeddings() async throws -> EmbeddingsStatus { try await get("/embeddings") }

    /// `POST /embeddings/choice` — `nil` goes back to the default. 400 for a model Cicada does not
    /// offer, 409 "not installed" or "Sleep is running" (both a sentence in `detail`).
    func chooseEmbeddingModel(_ id: String?) async throws -> EmbeddingsStatus {
        try await post("/embeddings/choice", body: ["model": id.map { $0 as Any } ?? NSNull()])
    }

    /// `POST /embeddings/install` (202) — the person's own read-access token rides this one request
    /// body and nothing else: never a header, a query, a log line, UserDefaults or the Keychain, and
    /// nothing here keeps it once the request is built. 400 for a token that is not shaped like
    /// one, 409 while an install already runs.
    func installLargerEmbeddingModel(token: String) async throws -> EmbeddingsStatus {
        try await post("/embeddings/install", body: ["hfToken": token])
    }

    /// `POST /embeddings/install` (202) with `model` — a download that needs no account (the Neural Engine
    /// model: pinned files, each checked before it is installed). 409 on a Mac that can't run it or while
    /// another install runs.
    func installEmbeddingModel(_ id: String) async throws -> EmbeddingsStatus {
        try await post("/embeddings/install", body: ["model": id])
    }

    /// `GET /memory/decay-suggestions` (G147) — the per-type pace suggestions and the pace
    /// already chosen. Not a Store domain, no ETag.
    func fetchDecayTuning() async throws -> DecayTuningResponse { try await get("/memory/decay-suggestions") }

    // MARK: Reading with the person's own agent (G166)

    /// `GET /reading/settings` — the switch, the sites the person let an agent read, and the first-use acknowledgement.
    func fetchReadingSettings() async throws -> ReadingSettingsResponse { try await get("/reading/settings") }

    /// `PUT /reading/settings` — only the fields passed are sent. `sites` is a patch `{site: bool}` (true lets an agent
    /// read that site, false takes it back; a site Cicada's reader has not needed the browser for is a 422). Turning the
    /// switch or a site on needs a current acknowledgement, given in the same call (`acknowledge`) or already stored;
    /// a 422 carries the sentence why.
    func setReadingSettings(agentEnabled: Bool? = nil, sites: [String: Bool]? = nil,
                            acknowledge: Bool = false, exploreSignedIn: Bool? = nil,
                            neverExplore: [String: Bool]? = nil,
                            youtubeLists: [String: Bool]? = nil,
                            savedLists: [String: Bool]? = nil) async throws -> ReadingSettingsResponse {
        try await put("/reading/settings", body: Self.readingSettingsBody(
            agentEnabled: agentEnabled, sites: sites, acknowledge: acknowledge, exploreSignedIn: exploreSignedIn,
            neverExplore: neverExplore, youtubeLists: youtubeLists, savedLists: savedLists))
    }

    /// `PUT /reading/settings`' body, pure: only what the caller named rides it — a saved-list patch never carries a
    /// `sites` grant (G206: a saved list is a standing ask for one page, never the site; review of #448).
    nonisolated static func readingSettingsBody(agentEnabled: Bool? = nil, sites: [String: Bool]? = nil,
                                                acknowledge: Bool = false, exploreSignedIn: Bool? = nil,
                                                neverExplore: [String: Bool]? = nil,
                                                youtubeLists: [String: Bool]? = nil,
                                                savedLists: [String: Bool]? = nil) -> [String: Any] {
        var body: [String: Any] = [:]
        // G206: a `{x|instagram|linkedin: Bool}` patch.
        if let savedLists { body["savedLists"] = savedLists }
        // G71 (2026-10-16): a `{watch_later|history: Bool}` patch.
        if let youtubeLists { body["youtubeLists"] = youtubeLists }
        if let agentEnabled { body["agentEnabled"] = agentEnabled }
        // G166 exploring: the signed-in switch (D2 amended) and a Never explore patch (D3).
        if let exploreSignedIn { body["exploreSignedIn"] = exploreSignedIn }
        if let neverExplore { body["neverExplore"] = neverExplore }
        if let sites { body["sites"] = sites }
        if acknowledge { body["acknowledge"] = true }
        return body
    }

    /// G198 — `GET /settings/editors`: the agents the person lets edit a page's words directly, and the local ones
    /// they could add. Machine-wide (outside every bank); not a Store domain.
    func fetchPageEditors() async throws -> PageEditorsResponse { try await get("/settings/editors") }

    /// G198 — `PUT /settings/editors` with a one-agent patch (`true` adds it, `false` removes it). A refusal is a 400
    /// whose `detail` is the sentence to show.
    func setPageEditor(_ harness: String, trusted: Bool) async throws -> PageEditorsResponse {
        try await put("/settings/editors", body: ["trusted": [harness: trusted]])
    }

    /// `GET /reading/sites` — the sites Cicada's own reader could not read, with counts. Not a Store domain.
    func fetchReadingSites() async throws -> ReadingSitesResponse { try await get("/reading/sites") }

    /// The same list revalidated with its ETag (Home's `ReadingSitesCache`): a 304 keeps what is held.
    func fetchReadingSites(etag: String?) async throws -> Conditional<ReadingSitesResponse> {
        try await getConditional("/reading/sites", etag: etag)
    }

    /// G61 S3-b — `GET /entities/{id}/sources/icon/{site}`: the mark of a site a source on this page names (icon
    /// service only; the site is never contacted). nil on a 404.
    func fetchEntitySourceIcon(entityId: String, site: String) async throws -> Data? {
        guard site.range(of: "^[a-z0-9][a-z0-9.-]*$", options: .regularExpression) != nil, !site.contains("..") else {
            return nil
        }
        var request = makeRequest("/entities/\(encodedID(entityId))/sources/icon/\(site)", method: "GET", json: false)
        request.timeoutInterval = Self.refreshTimeout
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        if http.statusCode == 404 { return nil }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            throw APIError.httpError(http.statusCode, String(data: data, encoding: .utf8) ?? "Unknown error")
        }
        return data
    }

    /// `GET /reading/sites/{site}/icon` — a site's favicon from the icon service (the site is never contacted). nil on
    /// a 404: "no icon" is an ordinary answer and the row draws its own mark.
    /// Owner ruling 2026-10-19 — a saved link's own site icon, asked of that site by the backend (never an icon
    /// service) for a row of a list the person opened. 404 is "draw the monogram".
    func fetchSavedLinkSiteIcon(mediaEntityId: String) async throws -> Data? {
        try await fetchOwnSiteIcon(path: "/sources/saved/\(encodedID(mediaEntityId))/site-icon")
    }

    /// Owner 2026-10-20 — the same icon for a saved link Sleep has not made a page of yet, asked by its episode's id
    /// (`GET /sources/saved/episodes/{id}/site-icon`; the backend reads the site from that episode's own link).
    func fetchSavedEpisodeSiteIcon(episodeId: String) async throws -> Data? {
        try await fetchOwnSiteIcon(path: "/sources/saved/episodes/\(encodedID(episodeId))/site-icon")
    }

    private func fetchOwnSiteIcon(path: String) async throws -> Data? {
        var request = makeRequest(path, method: "GET", json: false)
        request.timeoutInterval = Self.refreshTimeout
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        if http.statusCode == 404 { return nil }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            throw APIError.httpError(http.statusCode, String(data: data, encoding: .utf8) ?? "Unknown error")
        }
        return data
    }

    /// Sources v4 — a picture Cicada's own API serves for a Sources row (a Messages chat's photo, a watched video's
    /// still): its bytes, or nil on a 404 ("draw the monogram"). `path` is built by `SourcePictures`, never by a caller.
    func fetchSourcePicture(path: String) async throws -> Data? {
        var request = makeRequest(path, method: "GET", json: false)
        request.timeoutInterval = Self.refreshTimeout
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        if http.statusCode == 404 { return nil }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            throw APIError.httpError(http.statusCode, String(data: data, encoding: .utf8) ?? "Unknown error")
        }
        return data
    }

    func fetchSiteIcon(site: String) async throws -> Data? {
        guard site.range(of: "^[a-z0-9][a-z0-9.-]*$", options: .regularExpression) != nil, !site.contains("..") else {
            return nil
        }
        var request = makeRequest("/reading/sites/\(site)/icon", method: "GET", json: false)
        request.timeoutInterval = Self.refreshTimeout
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        if http.statusCode == 404 { return nil }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            throw APIError.httpError(http.statusCode, String(data: data, encoding: .utf8) ?? "Unknown error")
        }
        return data
    }

    /// `GET /agent-methods` — how the person's agent does each job, with the choices. Not a Store domain.
    func fetchAgentMethods() async throws -> AgentMethodsResponse { try await get("/agent-methods") }

    /// `PUT /agent-methods` — save a choice (`auto`, `own` or a catalog skill's id). The server also tries to file the
    /// chosen skill's page in the graph; `write.page` says what happened. A 422 carries a sentence.
    func setAgentMethod(job: String, choice: String) async throws -> AgentMethodWriteResponse {
        try await put("/agent-methods", body: ["job": job, "choice": choice])
    }

    /// `POST /agent-methods/skills/{skill}/page` — "Add to your graph" for an installed skill that has no page. 409
    /// while Sleep is writing (with a sentence).
    func addSkillPage(skill: String) async throws -> AgentMethodPage {
        try await post("/agent-methods/skills/\(skill)/page")
    }

    /// `GET /reading/prompt` — the generic, URL-free sentence to hand the person's own agent.
    func fetchReadingPrompt() async throws -> String {
        struct Reply: Decodable { let prompt: String }
        let reply: Reply = try await get("/reading/prompt")
        return reply.prompt
    }

    /// `POST /reading/asks` — "Ask an agent" on one link. 409 while the switch (or the link's site) is off, 422 for a
    /// link an agent is never offered; both carry a sentence written for the person.
    func askAgentToRead(url: String) async throws -> ReadingAskResponse {
        try await post("/reading/asks", body: ["url": url])
    }

    /// `PUT /memory/decay-tuning` (G147) — `nil` clears a kind back to the usual pace. 409
    /// while Sleep runs; 422 with a plain sentence for a pace outside what the server allows.
    func setDecayTuning(_ changes: [String: Double?]) async throws -> DecayTuningResponse {
        var body: [String: Any] = [:]
        for (type, value) in changes { body[type] = value.map { $0 as Any } ?? NSNull() }
        return try await put("/memory/decay-tuning", body: body)
    }

    /// `GET /skills/recommended` (G138) — the reviewed catalog with install
    /// state derived per request. No ETag and no Store domain (R-O23).
    func fetchRecommendedSkills() async throws -> RecommendedSkillsResponse { try await get("/skills/recommended") }

    /// The Skills page's one door (owner 2026-10-15): any `/skills…` route, its body as JSON, the answer's bytes for
    /// `SkillsAPI` to decode. A refusal carries the server's sentence (`APIError.httpError`).
    func skillsRequest(_ method: String, _ path: String, body: [String: Any]? = nil,
                       timeout: TimeInterval = 120) async throws -> Data {
        var request = makeRequest(path, method: method, json: body != nil)
        if let body { request.httpBody = try JSONSerialization.data(withJSONObject: body) }
        request.timeoutInterval = timeout
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            throw APIError.httpError(http.statusCode, String(data: data, encoding: .utf8) ?? "Unknown error")
        }
        return data
    }

    // MARK: - Remote connector (G135)

    /// `GET /remote/status`. `probe: true` also checks the public address
    /// (3 s server-side), so it gets a longer client timeout than the default poll.
    func fetchRemoteStatus(probe: Bool = false) async throws -> RemoteStatus {
        try await get("/remote/status" + (probe ? "?probe=true" : ""), timeout: probe ? 15 : nil)
    }

    /// `PUT /remote/settings` — omitted fields are left alone (the backend reads
    /// `model_fields_set`); an empty `publicBaseURL` clears it.
    func updateRemoteSettings(enabled: Bool? = nil, publicBaseURL: String? = nil) async throws -> RemoteStatus {
        var body: [String: Any] = [:]
        if let enabled { body["enabled"] = enabled }
        if let publicBaseURL { body["publicBaseUrl"] = publicBaseURL }
        return try await put("/remote/settings", body: body)
    }

    func fetchRemoteConnectors() async throws -> [RemoteConnector] {
        try await get("/remote/connectors")
    }

    /// `expiresInDays` is 7, 30 or 90 — every connector expires (R-R3); the
    /// backend refuses anything else, `null` included.
    func createRemoteConnector(app: String, label: String, scopes: [String], expiresInDays: Int) async throws -> RemoteConnectorCreated {
        let body: [String: Any] = ["app": app, "label": label, "scopes": scopes, "expiresInDays": expiresInDays]
        return try await post("/remote/connectors", body: body)
    }

    func rotateRemoteConnector(id: String) async throws -> RemoteConnectorCreated {
        try await post("/remote/connectors/\(encodedID(id))/rotate")
    }

    func revokeRemoteConnector(id: String) async throws -> RemoteConnector {
        let data = try await delete("/remote/connectors/\(encodedID(id))")
        return try decoder.decode(RemoteConnector.self, from: data)
    }

    /// `GET /remote/oauth/requests` — that sign-ins wait (ruling 32): no code, no name. Not a Store domain: the From
    /// anywhere page polls it while it is open.
    func fetchRemoteSignIns() async throws -> [RemoteSignInWaiting] {
        try await get("/remote/oauth/requests")
    }

    /// `POST /remote/oauth/match` — the waiting sign-in whose page shows this code (404 when none does).
    func matchRemoteSignIn(code: String) async throws -> RemoteSignInMatch {
        try await post("/remote/oauth/match", body: ["userCode": code])
    }

    /// `POST /remote/oauth/approve` — approves only by the typed code, never by a request id.
    func approveRemoteSignIn(code: String, scopes: [String], expiresInDays: Int) async throws -> RemoteConnector {
        let body: [String: Any] = ["userCode": code, "scopes": scopes, "expiresInDays": expiresInDays]
        return try await post("/remote/oauth/approve", body: body)
    }

    func denyRemoteSignIn(ref: String) async throws {
        _ = try await post("/remote/oauth/requests/\(encodedID(ref))/deny") as Data
    }

    func denyAllRemoteSignIns() async throws {
        _ = try await post("/remote/oauth/requests/deny-all") as Data
    }

    // MARK: - Devices (G181 phase 3)

    /// `GET /devices/status` (G212) — this server and each device by its own name, connected or not, how it connects
    /// and what waits for it. Not a Store domain and no ETag (it changes by the minute): the Sleep page polls it while
    /// it shows and holds the answer in memory.
    func fetchMachineStatus() async throws -> MachineStatusList {
        try await get("/devices/status", timeout: Self.refreshTimeout)
    }

    /// `GET /devices` — outside every bank, so never a Store domain (`DeviceDirectory` keeps it in memory).
    func getDevicesList() async throws -> DeviceList {
        try await get("/devices", timeout: Self.refreshTimeout)
    }

    /// `POST /devices` — the master token's alone (This Mac); the answer is the only place the token ever appears.
    func createDevice(name: String) async throws -> DeviceCreated {
        try await post("/devices", body: ["name": name])
    }

    /// `DELETE /devices/{id}` — the master token's alone; the device's next request is refused.
    func revokeDevice(id: String) async throws -> DeviceRecord {
        struct Answer: Decodable { let device: DeviceRecord }
        let data = try await delete("/devices/\(encodedID(id))")
        return try decoder.decode(Answer.self, from: data).device
    }

    // MARK: - One memory on every device (G132 phase 1): share, keep a copy

    /// `GET /sync/publish` — whether this computer, the home, shares its memory with the person's other computers.
    func fetchPublish() async throws -> PublishState {
        try await get("/sync/publish", timeout: Self.refreshTimeout)
    }

    /// `PUT /sync/publish` — the person's switch (this computer's own token; never a demo memory).
    func setPublish(_ on: Bool) async throws -> PublishState {
        try await put("/sync/publish", body: ["publish": on])
    }

    /// `GET /sync/replica` — this computer's mode and, while it keeps a copy, how the copy stands (counts only).
    func fetchReplica() async throws -> ReplicaState {
        try await get("/sync/replica", timeout: Self.refreshTimeout)
    }

    /// `PUT /sync/replica` — keep a copy of the memory the computer at `home` holds, paired with its one-time code.
    func keepCopy(home: String, code: String) async throws -> ReplicaSetupAnswer {
        try await put("/sync/replica", body: ["home": home, "code": code])
    }

    /// `DELETE /sync/replica` — stop keeping a copy (the copy stays on disk, inactive).
    func stopCopy() async throws {
        _ = try await delete("/sync/replica")
    }

    /// `POST /sync/replica/restart` — this computer's backend starts again, so a change of mode takes effect.
    func restartForCopy() async throws {
        _ = try await post("/sync/replica/restart")
    }

    /// `POST /sync/replica/recopy` — "Copy again" after the home's history changed.
    func copyAgain() async throws {
        _ = try await post("/sync/replica/recopy")
    }

    // MARK: - Moving the home (G132 phase 2): who runs consolidation, and switching it

    /// `GET /sync/home` — the device that runs consolidation, with every other device's lag; `shared: false` on a
    /// computer that shares nothing. Machine-wide, never a Store domain.
    func fetchHome() async throws -> HomeOverview {
        try await get("/sync/home", timeout: Self.refreshTimeout)
    }

    /// `POST /sync/home/move` — the person confirmed: `device` becomes the home (a copy's backend asks the home).
    func moveHome(to device: String) async throws -> HomeMoveAnswer {
        try await post("/sync/home/move", body: ["device": device])
    }

    /// `GET /sync/home/take-over` — how far behind this copy is of the last home it saw, before the person confirms.
    func fetchTakeOverPreview() async throws -> TakeOverPreview {
        try await get("/sync/home/take-over", timeout: Self.refreshTimeout)
    }

    /// `POST /sync/home/take-over` — the person confirmed what they were shown (`behind`): this computer takes over.
    func takeOver(behind: Int) async throws {
        _ = try await post("/sync/home/take-over", body: ["behind": behind, "confirm": true])
    }

    // MARK: - The connection model (G217, G212, G213)

    /// `GET /providers` — static per release, so no ETag and no Store domain: fetched once per launch, kept in memory.
    func fetchProviders() async throws -> ProvidersResponse {
        try await get("/providers", timeout: Self.refreshTimeout)
    }

    /// `GET /devices/status` — not a Store domain (it changes by the minute); polled while a view shows it.
    func fetchDeviceStatus() async throws -> DeviceStatusResponse {
        try await get("/devices/status", timeout: Self.refreshTimeout)
    }

    /// `POST /devices/pairing` — the master token's alone; `url` is where the new device will reach this server.
    func createPairing(url: String?, kind: PairingKind = .capture) async throws -> PairingCreated {
        // `kind` is #432's (an older backend ignores it): a phone's capture-only token, or a computer's full one.
        var body: [String: Any] = ["kind": kind.rawValue]
        if let url { body["url"] = url }
        return try await post("/devices/pairing", body: body)
    }

    /// `GET /devices/reach` (2026-10-29): the guided reach step; `check` also fetches this Mac's own served address the
    /// way a phone would (the backend's one bounded fetch, on the person's open or click).
    func fetchDeviceReach(check: Bool) async throws -> DeviceReach {
        try await get(check ? "/devices/reach?check=true" : "/devices/reach", timeout: Self.refreshTimeout)
    }

    /// `POST /devices/reach/serve` (owner 2026-10-29, "Yes, one click"): `serve` runs the `serve` step's command,
    /// `stop` the `ready` step's off. Only the action is sent; the backend builds the command it showed.
    func runDeviceReach(_ action: DeviceReachAction) async throws -> DeviceReachServe {
        try await post("/devices/reach/serve", body: ["action": action.rawValue])
    }

    func pairingState(_ id: String) async throws -> PairingAnswer {
        try await get("/devices/pairing/\(encodedID(id))", timeout: Self.refreshTimeout)
    }

    func cancelPairing(_ id: String) async throws {
        _ = try await delete("/devices/pairing/\(encodedID(id))")
    }

    /// `PUT /connections/{id}/key` with the check flag (G50): 422 = refused (nothing saved), 503 = unreachable — the
    /// caller then offers "Save without checking", which resends with `check: false`.
    func saveKey(_ id: String, key: String, check: Bool) async throws -> ConnectionStatus {
        try await put("/connections/\(encodedID(id))/key", body: ["key": key, "check": check])
    }

    /// `GET /agent-api/tokens` (G213) — machine-global, outside every bank; not a Store domain.
    func fetchAgentTokens() async throws -> [AgentToken] {
        struct Answer: Decodable { var tokens: [AgentToken] }
        let answer: Answer = try await get("/agent-api/tokens", timeout: Self.refreshTimeout)
        return answer.tokens
    }

    func createAgentToken(name: String) async throws -> AgentTokenCreated {
        try await post("/agent-api/tokens", body: ["name": name])
    }

    func revokeAgentToken(_ id: String) async throws {
        _ = try await delete("/agent-api/tokens/\(encodedID(id))")
    }

    // MARK: - Generic Helpers

    /// `timeout` overrides Foundation's 60 s default for this one request.
    /// Only the refresh path passes it (see `refreshTimeout`); everything else
    /// keeps the default so a slow-but-succeeding call is not cut short.
    private func get<T: Decodable>(_ path: String, timeout: TimeInterval? = nil) async throws -> T {
        var request = makeRequest(path, method: "GET", json: false)
        if let timeout { request.timeoutInterval = timeout }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
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
        var request = makeRequest(path, method: "POST")
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }

        let (data, response) = try await deliver(request, path: path)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }
        return try decoder.decode(T.self, from: data)
    }

    private func postData<T: Decodable>(_ path: String, json: Data) async throws -> T {
        var request = makeRequest(path, method: "POST")
        request.httpBody = json
        let (data, response) = try await deliver(request, path: path)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }
        return try decoder.decode(T.self, from: data)
    }

    private func putData<T: Decodable>(_ path: String, json: Data) async throws -> T {
        var request = makeRequest(path, method: "PUT")
        request.httpBody = json
        let (data, response) = try await deliver(request, path: path)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }
        return try decoder.decode(T.self, from: data)
    }

    @discardableResult
    private func post(_ path: String, body: [String: Any]? = nil) async throws -> Data {
        var request = makeRequest(path, method: "POST")
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }

        let (data, response) = try await deliver(request, path: path)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }
        return data
    }

    /// G181 phase 3 — a POST, and for a reader's post on a server the outbox's door: when no answer comes (the server
    /// is away) or the server fails (5xx), the bytes wait in `ReaderOutbox` and the caller hears
    /// `ServerLinkError.queuedOffline` — a failure, so the reader keeps its cursor and reads again, while the waiting
    /// copy goes first when the server answers (`flushOutbox`). Every other request is sent exactly as before.
    private func deliver(_ request: URLRequest, path: String) async throws -> (Data, URLResponse) {
        let queues = connection.isServer && ReaderOutbox.queues(path)
        // Review fix — never ahead of an older post on the same route and memory: a reader's snapshot (bookmarks,
        // tabs, tab groups…) replayed after a newer one would put the server back to the older state, and the reader,
        // having landed the newer one, would not send it again. The older ones go first; if any still waits, this
        // one waits behind it.
        if queues, await waitingAhead(request, path: path), await keep(request, path: path) {
            throw ServerLinkError.queuedOffline
        }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch let error as URLError where queues && error.code != .cancelled {
            // A stopped run (the person's Cancel, or a bank switch replacing a reader's run, G183(d)) is not the
            // server being away: its post never waits here under the memory it left (`keep` refuses too).
            if await keep(request, path: path) { throw ServerLinkError.queuedOffline }
            throw error
        }
        if queues, let http = response as? HTTPURLResponse, (500...599).contains(http.statusCode),
           await keep(request, path: path) {
            throw ServerLinkError.queuedOffline
        }
        return (data, response)
    }

    private func waitingAhead(_ request: URLRequest, path: String) async -> Bool {
        let method = request.httpMethod ?? "POST"
        let bank = request.value(forHTTPHeaderField: BankScope.header)
        let base = baseURL
        let same: @Sendable (ReaderOutbox.Entry) -> Bool = {
            $0.method == method && $0.path == path && $0.bank == bank && ReaderOutbox.isFor($0, base: base)
        }
        guard await outbox.has(where: same) else { return false }
        await flushOutbox(matching: same)
        return await outbox.has(where: same)
    }

    private func keep(_ request: URLRequest, path: String) async -> Bool {
        guard let body = request.httpBody, !Task.isCancelled else { return false }
        let stored = try? await outbox.put(method: request.httpMethod ?? "POST", path: path, body: body,
                                           bank: request.value(forHTTPHeaderField: BankScope.header),
                                           bankId: request.value(forHTTPHeaderField: BankScope.idHeader),
                                           base: baseURL)
        return stored == true
    }

    /// Send what the readers left waiting while the server was away, oldest first, each signed now and named for the
    /// memory it was read for. Called when the Store hears the server again. Server mode only.
    @discardableResult
    func flushOutbox() async -> ReaderOutbox.FlushResult { await flushOutbox(matching: { _ in true }) }

    /// One route's waiting posts only (`waitingAhead`).
    @discardableResult
    func flushOutbox(matching matches: @escaping @Sendable (ReaderOutbox.Entry) -> Bool) async
        -> ReaderOutbox.FlushResult {
        guard connection.isServer else { return ReaderOutbox.FlushResult() }
        // G202 (D2): only the posts read for THIS server go; each names the bank and the id it was read for.
        return await outbox.flush(for: baseURL, where: matches) { entry in
            var request = await self.makeRequest(entry.path, method: entry.method)
            if let bank = entry.bank { request.setValue(bank, forHTTPHeaderField: BankScope.header) }
            request.setValue(entry.bankId, forHTTPHeaderField: BankScope.idHeader)
            request.httpBody = entry.body
            guard let (_, response) = try? await self.session.data(for: request),
                  let http = response as? HTTPURLResponse else { return nil }
            return http.statusCode
        }
    }

    /// Generic DELETE-with-JSON-body helper (`/sources/feeds` unsubscribe is the
    /// only caller today). Mirrors the `post(_:body:) -> Data` shape.
    @discardableResult
    private func delete(_ path: String, body: [String: Any]? = nil) async throws -> Data {
        var request = makeRequest(path, method: "DELETE")
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }
        return data
    }

    private func put<T: Decodable>(_ path: String, body: [String: Any]? = nil) async throws -> T {
        var request = makeRequest(path, method: "PUT")
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
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

// MARK: - Sync engine support (conditional GETs, version vector, SSE)

extension APIClient {
    /// Conditional GET. Sends `If-None-Match` when we hold an etag and reports
    /// a 304 as `notModified` (value nil) so the caller keeps its snapshot.
    func getConditional<T: Decodable>(_ path: String, etag: String?) async throws -> Conditional<T> {
        var request = makeRequest(path, method: "GET", json: false)
        // `session`'s own configuration already disables `URLCache` and
        // forces `.reloadIgnoringLocalCacheData` for every request this
        // client makes — see the `session` property. Nothing extra to set
        // here; we still layer our own conditional-GET caching on top via
        // `etag` / `Snapshot` / `SnapshotCache`.
        if let etag, !etag.isEmpty { request.setValue(etag, forHTTPHeaderField: "If-None-Match") }
        request.timeoutInterval = Self.refreshTimeout
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        if http.statusCode == 304 { return Conditional(value: nil, etag: etag, notModified: true) }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            throw APIError.httpError(http.statusCode, String(data: data, encoding: .utf8) ?? "Unknown error")
        }
        do {
            return Conditional(
                value: try decoder.decode(T.self, from: data),
                etag: http.value(forHTTPHeaderField: "ETag"),
                notModified: false
            )
        } catch {
            throw APIError.decodingError("\(error)")
        }
    }
}

extension APIClient: SyncAPI {
    func fetchGraph(etag: String?) async throws -> Conditional<GraphResponse> {
        try await getConditional("/graph", etag: etag)
    }

    func fetchInbox(etag: String?) async throws -> Conditional<[InboxItem]> {
        try await getConditional("/inbox", etag: etag)
    }

    /// Same rule as every other conditional fetch: a 404 is "no such endpoint",
    /// not "no banks". An empty roster here would overwrite the real one *and*
    /// persist it under `_roster`, so the dropdown would come up empty on the
    /// next launch too.
    func fetchBanks(etag: String?) async throws -> Conditional<BanksResponse> {
        do {
            let answer: Conditional<BanksResponse> = try await getConditional("/banks", etag: etag)
            noteBankIds(answer.value)
            if answer.value == nil, connection.isServer, bankIds.isEmpty {
                // A roster cached from an earlier launch (304) carries no ids this client has heard: ask once in full.
                noteBankIds(try? await get("/banks") as BanksResponse)
            }
            return answer
        } catch APIError.httpError(404, _) {
            return .unavailable(etag: etag)
        }
    }

    func fetchSources(etag: String?) async throws -> Conditional<[MediaFeedItem]> {
        do {
            let c: Conditional<SourceListResponse> = try await getConditional("/sources?sort=relevance", etag: etag)
            return c.map(\.items)
        } catch APIError.httpError(404, _) {
            return .unavailable(etag: etag)
        }
    }

    func fetchChannels(etag: String?) async throws -> Conditional<[SourceChannel]> {
        do {
            let c: Conditional<SourceChannelsResponse> = try await getConditional("/sources/channels", etag: etag)
            return c.map(\.channels)
        } catch APIError.httpError(404, _) {
            return .unavailable(etag: etag)
        }
    }

    func fetchFeeds(etag: String?) async throws -> Conditional<[FeedSubscription]> {
        do {
            let c: Conditional<FeedListResponse> = try await getConditional("/sources/feeds", etag: etag)
            return c.map(\.feeds)
        } catch APIError.httpError(404, _) {
            return .unavailable(etag: etag)
        }
    }

    func fetchCalendars(etag: String?) async throws -> Conditional<[CalendarSubscription]> {
        do {
            let c: Conditional<CalendarListResponse> = try await getConditional("/sources/calendars", etag: etag)
            return c.map(\.calendars)
        } catch APIError.httpError(404, _) {
            return .unavailable(etag: etag)
        }
    }

    func fetchContributors(etag: String?) async throws -> Conditional<[Contributor]> {
        do {
            let c: Conditional<ContributorsResponse> = try await getConditional("/contributors", etag: etag)
            return c.map(\.contributors)
        } catch APIError.httpError(404, _) {
            return .unavailable(etag: etag)
        }
    }

    func fetchOrigins(etag: String?) async throws -> Conditional<[OriginStat]> {
        do {
            let c: Conditional<OriginsResponse> = try await getConditional("/origins", etag: etag)
            return c.map(\.origins)
        } catch APIError.httpError(404, _) {
            return .unavailable(etag: etag)
        }
    }

    /// G124 — `GET /sources/overview`. A 404 means the backend predates the
    /// endpoint: keep whatever snapshot the page already has rather than
    /// blanking the grid.
    /// G61 (owner 2026-10-26) — `GET /sources/where-to-check`: every page's sources the person and their agents added.
    /// Not a Store domain: `AddedSourcesModel` keeps it in memory with this ETag. An older backend's 404 reads as empty.
    func fetchWhereToCheck(etag: String?) async throws -> Conditional<AddedSourcesResponse> {
        do {
            return try await getConditional("/sources/where-to-check", etag: etag)
        } catch APIError.httpError(404, _) {
            return Conditional(value: AddedSourcesResponse(items: [], total: 0), etag: nil, notModified: false)
        }
    }

    func fetchSourcesOverview(etag: String?) async throws -> Conditional<[SourceOverview]> {
        do {
            let c: Conditional<SourceOverviewResponse> = try await getConditional("/sources/overview", etag: etag)
            return c.map(\.sources)
        } catch APIError.httpError(404, _) {
            return .unavailable(etag: etag)
        }
    }

    /// `/connections` has no ETag support server-side yet; `getConditional`
    /// simply never sees a 304 and this behaves as a plain GET.
    func fetchConnections(etag: String?) async throws -> Conditional<[ConnectionStatus]> {
        do {
            let c: Conditional<ConnectionsResponse> = try await getConditional("/connections", etag: etag)
            return c.map(\.connections)
        } catch APIError.httpError(404, _) {
            return .unavailable(etag: etag)
        }
    }

    /// Last-resort fallback for `fetchConsumption` when `/stats` comes back
    /// 304 and there is no `current` bundle to reuse instead (the very first
    /// fetch can't 304 at all, so in practice this only fires if the caller
    /// passes `current: nil`) — `ConsumptionStats` has no custom initializer,
    /// only `init(from decoder:)`, so build it by decoding its own tolerant
    /// defaults from an empty object.
    private static let emptyConsumptionStats: ConsumptionStats =
        // swiftlint:disable:next force_try — every field of `init(from:)` is
        // tolerant of a missing key, so decoding "{}" can never throw.
        try! JSONDecoder().decode(ConsumptionStats.self, from: Data("{}".utf8))

    /// Fans out to all six `/consumption/*` endpoints for the Store's
    /// default view (range "month", 53-week calendar) and folds them into one
    /// `ConsumptionBundle`. Only `/summary`, `/calendar` and `/stats` carry a
    /// server-side ETag (see `api/routers/consumption.py`) — `/connections`,
    /// `/harness` and `/feedback` are always refetched. `/feedback` is fetched
    /// unconditionally and a 404 there means only that section is missing
    /// (older backend), never that the dashboard is.
    ///
    /// A 304 on any of the three ETag'd endpoints must only short-circuit
    /// *that* section, never the whole bundle: `/connections`/`/harness` are
    /// freshly polled on every single call (a 304 there is impossible), so
    /// discarding the response outright whenever the other three happened to
    /// be unchanged — the old behaviour — silently dropped real, new
    /// connections/harness data on the floor (worst case: on every app
    /// bootstrap, since the reconcile fetch typically lands right after the
    /// cache-hydrated etags were already current). Each 304'd section falls
    /// back to `current`'s matching section instead, so the merged bundle is
    /// always complete and this always returns a value (`notModified` is
    /// only ever `true` via the 404 branch below, i.e. "no dashboard at
    /// all" — not "nothing new"). The combined etag is the three sub-etags
    /// pipe-joined; a 404 on any endpoint is treated as "this backend
    /// doesn't ship the dashboard yet", not an empty payload.
    func fetchConsumption(etag: String?, current: ConsumptionBundle?) async throws -> Conditional<ConsumptionBundle> {
        let range = "month"
        let weeks = 53
        let rawParts = (etag ?? "").components(separatedBy: "|")
        let parts: [String?] = (0..<3).map { i in
            guard i < rawParts.count, !rawParts[i].isEmpty else { return nil }
            return rawParts[i]
        }
        do {
            async let s: Conditional<ConsumptionSummary> = getConditional("/consumption/summary?range=\(range)", etag: parts[0])
            async let c: Conditional<ConsumptionCalendar> = getConditional("/consumption/calendar?weeks=\(weeks)", etag: parts[1])
            async let st: Conditional<ConsumptionStats> = getConditional("/consumption/stats?range=\(range)", etag: parts[2])
            async let conn: ConsumptionConnections = get("/consumption/connections?range=\(range)")
            async let h: HarnessStats = get("/consumption/harness")
            async let fb: ConsumptionFeedback? = {
                do { return try await self.fetchConsumptionFeedback(range: range) }
                catch APIError.httpError(404, _) { return nil }
            }()
            let (summaryResult, calendarResult, statsResult, connections, harness, feedback) = try await (s, c, st, conn, h, fb)
            // Typed one at a time: as nested `??` chains in one literal these sat near the type checker's limit.
            let summary: ConsumptionSummary = summaryResult.value ?? current?.summary ?? ConsumptionSummary()
            let calendar: ConsumptionCalendar = calendarResult.value ?? current?.calendar
                ?? ConsumptionCalendar(days: [], weeks: weeks)
            let stats: ConsumptionStats = statsResult.value ?? current?.stats ?? Self.emptyConsumptionStats
            let bundle = ConsumptionBundle(
                summary: summary,
                calendar: calendar,
                stats: stats,
                connections: connections,
                harness: harness,
                feedback: feedback
            )
            let summaryEtag: String = summaryResult.etag ?? parts[0] ?? ""
            let calendarEtag: String = calendarResult.etag ?? parts[1] ?? ""
            let statsEtag: String = statsResult.etag ?? parts[2] ?? ""
            let newEtag: String = [summaryEtag, calendarEtag, statsEtag].joined(separator: "|")
            return Conditional(value: bundle, etag: newEtag, notModified: false)
        } catch APIError.httpError(404, _) {
            return .unavailable(etag: etag)
        }
    }

    /// `GET /sync/version` → the current component version vector.
    func fetchSyncVersion() async throws -> VersionVector {
        try await get("/sync/version")
    }

    // MARK: Writes (§5.4)
    //
    // `subscribeFeed`/`unsubscribeFeed`/`subscribeCalendar`/
    // `unsubscribeCalendar`/`activateBank`/`triggerSleep`/`setUseForSleep`
    // already match their `SyncAPI` requirements exactly, so they satisfy the
    // protocol from their primary declarations above. The five below only exist to give the
    // protocol's connection/inbox names a home; each forwards verbatim.

    func resolveInbox(id: String, action: String, answer: String?,
                      optionKey: String?, remindDays: Int?,
                      mergeTarget: String?, mergeSurvivor: String?) async throws {
        try await resolveInboxItem(id: id, action: action, answer: answer,
                                   optionKey: optionKey, remindDays: remindDays,
                                   mergeTarget: mergeTarget, mergeSurvivor: mergeSurvivor)
    }

    func resolveInbox(id: String, action: String, answer: String?,
                      optionKey: String?, remindDays: Int?,
                      mergeTarget: String?, mergeSurvivor: String?,
                      quote: String?, relayedBy: String?, sessionId: String?) async throws {
        try await resolveInboxItem(id: id, action: action, answer: answer, optionKey: optionKey, remindDays: remindDays,
                                   mergeTarget: mergeTarget, mergeSurvivor: mergeSurvivor, quote: quote,
                                   relayedBy: relayedBy, sessionId: sessionId)
    }

    func setConnectionTier(_ id: String, tier: String?) async throws -> ConnectionStatus {
        try await setTier(id, tier: tier)
    }

    func setConnectionKey(_ id: String, key: String) async throws -> ConnectionStatus {
        try await setKey(id, key: key)
    }

    func removeConnectionKey(_ id: String) async throws -> ConnectionStatus {
        try await removeKey(id)
    }

    func logoutConnection(_ id: String) async throws -> ConnectionStatus {
        try await logout(id)
    }

    /// Opens the long-lived `GET /sync/events` SSE stream. The 1-hour timeout
    /// is a backstop only — the server pings every 15 s, and `SyncEngine`
    /// reconnects with backoff whenever the sequence ends for any reason.
    func syncEventLines() async throws -> (AsyncThrowingStream<String, any Error>, HTTPURLResponse) {
        var request = makeRequest("/sync/events", method: "GET", json: false)
        // `timeoutInterval` is an *idle* timeout — time waiting for the next
        // byte, not total connection lifetime — so a stream that keeps
        // trickling data lives indefinitely. 3600 is set explicitly (a
        // per-request value overrides any session-wide default) and the
        // backend's `PING_SECONDS = 15` keeps the gap between bytes far below
        // it. If that ping cadence is ever raised past this interval, the
        // stream would start dying on idle: see `api/routers/sync.py`.
        request.timeoutInterval = 3600
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        let (bytes, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        guard http.statusCode == 200 else {
            if http.statusCode == 401 { Self.invalidateToken() }
            throw APIError.httpError(http.statusCode, "sync/events")
        }
        // NOT `bytes.lines`: Foundation's AsyncLineSequence swallows empty
        // lines, and an empty line is what terminates an SSE frame.
        return (SSELineSplitter.lines(from: bytes), http)
    }
}

// MARK: - One intake (Track I T5)

extension APIClient: IntakeAPI {
    private static func bankQuery(_ bank: String?) -> String {
        guard let bank else { return "" }
        // `.urlQueryAllowed` keeps `&`, `=` and `+`, which would split or
        // re-read the one parameter; a bank slug never has them, but a name
        // typed into "New memory…" is not a slug until the backend says so.
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "&=+?#")
        return "?bank=" + (bank.addingPercentEncoding(withAllowedCharacters: allowed) ?? bank)
    }

    /// `POST /intake/sniff` — stages nothing (G71 §4.3); safe on every drop.
    func sniffIntake(fileURL: URL, bank: String?, name: String?, includeHistory: Bool) async throws -> IntakeSniff {
        let query = Self.bankQuery(bank)
        let history = includeHistory ? (query.isEmpty ? "?" : "&") + "include_history=true" : ""
        return try await uploadMultipart(path: "/intake/sniff" + query + history, fileURL: fileURL, filename: name)
    }

    /// `POST /intake/import` — 200 with counts, or 202 with `job` (Track I T2b).
    func importIntake(fileURL: URL, bank: String?) async throws -> IntakeImportResponse {
        try await uploadMultipart(path: "/intake/import" + Self.bankQuery(bank), fileURL: fileURL)
    }

    func intakeJob(id: String) async throws -> IntakeJobStatus { try await get("/intake/jobs/\(id)") }

    /// A `kind: saved` file commits through the path that previewed it (R-IA32).
    func uploadSaved(fileURL: URL, name: String?, includeHistory: Bool) async throws -> UploadResponse {
        try await uploadMultipart(path: "/sources/upload" + (includeHistory ? "?include_history=true" : ""),
                                  fileURL: fileURL, filename: name)
    }

    /// `GET /agents/wiring` (Track I T3) — read-only: which agents are wired
    /// and the exact argv `AgentConnect` may run after the person's click.
    func fetchAgentWiring() async throws -> AgentWiringResponse { try await get("/agents/wiring") }

    /// Round 4 C8 (R-AG5) — `GET /agents/live`: which agents Cicada has seen connect, engine-free and
    /// subprocess-free on the server, so the Agents page can poll it every few seconds (R-AG15).
    func fetchAgentLive() async throws -> AgentLiveResponse { try await get("/agents/live") }

    /// Report a problem (tester readiness, 2026-10-26): the backend's half of the report, plain text, already redacted
    /// (`api/services/diagnostics.py`). Not a Store domain: fetched when the sheet opens, held only by it.
    func fetchDiagnosticsReport(lines: Int = 200) async throws -> String {
        let request = makeRequest("/diagnostics/report?lines=\(lines)", method: "GET", json: false)
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            throw APIError.httpError(http.statusCode, String(data: data, encoding: .utf8) ?? "")
        }
        return String(decoding: data, as: UTF8.self)
    }

    /// Round-4 D5 (C5) — `GET /agents/setup?harness=<id>`: the prompt a person pastes into their agent so it
    /// installs Cicada itself. A 404 (an unknown harness, or a backend from before C5) throws, and the caller
    /// shows nothing new. The id is escaped like `fetchRecentConversations`' filters, so no value can smuggle a
    /// second query key.
    func fetchAgentSetup(harness: String) async throws -> AgentSetupPrompt {
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "&+=?/#")
        return try await get("/agents/setup?harness=\(harness.addingPercentEncoding(withAllowedCharacters: allowed) ?? harness)")
    }
}

/// G133 / G134 — `LocalSourceWatcher` talks to the backend through this seam.
extension APIClient: LocalSourcesAPI {}

// MARK: - Projects (G141 PJ-5) — the person's five writes

extension APIClient {
    /// `/projects/<id>/<tail…>`, every component encoded the way `provenancePath` encodes an id: a slug or a claim id
    /// never reshapes the URL.
    nonisolated static func projectPath(_ id: String, _ tail: String...) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        return "/projects/" + ([id] + tail).map { $0.addingPercentEncoding(withAllowedCharacters: allowed) ?? $0 }
            .joined(separator: "/")
    }

    func addProjectMilestone(project: String, name: String, target: String?) async throws -> ProjectWriteResponse {
        var body: [String: Any] = ["name": name]
        if let target { body["target"] = target }
        return try await post(Self.projectPath(project, "milestones"), body: body)
    }

    func changeProjectMilestone(project: String, slug: String, change: MilestoneChange) async throws -> ProjectWriteResponse {
        try await patch(Self.projectPath(project, "milestones", slug), body: change.body)
    }

    func logProjectHappening(project: String, text: String, status: String, when: String?) async throws -> ProjectWriteResponse {
        var body: [String: Any] = ["text": text, "status": status]
        if let when { body["when"] = when }
        return try await post(Self.projectPath(project, "happenings"), body: body)
    }

    func settleProjectThread(project: String, claimId: String, status: String) async throws -> ProjectWriteResponse {
        try await post(Self.projectPath(project, "threads", claimId), body: ["status": status])
    }

    func withdrawProjectHappening(project: String, claimId: String) async throws -> ProjectWriteResponse {
        try await post(Self.projectPath(project, "withdraw"), body: ["claimId": claimId])
    }

    /// Projects v2 (ruling 45) — start a project, take or leave a suggestion, the header, a tie, an influence.
    func sendProjectChange(_ change: ProjectChange) async throws -> ProjectOwnershipResponse {
        let route = change.route
        if route.method == "PATCH" { return try await patch(route.path, body: route.body) }
        return try await post(route.path, body: route.body)
    }

    /// The PATCH twin of `put` — `PATCH /projects/{id}/milestones/{slug}` is the one PATCH the app sends.
    private func patch<T: Decodable>(_ path: String, body: [String: Any]) async throws -> T {
        var request = makeRequest(path, method: "PATCH")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            throw APIError.httpError(http.statusCode, String(data: data, encoding: .utf8) ?? "Unknown error")
        }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decodingError("\(error)")
        }
    }
}

// MARK: - Backlog (G150) — the person's three writes

extension APIClient {
    func addBacklogItem(project: String, title: String, description: String) async throws -> BacklogItem {
        var body: [String: Any] = ["title": title]
        if !description.isEmpty { body["description"] = description }
        return try await post(Self.projectPath(project, "backlog"), body: body)
    }

    func addBacklogNote(project: String, item: String, note: String, status: String?) async throws -> BacklogItem {
        var body: [String: Any] = ["note": note]
        if let status { body["status"] = status }
        return try await post(Self.backlogPath(project, item, "notes"), body: body)
    }

    func updateBacklogItem(project: String, item: String, change: BacklogChange) async throws -> BacklogItem {
        try await patch(Self.backlogPath(project, item), body: change.body)
    }
}

// MARK: - Videos (G162) — the queue's writes

extension APIClient {
    func putVideo<T: Decodable>(_ path: String, body: [String: Any]) async throws -> T {
        try await put(path, body: body)
    }

    func postVideo<T: Decodable>(_ path: String, body: [String: Any]) async throws -> T {
        try await post(path, body: body)
    }

    func deleteVideo(_ path: String) async throws {
        _ = try await delete(path)
    }
}

// MARK: - Design taste (2026-10-14) — looks, on the pages of the things they show (2026-10-20)

/// The looks' reads and the person's writes (`api/routers/design.py`). A protocol so `LooksCache` is tested
/// against a fake, the `BacklogAPI` way.
protocol DesignAPI: Sendable {
    func fetchDesignBoard(etag: String?) async throws -> Conditional<DesignBoard>
    func fetchDesignRef(id: String, etag: String?) async throws -> Conditional<DesignRef>
    func saveDesignRef(_ upload: DesignUpload) async throws -> DesignRef
    func deleteDesignRef(id: String) async throws
    func searchDesign(query: String?, image: Data?, ext: String?) async throws -> DesignSearchResult
    func installImageModel() async throws
    /// Put a look on a page, or take it off one (`entity` nil): `PUT /design/{id}/entity`.
    func attachDesignRef(id: String, entity: String?) async throws -> DesignRef
    /// The looks most like one (`GET /design/{id}/similar`), itself left out.
    func similarDesign(id: String) async throws -> DesignSearchResult
    /// A website link pasted on a page: the link is saved (`POST /sources/save`), then its look is asked of the
    /// person's own agent for that page (`POST /explore/look` with `subject`) — the site-capture path (G166).
    func lookFromLink(url: String, subject: String) async throws -> ExploreLookResponse
    /// The person's own words on a look — its name, its link, what they liked (`PATCH /design/{id}`).
    func editDesignRef(id: String, title: String, url: String, note: String) async throws -> DesignRef
}

extension DesignAPI {
    func editDesignRef(id: String, title: String, url: String, note: String) async throws -> DesignRef {
        throw APIError.serverUnreachable
    }
    func attachDesignRef(id: String, entity: String?) async throws -> DesignRef { throw APIError.serverUnreachable }
    func similarDesign(id: String) async throws -> DesignSearchResult {
        DesignSearchResult(results: [], mode: "none", missing: [])
    }
    func lookFromLink(url: String, subject: String) async throws -> ExploreLookResponse {
        throw APIError.serverUnreachable
    }
}

extension APIClient: DesignAPI {
    nonisolated static func designPath(_ id: String, _ tail: String...) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        return "/design/" + ([id] + tail).map { $0.addingPercentEncoding(withAllowedCharacters: allowed) ?? $0 }
            .joined(separator: "/")
    }

    func fetchDesignBoard(etag: String?) async throws -> Conditional<DesignBoard> {
        try await getConditional("/design", etag: etag)
    }

    func fetchDesignRef(id: String, etag: String?) async throws -> Conditional<DesignRef> {
        try await getConditional(Self.designPath(id), etag: etag)
    }

    /// `multipart/form-data`: the image as `image`, every other field as text — nothing the server would have to guess.
    private func designMultipart(_ path: String, fields: [(String, String)], image: Data?, ext: String?) async throws -> Data {
        var request = makeRequest(path, method: "POST", json: false)
        let boundary = UUID().uuidString
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        var body = Data()
        for (name, value) in fields {
            body.append("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n".data(using: .utf8)!)
            body.append(value.data(using: .utf8)!)
            body.append("\r\n".data(using: .utf8)!)
        }
        if let image {
            let kind = ext == "png" ? "png" : "jpg"
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"image\"; filename=\"look.\(kind)\"\r\n".data(using: .utf8)!)
            body.append("Content-Type: \(kind == "png" ? "image/png" : "image/jpeg")\r\n\r\n".data(using: .utf8)!)
            body.append(image)
            body.append("\r\n".data(using: .utf8)!)
        }
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body
        let (reply, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            throw APIError.httpError(http.statusCode, String(data: reply, encoding: .utf8) ?? "Unknown error")
        }
        return reply
    }

    func saveDesignRef(_ upload: DesignUpload) async throws -> DesignRef {
        var fields: [(String, String)] = [("via", upload.via)]
        if let url = upload.url, !url.isEmpty { fields.append(("url", url)) }
        if let title = upload.title, !title.isEmpty { fields.append(("title", title)) }
        if let note = upload.note, !note.isEmpty { fields.append(("note", note)) }
        if let entity = upload.entity, !entity.isEmpty { fields.append(("entity", entity)) }
        let reply = try await designMultipart("/design", fields: fields, image: upload.image, ext: upload.ext)
        do { return try decoder.decode(DesignRef.self, from: reply) } catch { throw APIError.decodingError("\(error)") }
    }

    func deleteDesignRef(id: String) async throws {
        _ = try await delete(Self.designPath(id))
    }

    func searchDesign(query: String?, image: Data?, ext: String?) async throws -> DesignSearchResult {
        var fields: [(String, String)] = []
        if let query, !query.isEmpty { fields.append(("query", query)) }
        let reply = try await designMultipart("/design/search", fields: fields, image: image, ext: ext)
        do { return try decoder.decode(DesignSearchResult.self, from: reply) } catch {
            throw APIError.decodingError("\(error)")
        }
    }

    /// The image model's own click (`POST /embeddings/install` with `part: vision`, 202).
    func installImageModel() async throws {
        _ = try await post("/embeddings/install", body: ["model": "google/embeddinggemma-2:768", "part": "vision"]) as Data
    }

    func attachDesignRef(id: String, entity: String?) async throws -> DesignRef {
        try await put(Self.designPath(id, "entity"), body: ["entity": entity.map { $0 as Any } ?? NSNull()])
    }

    func similarDesign(id: String) async throws -> DesignSearchResult {
        try await get(Self.designPath(id, "similar"))
    }

    func editDesignRef(id: String, title: String, url: String, note: String) async throws -> DesignRef {
        try await patch(Self.designPath(id), body: ["title": title, "url": url, "note": note])
    }

    func lookFromLink(url: String, subject: String) async throws -> ExploreLookResponse {
        try await saveSource(url: url)   // already saved is a quiet duplicate; a refusal says why
        return try await post("/explore/look", body: ["url": url, "subject": subject])
    }
}

/// G191 — the panel's two calls, live.
extension APIClient: SavedWhyAPI {}

// MARK: - Links show as what they are (owner rulings 2026-10-14)

/// The person's own page edit: `POST /entities/{id}/edits`, the same body as `cicada_edit_page`.
struct PageEditAnswer: Decodable, Equatable, Sendable {
    var entityId: String
    var changes: [String]
    var sections: [String]
    var pinned: Int
}

extension APIClient {
    /// A page's link facts, `GET /entities/{id}/links` (ETagged, on demand — `LinkFactsCache`).
    func fetchEntityLinks(entityId: String, etag: String?) async throws -> Conditional<PageLinkFacts> {
        try await getConditional(Self.provenancePath("/entities", entityId, "/links"), etag: etag)
    }

    // MARK: G227 follow-up — merge two pages, split one, undo either (`page_joins`)

    /// Fold `entityId` into `into` (the page that stays).
    func mergePage(entityId: String, into: String) async throws -> PageJoinAnswer {
        try await post(Self.provenancePath("/entities", entityId, "/merge"), body: ["into": into])
    }

    /// Take a merge or split back, from the page's History.
    func undoJoin(entityId: String, commitHash: String) async throws -> PageJoinAnswer {
        try await post(Self.provenancePath("/entities", entityId, "/history/\(commitHash)/undo"))
    }

    /// One exact-words edit of a page as the person, pinned so Sleep's next rewrite keeps it (G198's corrections).
    /// The link-view switcher's door: `old` is the link's token, `new` the same link with its view word.
    func editPage(entityId: String, reason: String, old: String, new: String) async throws -> PageEditAnswer {
        try await post(Self.provenancePath("/entities", entityId, "/edits"),
                       body: ["reason": reason, "edits": [["old": old, "new": new, "all": true, "pin": true]]])
    }
}
