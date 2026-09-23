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

    /// G136 S5 — `FeedSearch`'s one field list (title, site, channel, origin,
    /// tags, description, url, about — and a paper's authors, arXiv id and DOI,
    /// G133), filtered in the Feed's own order (R-SU20). The fields are folded
    /// once per snapshot (`foldedFields`), never per keystroke: a render reads
    /// this two or three times, and re-folding every description and URL of
    /// ~1,500 saved items on each read measured ~100 ms a pass in a debug
    /// build while planning (QuickMatch's own rule, R-SU21).
    var filteredItems: [MediaFeedItem] {
        let tokens = QuickMatch.tokens(searchText)
        guard !tokens.isEmpty else { return items }
        let folded = foldedFields()
        return items.filter { QuickMatch.match(tokens, fields: folded[$0.id] ?? FeedSearch.fields($0)) != nil }
    }

    /// Keyed on the snapshot's change token and size — the pair
    /// `GraphViewModel.clusterSearchIndex()` uses for the same job.
    @ObservationIgnored private var searchCache: (stamp: Date?, count: Int, fields: [String: [QuickMatch.Field]])?

    private func foldedFields() -> [String: [QuickMatch.Field]] {
        let all = store.sources.value ?? []
        if let cache = searchCache, cache.stamp == store.sources.loadedAt, cache.count == all.count {
            return cache.fields
        }
        let fields = Dictionary(all.map { ($0.id, FeedSearch.fields($0)) }, uniquingKeysWith: { first, _ in first })
        searchCache = (store.sources.loadedAt, all.count, fields)
        return fields
    }

    /// One saved item against the words, through `FeedSearch`'s one field
    /// list (R-SU21) — kept as Track F's entry point, which `PaperCardTests`
    /// pins.
    nonisolated static func matches(_ item: MediaFeedItem, query: String) -> Bool {
        FeedSearch.matches(item, query: query)
    }

    func load() async {
        errorMessage = nil
        await store.refresh([.sources])
        if store.sources.value == nil {
            errorMessage = store.toast
        }
    }
}
