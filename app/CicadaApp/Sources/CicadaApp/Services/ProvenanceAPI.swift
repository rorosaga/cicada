import Foundation

/// The four read routes the provenance viewer needs (G118 slice 2, server
/// half merged in PR #72). A protocol for the same reason `SyncAPI` is one:
/// `ProvenanceCache` is driven by a fake in tests, and `APIClient` conforms
/// below.
///
/// None of these payloads is a Store domain (R-PB11, design K10): they are
/// fetched on demand and cached in memory only, so there is no
/// `VersionVector` mapping to ship. `/text`, `/citations` and `/provenance`
/// carry an ETag for that in-memory cache (`etag` in, 304 → `notModified`);
/// `/span` has none by design (slice-1 R9 — the response validates itself).
protocol ProvenanceAPI: Sendable {
    func fetchEpisodeSpan(episode: String, start: Int, end: Int, hash: String?) async throws -> EpisodeSpan
    func fetchEpisodeText(episode: String, focus: ReaderFocusQuery, etag: String?) async throws
        -> Conditional<EpisodeText>
    func fetchEntityProvenance(entityId: String, etag: String?) async throws -> Conditional<EntityProvenance>
    func fetchEpisodeCitations(episode: String, etag: String?) async throws -> Conditional<EpisodeCitations>
}

/// What `/episodes/{id}/text` is asked to focus (R-PB5): an asserted span
/// (`?start&end[&hash]`), a derived mention of an entity (`?focus=<id>`), or
/// nothing. Its `queryItems` are the one place the query is spelled.
enum ReaderFocusQuery: Hashable, Sendable {
    case none
    case span(start: Int, end: Int, hash: String?)
    case mention(entityId: String)

    var queryItems: [URLQueryItem] {
        switch self {
        case .none:
            return []
        case let .span(start, end, hash):
            var items = [URLQueryItem(name: "start", value: String(start)),
                         URLQueryItem(name: "end", value: String(end))]
            if let hash, !hash.isEmpty { items.append(URLQueryItem(name: "hash", value: hash)) }
            return items
        case let .mention(entityId):
            return [URLQueryItem(name: "focus", value: entityId)]
        }
    }
}

extension APIClient: ProvenanceAPI {
    /// A document id is a bare stem (`evidence._DOC_ID_RE`), but it lands in a
    /// PATH, so encode it the way every other id-in-a-path is encoded here
    /// (`fetchConversation`): a `/`, `?` or `#` must never reshape the URL.
    nonisolated static func provenancePath(_ prefix: String, _ id: String, _ suffix: String,
                                           query: [URLQueryItem] = []) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        let encoded = id.addingPercentEncoding(withAllowedCharacters: allowed) ?? id
        var components = URLComponents()
        components.queryItems = query.isEmpty ? nil : query
        // `URLQueryItem` leaves `+` alone and a server reads `+` as a space;
        // a hash is hex and an entity id a slug, but encode it anyway so the
        // rule does not depend on what the values happen to look like today.
        let q = components.percentEncodedQuery?.replacingOccurrences(of: "+", with: "%2B")
        return "\(prefix)/\(encoded)\(suffix)" + (q.map { "?\($0)" } ?? "")
    }

    func fetchEpisodeSpan(episode: String, start: Int, end: Int, hash: String?) async throws -> EpisodeSpan {
        var query = [URLQueryItem(name: "start", value: String(start)),
                     URLQueryItem(name: "end", value: String(end))]
        if let hash, !hash.isEmpty { query.append(URLQueryItem(name: "hash", value: hash)) }
        let path = Self.provenancePath("/episodes", episode, "/span", query: query)
        let result: Conditional<EpisodeSpan> = try await getConditional(path, etag: nil)
        guard let value = result.value else { throw APIError.decodingError("empty /span response") }
        return value
    }

    func fetchEpisodeText(episode: String, focus: ReaderFocusQuery, etag: String?) async throws
        -> Conditional<EpisodeText> {
        try await getConditional(Self.provenancePath("/episodes", episode, "/text", query: focus.queryItems),
                                 etag: etag)
    }

    func fetchEntityProvenance(entityId: String, etag: String?) async throws -> Conditional<EntityProvenance> {
        try await getConditional(Self.provenancePath("/entities", entityId, "/provenance"), etag: etag)
    }

    func fetchEpisodeCitations(episode: String, etag: String?) async throws -> Conditional<EpisodeCitations> {
        try await getConditional(Self.provenancePath("/episodes", episode, "/citations"), etag: etag)
    }
}
