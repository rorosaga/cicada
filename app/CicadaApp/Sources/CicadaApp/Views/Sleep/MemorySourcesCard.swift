import SwiftUI

// MARK: - The activity window (P2)

/// `SourceOverview.activity` is keyed by **UTC** calendar day (Task 1 / P1), so
/// every window that indexes it is built on a UTC calendar too. Mixing a local
/// window against UTC keys would shift the whole series by a bucket for any
/// reader west of Greenwich; at worst this labels the newest bucket by
/// UTC-today rather than local-today, which is a one-bucket edge effect on an
/// undated sparkline and never a wrong series.
private enum ActivityWindow {
    static let calendar: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "UTC")!
        return c
    }()

    /// The same `yyyy-MM-dd` shape `source_overview._activity_day` writes.
    /// `en_US_POSIX` because a formatter that follows the reader's locale would
    /// stop matching the backend's keys on a non-Gregorian calendar setting.
    static let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.timeZone = TimeZone(identifier: "UTC")
        f.locale = Locale(identifier: "en_US_POSIX")
        return f
    }()

    static func key(daysBefore offset: Int, from today: Date) -> String? {
        guard let date = calendar.date(byAdding: .day, value: -offset, to: today) else { return nil }
        return dayFormatter.string(from: date)
    }
}

/// The sparse `activity` histogram as a **dense** series, oldest first, with a
/// zero for every silent day.
///
/// Dense on purpose: a view that had to special-case "this source has no key
/// for Tuesday" would draw a different chart from one that did not, and the
/// panel's whole claim is that the two marks beside a row are the same reading.
/// A key outside the window is ignored rather than folded into the edge bucket
/// — the keys are absolute dates (R-A16), so a stale payload renders a day
/// SHORT, never a day SHIFTED.
func sparklinePoints(activity: [String: Int], days: Int, today: Date) -> [Int] {
    guard days > 0 else { return [] }
    return (0..<days).map { index in
        // index 0 is the OLDEST bucket, so it sits `days - 1` days back.
        guard let key = ActivityWindow.key(daysBefore: days - 1 - index, from: today) else { return 0 }
        return activity[key] ?? 0
    }
}

/// Captures per 7-day block, oldest first — the four-week rhythm behind the
/// sparkline's day-by-day noise. Summed from the SAME dense day series the
/// sparkline draws, so the two marks on a row can never disagree about a day.
func weekDots(activity: [String: Int], weeks: Int, today: Date) -> [Int] {
    guard weeks > 0 else { return [] }
    let daily = sparklinePoints(activity: activity, days: weeks * 7, today: today)
    return (0..<weeks).map { week in
        daily[(week * 7)..<((week + 1) * 7)].reduce(0, +)
    }
}

// MARK: - One row of the panel

/// One memory source, as the Sleep page's right column draws it: who it is,
/// how much it has ever captured, and the shape of the last month.
///
/// P17 — **two lists, two nouns.** The queue card counts what is `waiting`;
/// this one counts what was `captured`, and the noun is on the row rather than
/// hidden in a tooltip. The two numbers are different facts about different
/// moments and must never look like the same one.
struct MemorySourceRow: Identifiable, Equatable {
    let id: String
    let label: String
    /// The origin id `OriginMark` draws — `SourceOverview.mark`, the same one
    /// the Sources grid uses, so a source looks identical on both pages.
    let mark: String
    let captured: Int
    /// Captures inside `recentWindowDays`, the key this list is ordered by.
    let recentCaptures: Int
    let points: [Int]
    let dots: [Int]

    /// "312 captured" (budget row #13).
    var countLine: String { "\(UsageFormat.count(captured)) captured" }

    /// Two weeks: long enough that one quiet weekend does not reorder the
    /// panel, short enough that "what is feeding memory NOW" is still the
    /// question being answered.
    static let recentWindowDays = 14
    /// The sparkline's window — `source_overview.ACTIVITY_DAYS`, mirrored. A
    /// wider request than the payload carries simply reads as leading zeros.
    static let sparkDays = 30
    static let weeks = 4
    /// Six rows: a glance, not the list. The full grid is one click away.
    static let limit = 6
}

/// The panel's rows, ordered and capped — a **projection** of the
/// `sourcesOverview` domain the `Store` already holds (R-A10: no new fetch, no
/// new endpoint; the same list the hero's "N sources feeding it" tile counts).
///
/// A source with no captures is dropped rather than drawn as a zero: this panel
/// answers "where did memory come from", and a row with no evidence has no
/// answer to give (the same rule the Sources grid follows). Order is recent
/// captures, then lifetime captures, then id — the last term is what keeps the
/// list from reshuffling under the reader on every refresh that ties.
func memorySourceRows(overview: [SourceOverview],
                      today: Date,
                      limit: Int = MemorySourceRow.limit,
                      sparkDays: Int = MemorySourceRow.sparkDays) -> [MemorySourceRow] {
    overview
        .filter { $0.episodes > 0 }
        .map { source in
            MemorySourceRow(
                id: source.id,
                label: source.label,
                mark: source.mark,
                captured: source.episodes,
                recentCaptures: sparklinePoints(activity: source.activity,
                                                days: MemorySourceRow.recentWindowDays,
                                                today: today).reduce(0, +),
                points: sparklinePoints(activity: source.activity, days: sparkDays, today: today),
                dots: weekDots(activity: source.activity, weeks: MemorySourceRow.weeks, today: today)
            )
        }
        .sorted { a, b in
            if a.recentCaptures != b.recentCaptures { return a.recentCaptures > b.recentCaptures }
            if a.captured != b.captured { return a.captured > b.captured }
            return a.id < b.id
        }
        .prefix(limit)
        .map { $0 }
}

