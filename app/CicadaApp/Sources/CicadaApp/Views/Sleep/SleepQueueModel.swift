import Foundation

// MARK: - Pure grouping (G106 amendment; moved here from the retired
// `SleepDebtBreakdown.swift` — G125 R11: nothing dropped, only renamed).

/// "What Cicada needs to catch up on", by source — one row per distinct
/// `EpisodeQueueItem.origin` in the queue, largest pile first. Reuses
/// `OriginIconography` (extracted from `OriginPill`) for icon/label/color,
/// so a source reads identically here and on the Activity origins strip.
struct OriginBucket: Identifiable, Equatable {
    let origin: String
    let count: Int
    var id: String { origin }
}

/// Pure — no view, no dates — so the grouping/sort is unit-testable without
/// standing up a page. Stable order for ties: first-seen-in-`episodes` wins,
/// so the row order doesn't jitter between calls on unchanged input.
func groupEpisodesByOrigin(_ episodes: [EpisodeQueueItem]) -> [OriginBucket] {
    var counts: [String: Int] = [:]
    var order: [String] = []
    for ep in episodes {
        if counts[ep.origin] == nil { order.append(ep.origin) }
        counts[ep.origin, default: 0] += 1
    }
    return order
        .map { OriginBucket(origin: $0, count: counts[$0] ?? 0) }
        .sorted { $0.count > $1.count }
}

/// The four parsers `parseEpisodeTimestamp` tries, built ONCE. Final review
/// of Track Z (finding 1): the function used to build four fresh formatters
/// per call, and `episodesForOrigin` called it inside its sort comparator —
/// about 2·n·log n formatter builds per sort, measured at 0.60 s for 188
/// episodes in one origin and 2.09 s for 500. The spine popover made that a
/// one-click path that re-ran on every 1 s poll during a cycle. Formatter
/// construction, not parsing, was the cost. `DateFormatter` and
/// `ISO8601DateFormatter` are safe to share for `date(from:)` on macOS 10.9+,
/// and none of these is mutated after this initialiser.
private enum EpisodeTimestampFormatters {
    static let withFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    static let plain: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
    /// `.autoupdatingCurrent`, not `.current`: a cached formatter would
    /// otherwise pin the zone it was built in, and a naive-local timestamp
    /// must keep meaning "the Mac's local time now", as it did when a fresh
    /// formatter read `.current` on every call.
    static let naiveWithFractional: DateFormatter = makeNaive("yyyy-MM-dd'T'HH:mm:ss.SSSSSS")
    static let naive: DateFormatter = makeNaive("yyyy-MM-dd'T'HH:mm:ss")

    private static func makeNaive(_ format: String) -> DateFormatter {
        let f = DateFormatter()
        f.dateFormat = format
        f.timeZone = .autoupdatingCurrent
        f.locale = Locale(identifier: "en_US_POSIX")
        return f
    }
}

/// Tolerant of both ISO-8601-with-fractional-seconds and plain ISO-8601, plus
/// the naive-local shape the bank's own MCP capture path writes (M1's
/// companion fix on the client side — see the naive-local branch below).
/// A timestamp that fails every parse returns `nil` rather than being
/// silently coerced into "now" or "the epoch".
func parseEpisodeTimestamp(_ raw: String) -> Date? {
    guard !raw.isEmpty else { return nil }
    if let d = EpisodeTimestampFormatters.withFractional.date(from: raw) { return d }
    if let d = EpisodeTimestampFormatters.plain.date(from: raw) { return d }

    // Devin PR #27 round 1, finding 6: both attempts above REQUIRE a `Z`/
    // offset designator — `ISO8601DateFormatter`'s `.withInternetDateTime`
    // demands one and returns `nil` without it. But this bank's own MCP
    // capture path writes naive LOCAL time (`datetime.now().isoformat()`,
    // no explicit tz) — the same both-shapes reality the backend's
    // `sleep_debt._parse_episode_timestamp` hit (M1). Interpreted in the
    // LOCAL calendar, mirroring how the backend compares a naive value
    // directly against `datetime.now()` (also naive-local) rather than
    // assuming UTC.
    if let d = EpisodeTimestampFormatters.naiveWithFractional.date(from: raw) { return d }
    return EpisodeTimestampFormatters.naive.date(from: raw)
}

// MARK: - Study rows (G125 R3 — the per-source countdown)

