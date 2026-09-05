import Foundation

/// Number formatting for the Sources page's counts. No currency and no token
/// formatter live here any more — the 2026-09-03 G124 ruling took prices and
/// token usage out of the app.
enum UsageFormat {
    /// Plain grouped integer for counters ("1,284 sessions"). Never
    /// abbreviated — a count of "1.3k" reads as an estimate when it is exact.
    ///
    /// R-S17 — the locale is a parameter defaulting to
    /// `.autoupdatingCurrent`, not a pin to `en_US_POSIX`. The pin was the
    /// senior half of critique B1: it printed "1,035" to a reader whose whole
    /// system says "1.035", eight inches above a `Text("\(count) entities")`
    /// that — being a `LocalizedStringKey` — grouped in the reader's OWN
    /// locale. Three conventions in one window. An explicit parameter is also
    /// what lets a test assert both `es_ES` and `en_US` on any host.
    static func count(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.locale = locale
        // Kept from the `en_US_POSIX` era: that locale does NOT group by
        // default the way a real `en_US` one does, so without this "1,284"
        // silently came back as "1284". Harmless (and explicit) for a real
        // locale, which is why it stays rather than being dropped with the pin.
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
    ///
    /// R-S17 — the `locale:` is taken and FORWARDED rather than left to
    /// `count`'s default. The default would give the same answer today, but a
    /// caller that has already resolved a locale (a test asserting `es_ES` on a
    /// US host, a view formatting a whole panel) must be able to reach every
    /// number through one door. A formatter that swallows the parameter its
    /// callee accepts is exactly the second door B1 was.
    static func harnessValue(_ value: LooseValue?, locale: Locale = .autoupdatingCurrent) -> String {
        guard let value else { return "—" }
        if let n = value.number {
            return n == n.rounded() ? count(Int(n), locale: locale) : trim(n, digits: 2)
        }
        return value.text
    }

    private static func trim(_ v: Double, digits: Int) -> String {
        var s = String(format: "%.\(digits)f", v)
        while s.contains(".") && (s.hasSuffix("0") || s.hasSuffix(".")) { s.removeLast() }
        return s
    }
}
