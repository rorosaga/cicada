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
        var flat: [CalendarCell?] = Array(repeating: nil, count: weekdayIndex(first.date))
        flat.append(contentsOf: days.map { Optional($0) })
        while flat.count % 7 != 0 { flat.append(nil) }
        return stride(from: 0, to: flat.count, by: 7).map { Array(flat[$0..<$0 + 7]) }
    }

    static func monthLabels(_ columns: [[CalendarCell?]]) -> [(column: Int, label: String)] {
        var out: [(Int, String)] = []
        var seen = ""
        for (i, col) in columns.enumerated() {
            guard let firstDay = col.compactMap({ $0 }).first else { continue }
            let month = String(firstDay.date.prefix(7))
            if month != seen {
                seen = month
                let idx = Int(firstDay.date.dropFirst(5).prefix(2)) ?? 1
                out.append((i, formatter.shortMonthSymbols[idx - 1]))
            }
        }
        return out.map { (column: $0.0, label: $0.1) }
    }
}
