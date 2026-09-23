import Foundation
import Observation

/// A least-recently-used map. Pure and tested: the hover preview's span
/// cache is bounded by the design (§4.2 — 256 entries keyed by
/// `(episode, start, end, hash)`), and so is everything else here, because
/// these payloads live in memory only (R-PB11 — none is a Store domain).
struct LRUCache<Key: Hashable, Value> {
    let capacity: Int
    private var storage: [Key: Value] = [:]
    private var order: [Key] = []   // least recent first

    init(capacity: Int) { self.capacity = max(1, capacity) }

    var count: Int { storage.count }

    /// Reads and marks `key` most recent.
    mutating func get(_ key: Key) -> Value? {
        guard let value = storage[key] else { return nil }
        touch(key)
        return value
    }

    mutating func set(_ key: Key, _ value: Value) {
        storage[key] = value
        touch(key)
        while order.count > capacity {
            storage[order.removeFirst()] = nil
        }
    }

    mutating func remove(_ key: Key) {
        storage[key] = nil
        order.removeAll { $0 == key }
    }

    private mutating func touch(_ key: Key) {
        order.removeAll { $0 == key }
        order.append(key)
    }
}

/// What a provenance fetch came back with. `gone` is a 404 — the document or
/// entity is not in this bank (any more), which every surface says in words
/// rather than as an error (§4.4 States).
enum ProvenanceLoad<T> {
    case loaded(T)
    case gone
    case failed(String)

    var value: T? {
        if case let .loaded(v) = self { return v }
        return nil
    }
}

/// The provenance viewer's in-memory cache (G118 slice 2). One for the app,
/// owned by `CicadaApp` as `@State` (like `appRouter`) and injected into the
/// main window scene beside `ProvenanceRouter`.
///
/// **Never a Store domain** (R-PB11, design K10): these payloads are fetched
/// on demand, so there is no `SnapshotCache` entry and no `VersionVector`
/// mapping to ship. ETagged payloads are revalidated on every ask — a 304 is
/// cheap and keeps "Where this came from" honest after a Sleep cycle — and a
/// failure keeps the last-known-good value, the app's never-blank rule.
///
/// **Not keyed by bank, so a bank switch empties it** (`reset()`, R-PU26):
/// episode ids restart at `_001` every day in every bank, so without the
/// reset another bank's document could be served — or kept as
/// last-known-good — for an id this bank also has.
@Observable
@MainActor
final class ProvenanceCache {
    static let spanCapacity = 256
    static let documentCapacity = 12
    static let provenanceCapacity = 64
    static let citationsCapacity = 24

    struct SpanKey: Hashable { let episode: String; let start: Int; let end: Int; let hash: String }
    struct DocumentKey: Hashable { let episode: String; let focus: ReaderFocusQuery }
    private struct Tagged<T> { let etag: String?; let value: T }

    @ObservationIgnored private let api: any ProvenanceAPI
    @ObservationIgnored private var spans = LRUCache<SpanKey, EpisodeSpan>(capacity: ProvenanceCache.spanCapacity)
    @ObservationIgnored private var documents =
        LRUCache<DocumentKey, Tagged<EpisodeText>>(capacity: ProvenanceCache.documentCapacity)
    @ObservationIgnored private var provenances =
        LRUCache<String, Tagged<EntityProvenance>>(capacity: ProvenanceCache.provenanceCapacity)
    @ObservationIgnored private var citationSets =
        LRUCache<String, Tagged<EpisodeCitations>>(capacity: ProvenanceCache.citationsCapacity)

    init(api: any ProvenanceAPI = APIClient.shared) { self.api = api }

    /// Forget everything — called on a bank switch (`ContentView`, R-PU26).
    func reset() {
        spans = LRUCache(capacity: Self.spanCapacity)
        documents = LRUCache(capacity: Self.documentCapacity)
        provenances = LRUCache(capacity: Self.provenanceCapacity)
        citationSets = LRUCache(capacity: Self.citationsCapacity)
    }

    /// The hover preview's words. No ETag by design (slice-1 R9), so a hit is
    /// served from memory without a request.
    func span(_ ev: Evidence) async -> ProvenanceLoad<EpisodeSpan> {
        let key = SpanKey(episode: ev.episode, start: ev.start, end: ev.end, hash: ev.hash)
        if let hit = spans.get(key) { return .loaded(hit) }
        do {
            let value = try await api.fetchEpisodeSpan(episode: ev.episode, start: ev.start, end: ev.end,
                                                       hash: ev.hash.isEmpty ? nil : ev.hash)
            spans.set(key, value)
            return .loaded(value)
        } catch let error where Self.isOutOfRange(error) {
            // R-PU25 — the document was rewritten SHORTER than this span's end
            // (a page description, a re-synced file), so `/span` answers 422.
            // The words moved; they did not fail to load — `/citations`
            // already reads `end > len(text)` as stale. Not cached: the next
            // Sleep may mint the span afresh.
            return .loaded(EpisodeSpan(episode: ev.episode, start: ev.start, end: ev.end, stale: true,
                                       kind: ev.kind))
        } catch {
            return Self.classify(error, cached: nil as EpisodeSpan?)
        }
    }

