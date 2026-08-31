import Foundation

struct CalendarCell: Hashable {
    let date: String   // yyyy-MM-dd
    let level: Int     // 0…4
    let memoryWrites: Int
    let events: Int
    let tokens: Int
}

/// GitHub-style layout: one column per ISO week, 7 rows Monday→Sunday.
enum CalendarLayout {
    private static let formatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.timeZone = TimeZone(identifier: "UTC")
        f.locale = Locale(identifier: "en_US_POSIX")
        return f
    }()

    /// 0 = Monday … 6 = Sunday.
    static func weekdayIndex(_ iso: String) -> Int {
        guard let d = formatter.date(from: iso) else { return 0 }
        var cal = Calendar(identifier: .iso8601)
        cal.timeZone = TimeZone(identifier: "UTC")!
        return (cal.component(.weekday, from: d) + 5) % 7
    }

    /// Pads the *first* column with leading empty cells so every column
    /// keeps a consistent Monday…Sunday row alignment and every real day is
    /// rendered — GitHub's own contribution graph does the same. This is a
    /// deliberate no-data-loss choice over forcing a fixed column count: for
    /// the default 53-week (371-day) dashboard range, that gives exactly 53
    /// columns when the range happens to start on a Monday (1 day out of 7)
    /// and — honestly — 54 for the other 6, because a 371-day range starting
    /// mid-week genuinely spans 54 distinct Monday-Sunday weeks. Column count
    /// is a display detail; every day the backend sent is a click target and
    /// a data point, and neither gets sacrificed to hit "53" on the nose.
    static func columns(_ days: [CalendarCell]) -> [[CalendarCell?]] {
        guard let first = days.first else { return [] }
        var flat: [CalendarCell?] = Array(repeating: nil, count: weekdayIndex(first.date))
        flat.append(contentsOf: days.map { Optional($0) })
        while flat.count % 7 != 0 { flat.append(nil) }
        return stride(from: 0, to: flat.count, by: 7).map { Array(flat[$0..<$0 + 7]) }
    }

    /// Minimum column gap between two month labels. At an 11 pt cell + 3 pt
    /// gap a three-letter label spans roughly three columns; anything closer
    /// overprints its neighbour ("AugSep").
    static let minLabelSpacing = 3

    static func monthLabels(_ columns: [[CalendarCell?]]) -> [(column: Int, label: String)] {
        var out: [(Int, String)] = []
        var seen = ""
        for (i, col) in columns.enumerated() {
            guard let firstDay = col.compactMap({ $0 }).first else { continue }
            let month = String(firstDay.date.prefix(7))
            guard month != seen else { continue }
            // Advance `seen` even when the label is dropped, so the NEXT month
            // is still considered rather than being swallowed by this one.
            seen = month
            if let last = out.last, i - last.0 < minLabelSpacing { continue }
            let idx = Int(firstDay.date.dropFirst(5).prefix(2)) ?? 1
            out.append((i, formatter.shortMonthSymbols[idx - 1]))
        }
        return out.map { (column: $0.0, label: $0.1) }
    }
}
