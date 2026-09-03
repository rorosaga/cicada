import Foundation

/// The pure half of the G115 card, kept out of the views so it is testable:
/// the cause line, the age phrase (same wording as the server's
/// `inbox_questions.humanize_age`), the bolded excerpt, and the collapse rule.
enum InboxAge {
    /// Whole days between an ISO date/timestamp and `now`; `nil` if unparseable.
    static func days(since iso: String?, now: Date) -> Int? {
        guard let iso, !iso.isEmpty else { return nil }
        let full = ISO8601DateFormatter()
        full.formatOptions = [.withInternetDateTime]
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let dayOnly = DateFormatter()
        dayOnly.dateFormat = "yyyy-MM-dd"
        dayOnly.timeZone = TimeZone(identifier: "UTC")
        let then = full.date(from: iso) ?? fractional.date(from: iso) ?? dayOnly.date(from: String(iso.prefix(10)))
        guard let then else { return nil }
        return max(0, Int(now.timeIntervalSince(then) / 86_400))
    }

    /// Word-for-word `inbox_questions.humanize_age` — including the branch
    /// boundaries (the week branch starts at 14 days, the month branch at 60),
    /// so a card and an MCP blurb never disagree about the same item's age.
    /// The rounding rule is part of that parity: Python's `round()` is
    /// round-half-to-EVEN, so 75 days is "2 months ago" there and would be
    /// "3 months ago" under Swift's default `.rounded()` (half away from zero).
    /// `.toNearestOrEven` keeps the two surfaces in step.
    static func phrase(days: Int?) -> String {
        guard let days else { return "unknown" }
        if days == 0 { return "today" }
        if days == 1 { return "yesterday" }
        if days < 14 { return "\(days) days ago" }
        if days < 60 {
            let weeks = Int((Double(days) / 7).rounded(.toNearestOrEven))
            return weeks == 1 ? "a week ago" : "\(weeks) weeks ago"
        }
        if days < 365 {
            let months = Int((Double(days) / 30).rounded(.toNearestOrEven))
            return months == 1 ? "a month ago" : "\(months) months ago"
        }
        let years = Int((Double(days) / 365).rounded(.toNearestOrEven))
        return years == 1 ? "a year ago" : "\(years) years ago"
    }
}

enum ExcerptText {
    /// The excerpt with each `[start, end)` scalar range bolded. Ranges that
    /// fall outside the text are ignored — a stale offset must never crash
    /// the card (the server recomputes offsets on every read; the cache may
    /// hold an older excerpt for a moment).
    static func attributed(_ excerpt: String, bold offsets: [[Int]]) -> AttributedString {
        var out = AttributedString(excerpt)
        let scalars = excerpt.unicodeScalars
        let count = scalars.count
        for pair in offsets where pair.count == 2 {
            let (s, e) = (pair[0], pair[1])
            guard s >= 0, e > s, e <= count else { continue }
            let lower = scalars.index(scalars.startIndex, offsetBy: s)
            let upper = scalars.index(scalars.startIndex, offsetBy: e)
            guard let aLower = AttributedString.Index(lower, within: out),
                  let aUpper = AttributedString.Index(upper, within: out) else { continue }
            out[aLower..<aUpper].inlinePresentationIntent = .stronglyEmphasized
        }
        return out
    }
}

/// The owner's second defect (2026-09-03): merge/clarification items over media
/// rendered every URL inline. More than `threshold` non-blank lines collapse to
/// the first `visible` plus a "Show all N" toggle — four lines are not worth
/// the toggle, five are.
struct CollapsedLines {
    static let visible = 3
    static let threshold = 4

    let lines: [String]

    init(_ text: String) {
        lines = text.split(whereSeparator: \.isNewline)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
    }

    var needsCollapse: Bool { lines.count > Self.threshold }
    var head: [String] { needsCollapse ? Array(lines.prefix(Self.visible)) : lines }
    var hidden: Int { needsCollapse ? lines.count - Self.visible : 0 }
}

extension InboxItem {
    /// A cause that actually resolved to an episode.
    var hasCause: Bool { (cause?.tier ?? "none") != "none" }

    /// Line 2 of the card: `From “Title” · harness · age`, or the literal
    /// `[ no source recorded ]` — provenance is stated, never blank (G97).
    func causeLine(now: Date = .now) -> String {
        guard let cause, hasCause else { return "[ no source recorded ]" }
        var parts: [String] = []
        if let title = cause.conversationTitle, !title.isEmpty {
            parts.append("From “\(title)”")
        } else if let ep = cause.episodeId {
            parts.append("From \(ep)")
        }
        if let h = cause.harness ?? cause.origin, !h.isEmpty { parts.append(h) }
        let age = InboxAge.phrase(days: InboxAge.days(since: cause.timestamp, now: now))
        if age != "unknown" { parts.append(age) }
        return parts.joined(separator: " · ")
    }

    /// Index of the `(Recommended)` option in `options`, if any.
    var recommendedIndex: Int? {
        options.firstIndex(where: \.recommended)
    }
}
