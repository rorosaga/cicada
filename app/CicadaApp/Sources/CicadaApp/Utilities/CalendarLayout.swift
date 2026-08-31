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

    static func columns(_ days: [CalendarCell]) -> [[CalendarCell?]] {
        guard let first = days.first else { return [] }
        var offset = weekdayIndex(first.date)
        var effectiveDays = days
        // When the input is already an exact multiple of 7 (the default
        // 53-week / 371-day dashboard calendar), a leading partial week
        // borrows `offset` empty cells from what would otherwise be an exact
        // N/7 grid — and since there's no slack left to absorb them, that
        // borrow always spills into a whole extra column: 54 instead of 53,
        // on every day of the year except the one where "371 days ago"
        // happens to land on a Monday. Drop the handful of oldest days
        // before the next Monday instead, so an exact-weeks range only ever
        // needs exactly that many columns; the range still ends on the same
        // last (most recent) day either way. A non-exact input (most fixture
        // and test data) already has slack to absorb the leading partial
        // week without growing past `ceil(N/7)`, so it's left untouched.
        if offset > 0 && days.count % 7 == 0 {
            let drop = (7 - offset) % 7
            effectiveDays = Array(days.dropFirst(drop))
            offset = 0
        }
        var flat: [CalendarCell?] = Array(repeating: nil, count: offset)
        flat.append(contentsOf: effectiveDays.map { Optional($0) })
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