// MARK: - The mark itself

/// The series as a line, normalised to its own maximum inside `size`.
///
/// Per-row normalisation is deliberate: the panel compares a source against its
/// OWN month, not against a busier neighbour — a shared scale would flatten
/// every small source into the baseline and say nothing. The count beside it is
/// what carries absolute volume (budget rows #13/#14: one number, one mark,
/// neither drawn twice).
///
/// Fewer than two points draws nothing — a single dot would read as a datum.
/// An all-zero series still draws its flat baseline: "nothing captured this
/// month" is a fact worth seeing, and a blank cell reads as a broken view.
func sparklinePath(_ points: [Int], in size: CGSize) -> Path {
    var path = Path()
    guard points.count > 1, size.width > 0, size.height > 0 else { return path }
    let peak = max(points.max() ?? 0, 1)
    let step = size.width / CGFloat(points.count - 1)
    for (index, value) in points.enumerated() {
        let x = CGFloat(index) * step
        let y = size.height - (CGFloat(value) / CGFloat(peak)) * size.height
        if index == 0 { path.move(to: CGPoint(x: x, y: y)) } else { path.addLine(to: CGPoint(x: x, y: y)) }
    }
    return path
}

/// The sparkline, drawn from `sparklinePath`. Decorative in the accessibility
/// sense: the row's `countLine` carries the number, and R-A13's motion budget
/// means it never animates — a static line, no axes, no labels, no tooltip
/// pretending to be a chart.
private struct SparklineView: View {
    let points: [Int]

    var body: some View {
        GeometryReader { geo in
            sparklinePath(points, in: geo.size)
                .stroke(CicadaTheme.accent.opacity(0.75),
                        style: StrokeStyle(lineWidth: 1, lineCap: .round, lineJoin: .round))
        }
        .frame(width: 56, height: 14)
        .accessibilityHidden(true)
    }
}

/// Four dots, one per week, filled when that week had any captures at all.
///
/// **State, not quantity** — R1's "one volume encoding per surface", amended by
/// this plan to "one per mark": the sparkline already encodes how much, so a
/// second graded mark eighteen points away would ask the reader to tell two
/// charts apart by weight. These say only *which of the last four weeks this
/// source was alive*, which the line's own noise does not make obvious.
private struct WeekDotsView: View {
    let dots: [Int]

    var body: some View {
        HStack(spacing: 3) {
            ForEach(Array(dots.enumerated()), id: \.offset) { _, count in
                Circle()
                    .fill(count > 0 ? CicadaTheme.accent.opacity(0.65) : CicadaTheme.border)
                    .frame(width: 4, height: 4)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(dots.filter { $0 > 0 }.count) of the last \(dots.count) weeks had captures")
    }
}

// MARK: - The panel

/// "MEMORY SOURCES" (G125 v3 Task 7, R-A10) — the right column's top card:
/// what has been feeding this bank, biggest recent contributor first, with the
/// month's shape beside each row.
///
/// A pure renderer of rows the caller already projected (the same posture
/// `StudyListCard` and `ConsolidationHistoryCard` hold): it starts no fetches
/// and reads no clock, so what it draws is exactly what the page resolved once
/// per body evaluation.
struct MemorySourcesCard: View {
    let rows: [MemorySourceRow]
    /// Opens the Sources page. A closure rather than a `Binding<AppTab>` so the
    /// card stays a renderer with one outbound action.
    var onShowAllSources: (() -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text("MEMORY SOURCES")
                .font(CicadaTheme.font(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            if rows.isEmpty {
                // Not "0 sources": nothing has been captured into this bank
                // yet, which is a state, not a measurement (P18).
                Text("Nothing captured yet.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.vertical, CicadaTheme.spacingSM)
            } else {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    ForEach(rows) { row in
                        rowView(row)
                    }
                }
            }

            allSourcesRow
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private func rowView(_ row: MemorySourceRow) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            OriginMark(origin: row.mark, size: 16)

            VStack(alignment: .leading, spacing: 1) {
                Text(row.label)
                    .font(CicadaTheme.font(size: 12, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                Text(row.countLine)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }

            Spacer(minLength: CicadaTheme.spacingSM)

            VStack(alignment: .trailing, spacing: 3) {
                SparklineView(points: row.points)
                WeekDotsView(dots: row.dots)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(row.label), \(row.countLine)")
    }

    /// The way out of a capped list. `Copy.sources` rather than a retyped
    /// literal, so this pointer names its destination exactly as the sidebar
    /// spells it (the G68 §2.8 house rule).
    @ViewBuilder
    private var allSourcesRow: some View {
        if let onShowAllSources {
            Button(action: onShowAllSources) {
                HStack(spacing: 4) {
                    Text("All \(Copy.sources.lowercased())")
                        .font(CicadaTheme.captionFont)
                    Image(systemName: "arrow.right")
                        .font(CicadaTheme.font(size: 9, weight: .semibold))
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .foregroundStyle(CicadaTheme.accent)
        }
    }
}