/// One row of the study list — a source, how much of it is queued, how
/// stale the oldest item in it is, and (while a cycle is running) how far
/// Stage 1 has gotten through it. `read`/`total` are `nil` while idle: there
/// is nothing honest to count down when no cycle has claimed this source's
/// episodes yet (R3 — the countdown is Stage 1, and Stage 1 only runs
/// during a cycle).
struct StudyRow: Identifiable, Equatable {
    let origin: String
    let label: String
    let count: Int
    let oldestAge: String?
    let read: Int?
    let total: Int?
    var id: String { origin }
}

/// A pure, clock-injectable age label (R8-adjacent: no view reaches for
/// `Date()` on its own) — deliberately coarser than
/// `RelativeDateTimeFormatter` ("just now" / whole hours / whole days) so
/// the study list's second column reads as a rough sense of staleness, not
/// a running clock.
func ageLabel(hours: Double) -> String {
    if hours < 1 { return "just now" }
    if hours < 48 { return "\(Int(hours))h" }
    return "\(Int(hours / 24))d"
}

/// `ageLabel`'s long form, for sentences (Track Z Z-P21) — the same thresholds
/// in whole words, so "The oldest has waited 3 days." and the list's "3d" can
/// never disagree about the age, only about how much room they have.
func agePhrase(hours: Double) -> String {
    if hours < 1 { return "under an hour" }
    if hours < 48 {
        let h = Int(hours)
        return h == 1 ? "1 hour" : "\(h) hours"
    }
    return "\(Int(hours / 24)) days"
}

/// How long the oldest queued episode has waited, in hours — `nil` for an
/// empty queue or one whose timestamps all fail to parse (never a guess).
func oldestQueuedHours(_ queued: [EpisodeQueueItem], now: Date = .now) -> Double? {
    queued.compactMap { parseEpisodeTimestamp($0.timestamp) }.min().map { now.timeIntervalSince($0) / 3600 }
}

/// The study list's rows: `groupEpisodesByOrigin`'s buckets (largest pile
/// first), each with its oldest episode's age and — only while `running` —
/// the Stage 1 countdown for that source. A source that IS in the full
/// queue but is NOT a key of `queueByOrigin` was left out of this cycle by
/// the episode cap; it still gets a row (so it doesn't vanish from the
/// list), but `total: 0` tells the view to render "next cycle" instead of a
/// bogus "0 of 0" (see `queueByOrigin`'s doc comment on `SleepStatusResponse`).
func studyRows(
    queued: [EpisodeQueueItem],
    queueByOrigin: [String: Int],
    readByOrigin: [String: Int],
    running: Bool,
    now: Date = .now
) -> [StudyRow] {
    let buckets = groupEpisodesByOrigin(queued)
    var oldestByOrigin: [String: Date] = [:]
    for ep in queued {
        guard let date = parseEpisodeTimestamp(ep.timestamp) else { continue }
        if let existing = oldestByOrigin[ep.origin] {
            if date < existing { oldestByOrigin[ep.origin] = date }
        } else {
            oldestByOrigin[ep.origin] = date
        }
    }
    return buckets.map { bucket in
        let oldestAge = oldestByOrigin[bucket.origin].map { ageLabel(hours: now.timeIntervalSince($0) / 3600) }
        return StudyRow(
            origin: bucket.origin,
            label: OriginIconography.label(for: bucket.origin),
            count: bucket.count,
            oldestAge: oldestAge,
            read: running ? (readByOrigin[bucket.origin] ?? 0) : nil,
            total: running ? (queueByOrigin[bucket.origin] ?? 0) : nil
        )
    }
}

// MARK: - One source's queue (hoisted from StudyListCard, Track Z Z0)

/// The queued episodes from one `origin`, newest first; a timestamp that
/// fails every parse sorts last rather than being coerced to "now". Hoisted
/// so the study list's disclosure and a spine's popover (Z6) show the same
/// episodes in the same order.
///
/// Each timestamp is parsed ONCE, then sorted on the parsed key (final
/// review of Track Z, finding 1): parsing inside the comparator cost
/// 2·n·log n parses, and the spine popover calls this from its body.
func episodesForOrigin(_ origin: String, in episodes: [EpisodeQueueItem]) -> [EpisodeQueueItem] {
    episodes
        .filter { $0.origin == origin }
        .map { ($0, parseEpisodeTimestamp($0.timestamp) ?? .distantPast) }
        .sorted { $0.1 > $1.1 }
        .map(\.0)
}
