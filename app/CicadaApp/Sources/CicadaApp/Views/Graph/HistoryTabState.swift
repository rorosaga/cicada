import Foundation

/// Which of the three History-tab branches to render.
///
/// Split out of `EntityDetailCard` so the "is it still loading, or is it
/// genuinely empty?" decision is testable without a view. The graph hands the
/// card a light node entity first (`history == []`) and swaps in the full body
/// a round-trip later, so an unconditional list renders a silent, permanent
/// blank for any page whose history hasn't arrived — indistinguishable from a
/// page with no commits.
enum HistoryTabState {
    case loading
    case empty
    case entries([EntityHistoryEntry])
    /// The fetch threw. Distinct from `.empty` so a dead backend doesn't read
    /// as "no commits touch this page" — and distinct from `.loading` so the
    /// tab offers a retry instead of spinning forever. `fetched` must stay
    /// `nil` on a failed attempt (never coerced to `[]`) or this state is
    /// unreachable and a future retry is blocked by the "already fetched"
    /// guard in `loadHistoryIfNeeded`.
    case error

    /// - Parameters:
    ///   - embedded: whatever `GET /entities/{id}` already carried.
    ///   - fetched: `nil` until `GET /entities/{id}/history` has come back
    ///     successfully; `[]` once it has and there was nothing.
    ///   - failed: whether the most recent fetch attempt threw. Checked
    ///     before `fetched == nil` so a failure doesn't fall through to
    ///     `.loading`.
    static func resolve(embedded: [EntityHistoryEntry], fetched: [EntityHistoryEntry]?,
                        failed: Bool = false) -> HistoryTabState {
        if !embedded.isEmpty { return .entries(embedded) }
        if failed { return .error }
        guard let fetched else { return .loading }
        return fetched.isEmpty ? .empty : .entries(fetched)
    }
}
