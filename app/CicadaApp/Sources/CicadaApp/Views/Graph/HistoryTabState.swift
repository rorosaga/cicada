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

    /// - Parameters:
    ///   - embedded: whatever `GET /entities/{id}` already carried.
    ///   - fetched: `nil` until `GET /entities/{id}/history` has come back;
    ///     `[]` once it has and there was nothing.
    static func resolve(embedded: [EntityHistoryEntry], fetched: [EntityHistoryEntry]?) -> HistoryTabState {
        if !embedded.isEmpty { return .entries(embedded) }
        guard let fetched else { return .loading }
        return fetched.isEmpty ? .empty : .entries(fetched)
    }
}
