import Foundation

/// Number formatting for the Sources page's counts. No currency and no token
/// formatter live here any more — the 2026-09-03 G124 ruling took prices and
/// token usage out of the app.
enum UsageFormat {
    /// Plain grouped integer for counters ("1,284 sessions"). Never
    /// abbreviated — a count of "1.3k" reads as an estimate when it is exact.
    static func count(_ n: Int) -> String {
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.locale = Locale(identifier: "en_US_POSIX")
        // `en_US_POSIX` — otherwise locale-stable for a fixed "," + "." — does
        // NOT group by default the way a real `en_US` locale does; without
        // this, "1,284" silently comes back as "1284".
        f.usesGroupingSeparator = true
        return f.string(from: NSNumber(value: n)) ?? "\(n)"
    }

    /// Percent for the Codex rate-limit windows.
    static func percent(_ value: Double?) -> String {
        guard let value else { return "—" }
        return "\(Int(value.rounded()))%"
    }

    /// Wall-clock duration from milliseconds — the longest-sleep-run tile.
    static func duration(ms: Double?) -> String {
        guard let ms else { return "—" }
        let minutes = Int((ms / 60_000).rounded())
        if minutes < 1 { return "<1m" }
        if minutes < 60 { return "\(minutes)m" }
        return "\(minutes / 60)h \(minutes % 60)m"
    }

    /// One loose value out of a harness dict: an integer groups, a fraction
    /// trims, a string passes through, nothing renders as an em dash. The
    /// panel used to interpolate `LooseValue.text` and `Int(_)` directly, so
    /// the same figure formatted differently in two tiles.
    static func harnessValue(_ value: LooseValue?) -> String {
        guard let value else { return "—" }
        if let n = value.number {
            return n == n.rounded() ? count(Int(n)) : trim(n, digits: 2)
        }
        return value.text
    }

    private static func trim(_ v: Double, digits: Int) -> String {
        var s = String(format: "%.\(digits)f", v)
        while s.contains(".") && (s.hasSuffix("0") || s.hasSuffix(".")) { s.removeLast() }
        return s
    }
}
