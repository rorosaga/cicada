import SwiftUI

// MARK: - The activity window (moved from Views/Sleep/MemorySourcesCard.swift, Track Z Z3)
//
// Track A wrote these for the Sleep page's Memory sources card; Sources v2
// (R-S8) has called them from the grid, the header card and the detail page
// ever since. The card has left the Sleep page (design §4.2 — Sources v2 draws
// the same projection), so the series live beside their only callers now.
// The functions and their tests moved verbatim; nothing about the window
// (UTC days, dense, oldest first) changed.

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
