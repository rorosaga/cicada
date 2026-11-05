import Foundation

/// G161 — `GET /sources/channels/{id}/items`: what a source brought in, by name. Not a Store domain: fetched on
/// demand into `ChannelItemsCache` and revalidated with the ETag the server sends — no `VersionVector` mapping (the
/// provenance and Projects reads' precedent). On a protocol so the cache's tests fake it.
protocol ChannelItemsAPI: Sendable {
    func fetchChannelItems(channel: String, offset: Int, limit: Int, etag: String?) async throws
        -> Conditional<ChannelItemsPage>
    /// source-page-v3 — the same page narrowed by a source page's one search (`q`); an empty `query` is no search.
    func fetchChannelItems(channel: String, offset: Int, limit: Int, query: String, etag: String?) async throws
        -> Conditional<ChannelItemsPage>
    /// Sources v4 — one watched day's videos (`GET /sources/watch-history/days/{episode}`), read when the day opens.
    func fetchWatchedDay(episode: String, etag: String?) async throws -> Conditional<WatchedDay>
    /// Sources v4 (review of #358) — one Messages chat's sittings (`GET /sources/messages/chats/{id}/sittings`).
    func fetchChatSittings(conversation: String, etag: String?) async throws -> Conditional<ChatSittings>
    /// 2026-11-04 — where a channel's items live: accounts, each with its collections.
    func fetchChannelCollections(channel: String, etag: String?) async throws -> Conditional<ChannelCollections>
    /// G154 — every card on this Mac as a face (`GET /sources/contacts-local/book`). Not a Store domain, no ETag.
    func fetchContactsBook() async throws -> ContactsBook
}

extension ChannelItemsAPI {
    /// A fake that knows no search answers a search with the whole page.
    func fetchChannelItems(channel: String, offset: Int, limit: Int, query: String, etag: String?) async throws
        -> Conditional<ChannelItemsPage> {
        try await fetchChannelItems(channel: channel, offset: offset, limit: limit, etag: etag)
    }

    /// A fake that lists items only never opens a day.
    func fetchWatchedDay(episode: String, etag: String?) async throws -> Conditional<WatchedDay> {
        throw APIError.serverUnreachable
    }

    func fetchChatSittings(conversation: String, etag: String?) async throws -> Conditional<ChatSittings> {
        throw APIError.serverUnreachable
    }

    /// A fake that lists items only holds no address book.
    func fetchContactsBook() async throws -> ContactsBook { throw APIError.serverUnreachable }

    /// A fake that lists items only files them nowhere: the page lists them directly.
    func fetchChannelCollections(channel: String, etag: String?) async throws -> Conditional<ChannelCollections> {
        throw APIError.serverUnreachable
    }
}

extension APIClient: ChannelItemsAPI {
    /// A channel id carries a `:` (`chat-export:claude`, `folder:<id>`) and lands in a PATH: encoded like every other
    /// id in a path, so a `/`, `?` or `#` never reshapes the URL. source-page-v3: a search rides `q`, every character
    /// but the unreserved ones encoded, so `&`, `=`, `+` and `#` stay words; cut at the backend's cap.
    nonisolated static func channelItemsPath(_ channel: String, offset: Int, limit: Int, query: String = "") -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        // 2026-11-04 — a list of one collection (a calendar, a Reminders list, a Notes folder) rides `collection`.
        let (base, collection) = SourceListKey.parts(channel)
        let encoded = base.addingPercentEncoding(withAllowedCharacters: allowed) ?? base
        var path = "/sources/channels/\(encoded)/items?offset=\(max(0, offset))&limit=\(max(1, limit))"
        if let collection {
            path += "&collection=" + (collection.addingPercentEncoding(withAllowedCharacters: SourceSearch.queryAllowed)
                                      ?? "")
        }
        let words = SourceSearch.normalized(query)
        guard !words.isEmpty else { return path }
        return path + "&q=" + (words.addingPercentEncoding(withAllowedCharacters: SourceSearch.queryAllowed) ?? "")
    }

    func fetchChannelItems(channel: String, offset: Int, limit: Int, etag: String?) async throws
        -> Conditional<ChannelItemsPage> {
        try await getConditional(Self.channelItemsPath(channel, offset: offset, limit: limit), etag: etag)
    }

    /// G161 (ROR-111) — where one listed item lives, read on the person's click, never kept. Encoded as a list's path.
    nonisolated static func itemPlacePath(channel: String, item: String) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        let base = SourceListKey.parts(channel).0
        return "/sources/channels/\(base.addingPercentEncoding(withAllowedCharacters: allowed) ?? base)"
            + "/items/\(item.addingPercentEncoding(withAllowedCharacters: allowed) ?? item)/place"
    }

    func fetchItemPlace(channel: String, item: String) async throws -> ItemPlace {
        let answer: Conditional<ItemPlace> = try await getConditional(Self.itemPlacePath(channel: channel, item: item),
                                                                      etag: nil)
        guard let place = answer.value else { throw APIError.serverUnreachable }
        return place
    }

    /// 2026-11-04 — where a channel's items live (`GET /sources/channels/{id}/collections`).
    func fetchChannelCollections(channel: String, etag: String?) async throws -> Conditional<ChannelCollections> {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        let encoded = channel.addingPercentEncoding(withAllowedCharacters: allowed) ?? channel
        return try await getConditional("/sources/channels/\(encoded)/collections", etag: etag)
    }

    func fetchChannelItems(channel: String, offset: Int, limit: Int, query: String, etag: String?) async throws
        -> Conditional<ChannelItemsPage> {
        try await getConditional(Self.channelItemsPath(channel, offset: offset, limit: limit, query: query), etag: etag)
    }
}
