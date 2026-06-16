import Foundation

/// The menu-bar bookworm's mood. Derived from a ``StatusSnapshot`` by the pure
/// ``deriveBookwormState(_:justFinishedAt:now:)`` function so the precedence
/// logic is testable without the menu bar. Replaces the old `CicadaStatus` enum.
enum BookwormState: Equatable {
    /// Cold-start / unknown (before the first poll resolves, or when /status is
    /// unreachable). Idle worm with an occasional blink.
    case awake
    /// A sleep cycle is running; `stage` is clamped to 1...5 for the progress dots.
    case sleeping(stage: Int)
    /// Brief chewing loop right after a cycle finishes (running -> idle, no error).
    case digesting
    /// Inbox empty, fed, idle.
    case happy
    /// Inbox has `count` pending items; the badge renders `min(count, 99)`.
    case curious(count: Int)
    /// No episode ingested in 48h (or never).
    case hungry

    var title: String {
        switch self {
        case .awake: "Awake"
        case .sleeping: "Sleeping"
        case .digesting: "Digesting"
        case .happy: "Happy"
        case .curious: "Curious"
        case .hungry: "Hungry"
        }
    }

    /// One-line detail string shown under the title in the dropdown header.
    var detail: String {
        switch self {
        case .awake: "idle — listening for episodes"
        case .sleeping(let stage): "stage \(stage)/5"
        case .digesting: "chewing on new memories…"
        case .curious(let n): "\(n) item\(n == 1 ? "" : "s") waiting"
        case .hungry: "no episodes in 48h"
        case .happy: "inbox clear"
        }
    }

    /// Stable identity used for animation-frame caching and transition checks.
    /// Two `.curious` cases with different counts share a case name (the count
    /// only changes the badge overlay, not the animation), so the frame timer
    /// is not restarted on every badge change.
    var caseName: String {
        switch self {
        case .awake: "awake"
        case .sleeping: "sleeping"
        case .digesting: "digesting"
        case .happy: "happy"
        case .curious: "curious"
        case .hungry: "hungry"
        }
    }
}

// MARK: - Status snapshot

/// The decoded `GET /status` aggregate (or the client-side composed fallback).
/// Matches the §0 wire shape; ``APIClient.fetchStatus()`` produces it from either
/// source. Kept `Codable` so the real `/status` endpoint can decode straight in.
struct StatusSnapshot: Codable, Equatable {
    struct Sleep: Codable, Equatable {
        var status: String          // "idle" | "running"
        var stage: Int
        var totalStages: Int
        var cycleId: String?
        var error: String?
    }
    struct Inbox: Codable, Equatable {
        var total: Int
        var byKind: [String: Int]
    }
    struct Episodes: Codable, Equatable {
        var unprocessed: Int
        var lastIngestedAt: String?  // ISO8601, null if none
    }

    var sleep: Sleep
    var inbox: Inbox
    var episodes: Episodes
    var lastSleepAt: String?         // ISO8601, null if never
    var nextSleepAt: String?         // ISO8601, null if schedule disabled
}

// MARK: - Date parsing helpers

extension StatusSnapshot {
    /// Parse an ISO8601 timestamp from the snapshot. Tolerant of the
    /// with/without fractional-seconds variants the backend emits.
    static func parseDate(_ iso: String?) -> Date? {
        guard let iso, !iso.isEmpty else { return nil }
        let withFractional = ISO8601DateFormatter()
        withFractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = withFractional.date(from: iso) { return d }
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        return plain.date(from: iso)
    }
}

// MARK: - Pure state derivation

/// Maps a status snapshot to a ``BookwormState``. Pure so the precedence logic
/// is unit-testable. Precedence (highest wins):
/// sleeping > digesting > hungry > curious > happy > awake.
func deriveBookwormState(
    _ s: StatusSnapshot,
    justFinishedAt: Date?,
    now: Date = .now
) -> BookwormState {
    if s.sleep.status == "running" {
        return .sleeping(stage: max(1, min(5, s.sleep.stage)))
    }
    if let f = justFinishedAt, now.timeIntervalSince(f) < 6 {
        return .digesting
    }
    let stale = StatusSnapshot.parseDate(s.episodes.lastIngestedAt)
        .map { now.timeIntervalSince($0) > 48 * 3600 } ?? true
    if stale { return .hungry }
    if s.inbox.total > 0 { return .curious(count: s.inbox.total) }
    return .happy
}
