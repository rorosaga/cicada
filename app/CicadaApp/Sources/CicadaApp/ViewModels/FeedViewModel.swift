import Foundation
import Observation

/// Backs the media Feed screen. Thin projection over `Store.sources` (§5.5):
/// `items` reads straight from the snapshot, sorted server-side by the §3.4
/// relevance metric (or recency) the last time `sort` changed. Never wipes
/// `items` on a failed refresh — since it's a computed read over the Store's
/// snapshot (which itself never blanks on error), that safety property falls
/// out for free.
@Observable
@MainActor
final class FeedViewModel {
    enum SortMode: String, CaseIterable, Identifiable {
        case relevance, recent
        var id: String { rawValue }
        var label: String { self == .relevance ? "Relevance" : "Recent" }
    }

    private let store: Store

    var errorMessage: String?
    /// `GET /sources` is always fetched relevance-sorted server-side (the
    /// Store's `SyncAPI.fetchSources` hardcodes `sort=relevance`, since the
    /// snapshot is shared and can't carry two orderings at once); `.recent`
    /// just re-sorts the same snapshot client-side, so flipping the segmented
    /// control is instant and never re-fetches or blanks the list.
    var sort: SortMode = .relevance
    var searchText = ""

    init(store: Store) {
        self.store = store
    }

    /// Sorted per `sort`; unfiltered.
    var items: [MediaFeedItem] {
        let base = store.sources.value ?? []
        switch sort {
        case .relevance: return base
        // G99d: prefer the recovered true save date over the ingest
        // timestamp, falling back to it only when no source date parsed.
        // Compared as real Dates (review finding), not raw strings — see
        // MediaFeedItem.recencyDate's doc for the same-day tie-break rule.
        case .recent: return base.sorted { $0.recencyDate > $1.recencyDate }
        }
    }

    var isLoading: Bool { store.sources.isEmpty && store.sources.isRefreshing }

    /// The §3.4 score is decayed confidence, not query relevance — after a
    /// bulk bookmark sync every item carries identical defaults and every
    /// badge renders the same percentage. Only show the badge (and treat the
    /// Relevance sort as meaningful) when the RENDERED percentages actually
    /// differ; raw-Double comparison is wrong here (0.5664 vs 0.5689 are
    /// distinct Doubles but both render "57%").
    var scoresAreInformative: Bool {
        let rendered = Set((store.sources.value ?? []).map { Int(($0.relevance * 100).rounded()) })
        return rendered.count > 1
    }

    var filteredItems: [MediaFeedItem] {
        guard !searchText.isEmpty else { return items }
        let q = searchText.lowercased()
        return items.filter {
            $0.title.lowercased().contains(q)
                || ($0.site?.lowercased().contains(q) ?? false)
                || $0.tags.contains(where: { $0.lowercased().contains(q) })
        }
    }

    func load() async {
        errorMessage = nil
        await store.refresh([.sources])
        if store.sources.value == nil {
            errorMessage = store.toast
        }
    }
}
