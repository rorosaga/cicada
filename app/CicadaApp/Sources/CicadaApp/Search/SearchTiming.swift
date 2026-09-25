import Foundation

/// The palette's clock and sizes (round-3 design §1.1). Not motion, so they
/// live here rather than in `CicadaMotion`.
enum SearchTiming {
    /// The owner's brief (2026-09-23) set 150–200 ms, over the design's 120 ms
    /// (R-SU14): a fast typist never sends a mid-word request, and the server
    /// answers a prefix in ~5 ms warm, so the pause is the latency.
    static let serverDebounce: Duration = .milliseconds(150)
    /// Idle before the hybrid (vector) pass — once the typing has settled.
    static let semanticIdle: Duration = .milliseconds(450)
    static let perKind = 5
    /// "Show all" on a server-fed group re-asks that kind at the server's cap (`MAX_PER_KIND`).
    static let expandedPerKind = 20
    /// Design §3.10: p95 per keystroke in a release build (R-SU24).
    static let localBudgetMs = 8.0

    /// `text_fold.MIN_TOKEN_CHARS`: the server searches nothing shorter than two characters.
    static func wantsServer(_ query: String) -> Bool {
        QuickMatch.tokens(query).contains { $0.scalars.count >= 2 }
    }
}
