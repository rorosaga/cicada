import Foundation

/// Owner ruling 2026-10-16 — "Settled by a check": its read, its undo and the one-tap promotion of a citation to a
/// tracked source. Not a Store domain: fetched on demand into `SettledChecks` and cached in memory (no ETag, no
/// `VersionVector` mapping). On a protocol so the model's tests fake it.
protocol SettledChecksAPI: Sendable {
    func fetchSettledChecks() async throws -> [SettledCheck]
    func undoSettledCheck(id: String) async throws
    /// The person's own add-source route (`POST /entities/{id}/sources`), the one "Use this source" takes: a citation
    /// becomes a tracked source only by this tap, never automatically.
    func trackCitation(entityId: String, ref: String, predicate: String?) async throws
}

extension APIClient: SettledChecksAPI {
    func trackCitation(entityId: String, ref: String, predicate: String?) async throws {
        _ = try await addEntitySource(entityId: entityId, ref: ref, predicate: predicate)
    }
}
