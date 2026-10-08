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

/// #244 — the History tab past the served window. `GET /entities/{id}` carries an entity's newest `window` changes
/// (plus older commits that still own lines) and `historyTruncated` when there are more; `GET
/// /entities/{id}/history?skip=N` reads the changes older than the newest N. "Older changes" asks for the next page.
struct HistoryPaging: Equatable {
    /// `git_service.MAX_PROVENANCE_COMMITS`, pinned by `api/tests/test_history_window_pin.py`.
    static let window = 500

    private(set) var hasMore: Bool
    private(set) var nextSkip: Int

    init(truncated: Bool) {
        hasMore = truncated
        nextSkip = Self.window
    }

    /// One page came back: it moves the cursor by what it held; a short page is the last.
    mutating func received(_ page: [EntityHistoryEntry]) {
        nextSkip += page.count
        hasMore = page.count >= Self.window
    }

    /// The rows shown newest first, then the older ones, each commit once (the served page may already carry an
    /// older commit that still owns lines).
    static func merge(_ shown: [EntityHistoryEntry], older: [EntityHistoryEntry]) -> [EntityHistoryEntry] {
        var seen = Set(shown.map(\.commitHash).filter { !$0.isEmpty })
        return shown + older.filter { $0.commitHash.isEmpty || seen.insert($0.commitHash).inserted }
    }
}
