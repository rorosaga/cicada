import Foundation

/// F1 R-FX11 — the entity card's beliefs list, in its own file so this track
/// and the sibling tracks appending to `Copy.swift` never edit the same lines
/// (the `Copy+Intake.swift` precedent, R-IA19). Plain words for a person who
/// has never heard "claim".
extension Copy {
    enum Beliefs {
        static let title = "What Cicada knows"
        static let caption = "Nothing's written up about this yet, so here's what Cicada has noted."
        /// DR-45 — the section label carries its count, grouped in the reader's locale (R-S18).
        static func heading(_ n: Int) -> String { "\(title) · \(UsageFormat.count(n))" }
    }
}
