import Foundation

/// The date formatters `ReaderTime` and `InboxAge` parse stamps with, built once (inbox lag, 2026-10-17).
///
/// Building an `ISO8601DateFormatter` or a `DateFormatter` costs far more than using one, and both helpers built two
/// to five of them on every call. Every Inbox row calls them three times when it draws (its age, its source line's
/// day, the day in its help), and the question list is a plain `VStack`, so each render of the page drew every row:
/// 171 ms per pass over 239 rows, on the main thread, several passes as the page opened. Parsing with a kept
/// formatter gives the same `Date` for the same input. A formatter is a mutable reference type, so each use holds
/// one lock: parsing a stamp takes microseconds, and callers on other threads stay safe.
enum ISOStamp {
    private static let lock = NSLock()
    nonisolated(unsafe) private static let internet: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
    nonisolated(unsafe) private static let fractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    /// `"<posix>|<zone>|<format>"` -> formatter. A handful of entries: three formats, one or two zones.
    nonisolated(unsafe) private static var fixed: [String: DateFormatter] = [:]

    /// `"<zone>\u{1}<raw>"` -> what `remembered` computed for it, `nil` included. A bank holds a few thousand
    /// distinct stamps; past `memoLimit` the memo starts over rather than grow.
    nonisolated(unsafe) private static var memo: [String: Date?] = [:]
    static let memoLimit = 4096

    /// `compute()` for this stamp in this zone, once: the list draws the same rows on every render, and a stamp
    /// that is not RFC 3339 walks several formatters before it parses (or does not). `compute` runs outside the
    /// lock, so it may call the parsers below.
    static func remembered(_ raw: String, timeZone: TimeZone, _ compute: () -> Date?) -> Date? {
        let key = "\(timeZone.identifier)\u{1}\(raw)"
        lock.lock()
        let kept = memo[key]
        lock.unlock()
        if let kept { return kept }
        let value = compute()
        lock.lock()
        if memo.count >= memoLimit { memo.removeAll(keepingCapacity: true) }
        memo[key] = .some(value)
        lock.unlock()
        return value
    }

    /// An aware RFC 3339 stamp, without then with fractional seconds; `nil` for any other shape.
    static func internetDate(_ raw: String) -> Date? {
        lock.lock()
        defer { lock.unlock() }
        return internet.date(from: raw) ?? fractional.date(from: raw)
    }

    /// `raw` read with a fixed `format` in `timeZone`. `posix` pins the `en_US_POSIX` locale (what a machine stamp
    /// needs); `false` keeps the formatter's default locale, for the one caller that always had it.
    static func date(_ raw: String, format: String, timeZone: TimeZone, posix: Bool = true) -> Date? {
        lock.lock()
        defer { lock.unlock() }
        let key = "\(posix ? "posix" : "default")|\(timeZone.identifier)|\(format)"
        let formatter: DateFormatter
        if let kept = fixed[key] {
            formatter = kept
        } else {
            formatter = DateFormatter()
            if posix { formatter.locale = Locale(identifier: "en_US_POSIX") }
            formatter.timeZone = timeZone
            formatter.dateFormat = format
            fixed[key] = formatter
        }
        return formatter.date(from: raw)
    }
}
