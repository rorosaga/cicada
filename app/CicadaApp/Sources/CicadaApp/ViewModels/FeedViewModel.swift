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
        case .recent: return base.sorted { $0.savedAt > $1.savedAt }
        }
    }

    var isLoading: Bool { store.sources.isEmpty && store.sources.isRefreshing }

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
