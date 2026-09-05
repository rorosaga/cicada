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

/// Tolerant of both ISO-8601-with-fractional-seconds and plain ISO-8601, plus
/// the naive-local shape the bank's own MCP capture path writes (M1's
/// companion fix on the client side — see the naive-local branch below).
/// A timestamp that fails every parse returns `nil` rather than being
/// silently coerced into "now" or "the epoch".
func parseEpisodeTimestamp(_ raw: String) -> Date? {
    guard !raw.isEmpty else { return nil }
    let withFractional = ISO8601DateFormatter()
    withFractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let d = withFractional.date(from: raw) { return d }
    let plain = ISO8601DateFormatter()
    plain.formatOptions = [.withInternetDateTime]
    if let d = plain.date(from: raw) { return d }

    // Devin PR #27 round 1, finding 6: both attempts above REQUIRE a `Z`/
    // offset designator — `ISO8601DateFormatter`'s `.withInternetDateTime`
    // demands one and returns `nil` without it. But this bank's own MCP
    // capture path writes naive LOCAL time (`datetime.now().isoformat()`,
    // no explicit tz) — the same both-shapes reality the backend's
    // `sleep_debt._parse_episode_timestamp` hit (M1). Interpreted in the
    // LOCAL calendar (`TimeZone.current`), mirroring how the backend
    // compares a naive value directly against `datetime.now()` (also
    // naive-local) rather than assuming UTC.
    let naiveWithFractional = DateFormatter()
    naiveWithFractional.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"
    naiveWithFractional.timeZone = .current
    naiveWithFractional.locale = Locale(identifier: "en_US_POSIX")
    if let d = naiveWithFractional.date(from: raw) { return d }

    let naive = DateFormatter()
    naive.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
    naive.timeZone = .current
    naive.locale = Locale(identifier: "en_US_POSIX")
    return naive.date(from: raw)
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