    func document(episode: String, focus: ReaderFocusQuery) async -> ProvenanceLoad<EpisodeText> {
        let key = DocumentKey(episode: episode, focus: focus)
        let cached = documents.get(key)
        do {
            let result = try await api.fetchEpisodeText(episode: episode, focus: focus, etag: cached?.etag)
            if result.notModified, let cached { return .loaded(cached.value) }
            guard let value = result.value else { return Self.classify(nil, cached: cached?.value) }
            documents.set(key, Tagged(etag: result.etag, value: value))
            return .loaded(value)
        } catch {
            if Self.isGone(error) || Self.isOutOfRange(error) { documents.remove(key) }
            // R-PU25 — `/text` 422s a stored span the document no longer
            // reaches (`provenance.SpanOutOfRange`). The conversation is still
            // here, so open ALL of it under the stale banner rather than
            // "Couldn't open": re-ask with no focus and mark the focus stale
            // (no offsets — R-PB2, so nothing washes).
            if case .span = focus, Self.isOutOfRange(error) {
                return Self.markedStale(await document(episode: episode, focus: .none))
            }
            return Self.classify(error, cached: cached?.value)
        }
    }

    func provenance(entityId: String) async -> ProvenanceLoad<EntityProvenance> {
        let cached = provenances.get(entityId)
        do {
            let result = try await api.fetchEntityProvenance(entityId: entityId, etag: cached?.etag)
            if result.notModified, let cached { return .loaded(cached.value) }
            guard let value = result.value else { return Self.classify(nil, cached: cached?.value) }
            provenances.set(entityId, Tagged(etag: result.etag, value: value))
            return .loaded(value)
        } catch {
            if Self.isGone(error) { provenances.remove(entityId) }
            return Self.classify(error, cached: cached?.value)
        }
    }

    func citations(episode: String) async -> ProvenanceLoad<EpisodeCitations> {
        let cached = citationSets.get(episode)
        do {
            let result = try await api.fetchEpisodeCitations(episode: episode, etag: cached?.etag)
            if result.notModified, let cached { return .loaded(cached.value) }
            guard let value = result.value else { return Self.classify(nil, cached: cached?.value) }
            citationSets.set(episode, Tagged(etag: result.etag, value: value))
            return .loaded(value)
        } catch {
            if Self.isGone(error) { citationSets.remove(episode) }
            return Self.classify(error, cached: cached?.value)
        }
    }

    private static func isGone(_ error: Error) -> Bool {
        if case APIError.httpError(404, _) = error { return true }
        return false
    }

    /// 422 — offsets outside the document (`/span` and `/text` both refuse a
    /// pair past the end). Only ever about offsets: an id is 404, never 422.
    private static func isOutOfRange(_ error: Error) -> Bool {
        if case APIError.httpError(422, _) = error { return true }
        return false
    }

    /// The whole document re-labelled as a stale landing (R-PU25):
    /// `ReaderPresentation` then says "the words may have moved" and lands as
    /// near the old offset as the text still reaches.
    private static func markedStale(_ load: ProvenanceLoad<EpisodeText>) -> ProvenanceLoad<EpisodeText> {
        guard case let .loaded(doc) = load else { return load }
        return .loaded(EpisodeText(
            episode: doc.episode, kind: doc.kind, text: doc.text, length: doc.length, hash: doc.hash,
            truncated: doc.truncated, title: doc.title, timestamp: doc.timestamp, harness: doc.harness,
            origin: doc.origin, conversationId: doc.conversationId, captureKind: doc.captureKind,
            turns: doc.turns, focus: EpisodeFocus(start: nil, end: nil, stale: true)))
    }

    /// A 404 is `gone` even when something was cached — the bank no longer
    /// has it, and saying otherwise would be the stale-highlight bug in
    /// another shape. Any other failure serves last-known-good if there is one.
    private static func classify<T>(_ error: Error?, cached: T?) -> ProvenanceLoad<T> {
        if let error, isGone(error) { return .gone }
        if let cached { return .loaded(cached) }
        return .failed(error?.localizedDescription ?? "empty response")
    }
}
