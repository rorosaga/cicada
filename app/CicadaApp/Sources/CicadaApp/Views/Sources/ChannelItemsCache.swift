import Foundation
import Observation

/// G161 — what each source brought in, by name, kept in memory: one for the app, owned by `CicadaApp` beside
/// `ProvenanceCache`, and emptied on a bank switch (episode and page ids repeat across banks). **Never a Store
/// domain**: nothing on disk, no `VersionVector` mapping — a list revalidates with the server's ETag when it opens and
/// whenever the channels move, and a failed or 304 answer keeps the last value (never blank, DR-43). An answer in
/// flight across a bank switch is dropped by its epoch (the `BacklogCache` rule).
@Observable
@MainActor
final class ChannelItemsCache {
    enum Phase: Equatable { case idle, loading, loaded, gone, failed(String) }

    private(set) var lists: [String: ChannelItemsList] = [:]
    private(set) var phases: [String: Phase] = [:]
    /// Channels whose next page is being read ("Show more" waits on it).
    private(set) var loadingMore: Set<String> = []

    private struct Tag { let limit: Int; let etag: String }

    @ObservationIgnored private let api: any ChannelItemsAPI
    /// The ETag of the first-page read that covers every row shown — tied to its `limit`, since another limit is
    /// another body (and another tag) on the server.
    @ObservationIgnored private var tags: [String: Tag] = [:]
    @ObservationIgnored private var epoch = 0

    init(api: any ChannelItemsAPI = APIClient.shared) { self.api = api }

    func list(_ channel: String) -> ChannelItemsList? { lists[channel] }
    func phase(_ channel: String) -> Phase { phases[channel] ?? .idle }
    func isLoadingMore(_ channel: String) -> Bool { loadingMore.contains(channel) }

    /// Forget everything — a bank switch (`ContentView`, R-PU26's reason).
    func reset() {
        epoch &+= 1
        lists = [:]
        phases = [:]
        loadingMore = []
        tags = [:]
    }

    /// Re-read the rows already shown (at least the first page), sending the tag only when it covers the same rows —
    /// a 304 then keeps the list exactly as it is.
    func refresh(_ channel: String) async {
        let started = epoch
        let cached = lists[channel]
        let limit = CapturedItems.refreshLimit(shown: cached?.items.count ?? 0)
        if cached == nil { phases[channel] = .loading }
        let etag = cached == nil ? nil : tags[channel].flatMap { $0.limit == limit ? $0.etag : nil }
        do {
            let answer = try await api.fetchChannelItems(channel: channel, offset: 0, limit: limit, etag: etag)
            guard started == epoch else { return }
            if let page = answer.value {
                lists[channel] = ChannelItemsList(items: page.items, total: page.total)
                tags[channel] = answer.etag.map { Tag(limit: limit, etag: $0) }
            }
            phases[channel] = .loaded
        } catch APIError.httpError(404, _) {
            guard started == epoch else { return }
            lists[channel] = nil
            tags[channel] = nil
            phases[channel] = .gone
        } catch {
            guard started == epoch else { return }
            phases[channel] = lists[channel] == nil ? .failed(Copy.capturedLoadFailed) : .loaded
        }
    }

    /// "Show more" — the next page, appended in place. A row the list already holds (new items arrived at the top
    /// since the last read and shifted the pages) is never shown twice.
    func loadMore(_ channel: String) async {
        guard let current = lists[channel], current.hasMore, !loadingMore.contains(channel) else { return }
        let started = epoch
        loadingMore.insert(channel)
        defer { if started == epoch { loadingMore.remove(channel) } }
        do {
            let answer = try await api.fetchChannelItems(channel: channel, offset: current.items.count,
                                                         limit: CapturedItems.pageSize, etag: nil)
            guard started == epoch, let page = answer.value, var list = lists[channel] else { return }
            let held = Set(list.items.map { "\($0.kind.rawValue)|\($0.id)" })
            list.items += page.items.filter { !held.contains("\($0.kind.rawValue)|\($0.id)") }
            // A short page is the end, whatever the total said a moment ago (a list can shrink between reads).
            list.total = page.items.count < CapturedItems.pageSize ? list.items.count : page.total
            lists[channel] = list
        } catch {
            // The rows already shown stay; the button stays for another try.
        }
    }
}
