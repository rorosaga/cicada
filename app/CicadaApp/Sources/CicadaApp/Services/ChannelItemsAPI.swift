import Foundation

/// G161 — `GET /sources/channels/{id}/items`: what a source brought in, by name. Not a Store domain: fetched on
/// demand into `ChannelItemsCache` and revalidated with the ETag the server sends — no `VersionVector` mapping (the
/// provenance and Projects reads' precedent). On a protocol so the cache's tests fake it.
protocol ChannelItemsAPI: Sendable {
    func fetchChannelItems(channel: String, offset: Int, limit: Int, etag: String?) async throws
        -> Conditional<ChannelItemsPage>
}

extension APIClient: ChannelItemsAPI {
    /// A channel id carries a `:` (`chat-export:claude`, `folder:<id>`) and lands in a PATH: encoded like every other
    /// id in a path, so a `/`, `?` or `#` never reshapes the URL.
    nonisolated static func channelItemsPath(_ channel: String, offset: Int, limit: Int) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        let encoded = channel.addingPercentEncoding(withAllowedCharacters: allowed) ?? channel
        return "/sources/channels/\(encoded)/items?offset=\(max(0, offset))&limit=\(max(1, limit))"
    }

    func fetchChannelItems(channel: String, offset: Int, limit: Int, etag: String?) async throws
        -> Conditional<ChannelItemsPage> {
        try await getConditional(Self.channelItemsPath(channel, offset: offset, limit: limit), etag: etag)
    }
}
