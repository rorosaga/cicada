import Foundation

/// `GET /entities/{id}`'s client mapping for its ETag (2026-10-28, `page_blocks.card_etag`). The card is asked on
/// every open; the last answer per page is held here with its ETag, sent back as `If-None-Match`, and a 304 returns
/// the held copy. **Not a Store domain** (the `LinkFactsCache` rule): in memory, by page id, a few dozen pages at most,
/// emptied on a bank switch (`ContentView`) — though the server's ETag names the bank as well, so a held page can never
/// answer for another bank's.
struct EntityCardCache {
    static let capacity = 24

    struct Held {
        let etag: String
        let entity: Entity
    }

    private var cards = LRUCache<String, Held>(capacity: EntityCardCache.capacity)

    var count: Int { cards.count }

    mutating func held(_ id: String) -> Held? { cards.get(id) }

    mutating func forget(_ id: String) { cards.remove(id) }

    /// The page to show for one answer: a fresh body is held under its ETag (or forgotten when it carries none); a 304
    /// is the held copy. A 304 with nothing held cannot happen (no ETag was sent) and reads as unreachable.
    mutating func settle(_ id: String, _ result: Conditional<Entity>, held: Held?) throws -> Entity {
        if let value = result.value {
            if let etag = result.etag, !etag.isEmpty {
                cards.set(id, Held(etag: etag, entity: value))
            } else {
                cards.remove(id)
            }
            return value
        }
        if let held { return held.entity }
        throw APIError.serverUnreachable
    }
}
