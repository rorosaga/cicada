import Foundation
import Observation

/// A page's link facts (`GET /entities/{id}/links`, owner rulings 2026-10-14), in memory, by entity id. **Not a Store
/// domain** (like `/provenance`): fetched when an article with web links is drawn, revalidated by ETag on every ask (a
/// view switch or a new look shows at once), a failure keeps the last-known-good copy, a 404 forgets it. Emptied on a
/// bank switch (`ContentView`).
@Observable
@MainActor
final class LinkFactsCache {
    static let shared = LinkFactsCache()
    static let capacity = 48

    private struct Tagged { let etag: String?; let value: PageLinkFacts }

    /// The last answer per page, observed so a card redraws when it lands.
    private(set) var facts: [String: PageLinkFacts] = [:]
    @ObservationIgnored private var tagged = LRUCache<String, Tagged>(capacity: LinkFactsCache.capacity)
    @ObservationIgnored private var inFlight: [String: Task<Void, Never>] = [:]
    /// Bumped by `reset()`: an answer that lands after a bank switch belongs to the bank it was asked in, and is dropped
    /// (the `BacklogCache` rule) — cancelling its task does not stop a response already on its way.
    @ObservationIgnored private var epoch = 0
    @ObservationIgnored private let fetch: @Sendable (String, String?) async throws -> Conditional<PageLinkFacts>

    init(fetch: @escaping @Sendable (String, String?) async throws -> Conditional<PageLinkFacts> = { id, etag in
        try await APIClient.shared.fetchEntityLinks(entityId: id, etag: etag)
    }) {
        self.fetch = fetch
    }

    func reset() {
        epoch &+= 1
        facts = [:]
        tagged = LRUCache(capacity: Self.capacity)
        inFlight.values.forEach { $0.cancel() }
        inFlight = [:]
    }

    /// What is known about `url` on `entityId`'s page now; a URL not (yet) answered for is only its site.
    func fact(_ url: String, on entityId: String?) -> LinkFact {
        guard let entityId, let page = facts[entityId], let fact = page.fact(for: url) else { return .unknown(url) }
        return fact
    }

    /// Ask again (an ETag makes an unchanged page a 304). One request per page at a time.
    func refresh(_ entityId: String) async {
        if let running = inFlight[entityId] { return await running.value }
        let asked = epoch
        let task = Task { [weak self] in
            guard let self else { return }
            let cached = self.tagged.get(entityId)
            defer { if self.epoch == asked { self.inFlight[entityId] = nil } }
            do {
                let result = try await self.fetch(entityId, cached?.etag)
                guard self.epoch == asked else { return }   // the bank switched while this was out
                if let value = result.value {
                    self.tagged.set(entityId, Tagged(etag: result.etag, value: value))
                    self.facts[entityId] = value
                } else if let cached, self.facts[entityId] == nil {
                    self.facts[entityId] = cached.value
                }
            } catch APIError.httpError(404, _) {
                guard self.epoch == asked else { return }
                self.tagged.remove(entityId)
                self.facts[entityId] = nil
            } catch {
                // Never blank: the last-known-good copy stays.
            }
        }
        inFlight[entityId] = task
        await task.value
    }
}
