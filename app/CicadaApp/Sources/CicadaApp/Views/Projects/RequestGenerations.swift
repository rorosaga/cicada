import Foundation

/// Audit 2026-10-05 P2-6 — which request for a cached resource is the newest. An epoch only separates banks; two
/// refreshes of one resource in one bank (a write's refresh and a sync event's, say) can land in either order, and the
/// older answer must not overwrite the newer one. Each refresh takes a generation as it starts; only the latest started
/// for its key may write what it got. A newer request that fails leaves the last value standing (never blank, DR-43).
struct RequestGenerations {
    private var latest: [String: Int] = [:]
    private var next = 1

    /// Start a request for `key`; the answer is current only while this stays the latest generation for it.
    mutating func begin(_ key: String) -> Int {
        let generation = next
        next &+= 1
        latest[key] = generation
        return generation
    }

    func isLatest(_ key: String, _ generation: Int) -> Bool { latest[key] == generation }

    /// The newest generation started for `key` (0 if none).
    func current(_ key: String) -> Int { latest[key] ?? 0 }
}
