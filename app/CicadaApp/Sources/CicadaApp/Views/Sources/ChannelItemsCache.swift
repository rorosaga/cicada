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
    /// Sources v4 — the watched days opened so far, by episode id, and the ones whose read failed with nothing held.
    private(set) var days: [String: WatchedDay] = [:]
    private(set) var failedDays: Set<String> = []
    @ObservationIgnored private var dayTags: [String: String] = [:]
    /// Sources v4 (review of #358) — the Messages chats opened so far, by conversation hash.
    private(set) var chats: [String: ChatSittings] = [:]
    private(set) var failedChats: Set<String> = []
    @ObservationIgnored private var chatTags: [String: String] = [:]

    private struct Tag { let limit: Int; let etag: String }

    @ObservationIgnored private let api: any ChannelItemsAPI
    /// The ETag of the first-page read that covers every row shown — tied to its `limit`, since another limit is
    /// another body (and another tag) on the server.
    @ObservationIgnored private var tags: [String: Tag] = [:]
    @ObservationIgnored private var epoch = 0

    init(api: any ChannelItemsAPI = APIClient.shared) { self.api = api }

    /// source-page-v3 — a search is its own list, held beside the channel's (the search field clears back to the held
    /// list instantly). The separator never occurs in a channel id.
    nonisolated static func key(_ channel: String, query: String) -> String {
        let words = SourceSearch.normalized(query)
        return words.isEmpty ? channel : channel + "\u{1F}" + words
    }

    func list(_ channel: String, query: String = "") -> ChannelItemsList? { lists[Self.key(channel, query: query)] }
    func phase(_ channel: String, query: String = "") -> Phase { phases[Self.key(channel, query: query)] ?? .idle }
    func isLoadingMore(_ channel: String, query: String = "") -> Bool {
        loadingMore.contains(Self.key(channel, query: query))
    }
    func day(_ episode: String) -> WatchedDay? { days[episode] }
    func dayFailed(_ episode: String) -> Bool { failedDays.contains(episode) && days[episode] == nil }
    func sittings(_ chat: String) -> ChatSittings? { chats[chat] }
    func sittingsFailed(_ chat: String) -> Bool { failedChats.contains(chat) && chats[chat] == nil }

    /// Forget everything — a bank switch (`ContentView`, R-PU26's reason).
    func reset() {
        epoch &+= 1
        lists = [:]
        phases = [:]
        loadingMore = []
        tags = [:]
        days = [:]
        failedDays = []
        dayTags = [:]
        chats = [:]
        failedChats = []
        chatTags = [:]
    }

    /// Read (or revalidate) one chat's sittings when its row opens; a 304 or a failure keeps what is held.
    func refreshSittings(_ chat: String) async {
        let started = epoch
        do {
            let answer = try await api.fetchChatSittings(conversation: chat, etag: chats[chat] == nil ? nil : chatTags[chat])
            guard started == epoch else { return }
            if let page = answer.value {
                chats[chat] = page
                chatTags[chat] = answer.etag
            }
            failedChats.remove(chat)
        } catch {
            guard started == epoch else { return }
            failedChats.insert(chat)
        }
    }

    /// Sources v4 — read (or revalidate) one watched day when it opens; a 304 or a failure keeps what is held.
    func refreshDay(_ episode: String) async {
        let started = epoch
        do {
            let answer = try await api.fetchWatchedDay(episode: episode, etag: days[episode] == nil ? nil : dayTags[episode])
            guard started == epoch else { return }
            if let day = answer.value {
                days[episode] = day
                dayTags[episode] = answer.etag
            }
            failedDays.remove(episode)
        } catch {
            guard started == epoch else { return }
            failedDays.insert(episode)
        }
    }

    /// Re-read the rows already shown (at least the first page), sending the tag only when it covers the same rows —
    /// a 304 then keeps the list exactly as it is.
    /// source-page-v3: `query` narrows the read to a source page's search; its list is held under its own key.
    func refresh(_ channel: String, query: String = "") async {
        let started = epoch
        let key = Self.key(channel, query: query)
        let cached = lists[key]
        let limit = CapturedItems.refreshLimit(shown: cached?.items.count ?? 0)
        if cached == nil { phases[key] = .loading }
        let etag = cached == nil ? nil : tags[key].flatMap { $0.limit == limit ? $0.etag : nil }
        do {
            let answer = try await fetch(channel, query: query, offset: 0, limit: limit, etag: etag)
            guard started == epoch else { return }
            if let page = answer.value {
                lists[key] = ChannelItemsList(items: page.items, total: page.total, all: page.all, latest: page.latest)
                tags[key] = answer.etag.map { Tag(limit: limit, etag: $0) }
            }
            phases[key] = .loaded
        } catch APIError.httpError(404, _) {
            guard started == epoch else { return }
            lists[key] = nil
            tags[key] = nil
            phases[key] = .gone
        } catch {
            guard started == epoch else { return }
            phases[key] = lists[key] == nil ? .failed(Copy.capturedLoadFailed) : .loaded
        }
    }

    /// "Show more" — the next page, appended in place. A row the list already holds (new items arrived at the top
    /// since the last read and shifted the pages) is never shown twice.
    func loadMore(_ channel: String, query: String = "") async {
        let key = Self.key(channel, query: query)
        guard let current = lists[key], current.hasMore, !loadingMore.contains(key) else { return }
        let started = epoch
        loadingMore.insert(key)
        defer { if started == epoch { loadingMore.remove(key) } }
        do {
            let answer = try await fetch(channel, query: query, offset: current.items.count,
                                         limit: CapturedItems.pageSize, etag: nil)
            guard started == epoch, let page = answer.value, var list = lists[key] else { return }
            let held = Set(list.items.map { "\($0.kind.rawValue)|\($0.id)" })
            list.items += page.items.filter { !held.contains("\($0.kind.rawValue)|\($0.id)") }
            // A short page is the end, whatever the total said a moment ago (a list can shrink between reads).
            list.total = page.items.count < CapturedItems.pageSize ? list.items.count : page.total
            lists[key] = list
        } catch {
            // The rows already shown stay; the button stays for another try.
        }
    }

    /// The channel's own read when there is no search (the fakes' and an older backend's door), the search's when there is.
    private func fetch(_ channel: String, query: String, offset: Int, limit: Int, etag: String?) async throws
        -> Conditional<ChannelItemsPage> {
        let words = SourceSearch.normalized(query)
        if words.isEmpty {
            return try await api.fetchChannelItems(channel: channel, offset: offset, limit: limit, etag: etag)
        }
        return try await api.fetchChannelItems(channel: channel, offset: offset, limit: limit, query: words, etag: etag)
    }
}
