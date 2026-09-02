import Foundation

/// Number/cost formatting for the Usage page. Honesty rule (spec §6.6):
/// subscription work is never shown as "spent" — only as an API-equivalent estimate.
enum UsageFormat {
    static func tokens(_ n: Int) -> String {
        switch n {
        case ..<1_000: return "\(n)"
        case ..<1_000_000: return trim(Double(n) / 1_000, digits: 1) + "k"
        default: return trim(Double(n) / 1_000_000, digits: 2) + "M"
        }
    }

    static func usd(_ x: Double?) -> String {
        guard let x else { return "n/a" }
        if x == 0 { return "$0.00" }
        if x < 0.01 { return "$" + String(format: "%.4f", x) }
        return "$" + String(format: "%.2f", x)
    }

    static func costLine(costUsd: Double, equivUsd: Double, subscriptionUsd: Double?) -> String {
        let planEquiv = max(0, equivUsd - costUsd)
        if costUsd == 0 && subscriptionUsd != nil {
            return "Included in plan · ≈ \(usd(planEquiv)) at API list price"
        }
        if subscriptionUsd == nil || planEquiv < 0.005 {
            return "\(usd(costUsd)) spent"
        }
        return "\(usd(costUsd)) spent · plan work ≈ \(usd(planEquiv)) at API list price"
    }

    /// Plain grouped integer for harness counters ("1,284 sessions"). Distinct
    /// from `tokens`, which abbreviates — a session count of "1.3k" reads as
    /// an estimate when it is exact.
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
