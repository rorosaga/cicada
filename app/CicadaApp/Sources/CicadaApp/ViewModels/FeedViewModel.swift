import Foundation
import Observation

/// Backs the media Feed screen. Loads saved media from `GET /sources`, sorted by
/// the §3.4 relevance metric (or recency), and exposes a lightweight text filter.
@Observable
final class FeedViewModel {
    enum SortMode: String, CaseIterable, Identifiable {
        case relevance, recent
        var id: String { rawValue }
        var label: String { self == .relevance ? "Relevance" : "Recent" }
    }

    var items: [MediaFeedItem] = []
    var isLoading = false
    var errorMessage: String?
    var sort: SortMode = .relevance {
        didSet { Task { await load() } }
    }
    var searchText = ""

    var filteredItems: [MediaFeedItem] {
        guard !searchText.isEmpty else { return items }
        let q = searchText.lowercased()
        return items.filter {
            $0.title.lowercased().contains(q)
                || ($0.site?.lowercased().contains(q) ?? false)
                || $0.tags.contains(where: { $0.lowercased().contains(q) })
        }
    }

    @MainActor
    func load() async {
        isLoading = true
        errorMessage = nil
        do {
            items = try await APIClient.shared.fetchSources(sort: sort.rawValue)
        } catch {
            errorMessage = error.localizedDescription
            items = []
        }
        isLoading = false
    }
}
