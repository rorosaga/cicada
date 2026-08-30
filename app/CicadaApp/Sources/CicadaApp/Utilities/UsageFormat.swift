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

    private static func trim(_ v: Double, digits: Int) -> String {
        var s = String(format: "%.\(digits)f", v)
        while s.contains(".") && (s.hasSuffix("0") || s.hasSuffix(".")) { s.removeLast() }
        return s
    }
}
