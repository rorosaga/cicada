import SwiftUI

// MARK: - Pure grouping (G106 amendment)

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

/// The three age buckets the breakdown groups by. Deliberately coarse
/// (three buckets, not a histogram) — this is a "what's piling up and how
/// stale" glance, not a report.
enum SleepAgeBucket: String, CaseIterable, Identifiable {
    case today = "Today"
    case thisWeek = "This week"
    case older = "Older"
    var id: String { rawValue }
}

struct AgeBucketCount: Identifiable, Equatable {
    let bucket: SleepAgeBucket
    let count: Int
    var id: String { bucket.id }
}

/// Tolerant of both ISO-8601-with-fractional-seconds and plain ISO-8601 —
/// mirrors `EpisodeRow.shortTimestamp`'s own two-attempt parse in
/// SleepView.swift so the two never disagree about what a given raw
/// timestamp string means. A timestamp that fails both parses counts as
/// `.older` rather than being silently dropped from the total.
func parseEpisodeTimestamp(_ raw: String) -> Date? {
    guard !raw.isEmpty else { return nil }
    let withFractional = ISO8601DateFormatter()
    withFractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let d = withFractional.date(from: raw) { return d }
    let plain = ISO8601DateFormatter()
    plain.formatOptions = [.withInternetDateTime]
    return plain.date(from: raw)
}

/// Pure — `now` injected so bucket boundaries are exercisable exactly, not
/// approximated with `Date()` inside a test's own tolerance window.
func groupEpisodesByAge(_ episodes: [EpisodeQueueItem], now: Date = .now) -> [AgeBucketCount] {
    var counts: [SleepAgeBucket: Int] = [:]
    for ep in episodes {
        let hoursAgo = parseEpisodeTimestamp(ep.timestamp).map { now.timeIntervalSince($0) / 3600 }
        let bucket: SleepAgeBucket
        switch hoursAgo {
        case .some(let h) where h < 24: bucket = .today
        case .some(let h) where h < 24 * 7: bucket = .thisWeek
        default: bucket = .older   // unparseable or >= a week: treat as the stalest bucket
        }
        counts[bucket, default: 0] += 1
    }
    return SleepAgeBucket.allCases.compactMap { b in
        guard let c = counts[b], c > 0 else { return nil }
        return AgeBucketCount(bucket: b, count: c)
    }
}

// MARK: - View

/// The Sleep page's "what's waiting" breakdown — by source (with brand
/// iconography) and by age. Read-only; a projection over whatever
/// `SleepViewModel.queuedEpisodes` last fetched, no fetches of its own.
struct SleepDebtBreakdown: View {
    let episodes: [EpisodeQueueItem]

    private var bySource: [OriginBucket] { groupEpisodesByOrigin(episodes) }
    private var byAge: [AgeBucketCount] { groupEpisodesByAge(episodes) }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text("CATCHING UP ON")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            if episodes.isEmpty {
                Text("Nothing queued.")
                    .font(.system(size: 12))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.vertical, CicadaTheme.spacingSM)
            } else {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    ForEach(bySource) { row in
                        sourceRow(row)
                    }
                }

                Divider().background(CicadaTheme.border).padding(.vertical, CicadaTheme.spacingXS)

                HStack(spacing: CicadaTheme.spacingMD) {
                    ForEach(byAge) { row in
                        ageChip(row)
                    }
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private func sourceRow(_ row: OriginBucket) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: OriginIconography.symbol(for: row.origin))
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(OriginIconography.color(for: row.origin))
                .frame(width: 16)
            Text(OriginIconography.label(for: row.origin))
                .font(.system(size: 12))
                .foregroundStyle(CicadaTheme.textPrimary)
            Spacer()
            Text("\(row.count)")
                .font(.system(size: 12, weight: .semibold, design: .rounded))
                .foregroundStyle(CicadaTheme.textSecondary)
        }
    }

    private func ageChip(_ row: AgeBucketCount) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(row.bucket.rawValue.uppercased())
                .font(.system(size: 9, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(0.8)
            Text("\(row.count)")
                .font(.system(size: 16, weight: .semibold, design: .rounded))
                .foregroundStyle(CicadaTheme.textPrimary)
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(CicadaTheme.surfaceHover)
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }
}
