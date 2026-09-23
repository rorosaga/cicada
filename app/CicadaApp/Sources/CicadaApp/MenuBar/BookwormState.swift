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
    /// Shown on the Sleep page (never the menu bar — R2) while intake is
    /// being consumed (an upload/import is in flight, `Store.intakeInFlight`)
    /// or the queue is non-empty and Sleep is idle. `deriveSleepPageMood`
    /// returns this where it used to return `.curious(count:)`;
    /// `deriveBookwormState` (menu bar) is byte-for-byte unchanged and
    /// `.curious` keeps meaning "inbox items" there (G125 R2).
    case reading
    /// The last Sleep cycle failed (`/status.sleep.error` is set). Red pupils
    /// and a glitch frame. Outranks everything but a running cycle (R6): the
    /// Store stamps `justFinishedAt` on ANY running→idle edge, so without
    /// this order a failed cycle would chew for six seconds first. Clears when
    /// the backend clears the error, i.e. when the next cycle starts.
    case error

    var title: String {
        switch self {
        case .awake: "Awake"
        case .sleeping: "Sleeping"
        case .digesting: "Digesting"
        case .happy: "Happy"
        case .curious: "Curious"
        case .hungry: "Hungry"
        case .reading: "Reading"
        case .error: "Error"
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
        case .reading: "reading what's waiting"
        case .error: "last sleep cycle failed"
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
        case .reading: "reading"
        case .error: "error"
        }
    }

    /// The inbox count the badge draws (1…99) — `0` for every other state.
    var badgeCount: Int {
        if case .curious(let n) = self { return max(1, min(99, n)) }
        return 0
    }

    /// The 1…5 stage the sleeping frames light up — `0` for every other state.
    var stageNumber: Int {
        if case .sleeping(let s) = self { return max(0, min(5, s)) }
        return 0
    }

    /// Identity of the FRAME SET, as opposed to `caseName` (identity of the
    /// animation loop): `.curious` bakes its count and `.sleeping` its stage
    /// into the frames (R2), so they are part of the key the renderer caches
    /// by (R5). `curious|47`, `sleeping|3`, `awake`.
    var spriteKey: String {
        switch self {
        case .curious: "\(caseName)|\(badgeCount)"
        case .sleeping: "\(caseName)|\(stageNumber)"
        default: caseName
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

    /// G139 — facts about the backend that name nothing (R-O21/R-O22): the
    /// usage ledger's switch, the three outbound gates, and which env switches
    /// are set, by name. Optional, so the on-disk snapshot cache and an older
    /// backend still decode; the memberwise init keeps working through the
    /// defaults.
    var telemetry: String? = nil
    var gates: Gates? = nil
    var envOverrides: [String]? = nil

    /// Each gate optional too: a missing key reads as "—" on Privacy & data,
    /// never as a guessed On or Off, and never fails the whole `/status`
    /// decode (which would blank the menu-bar bookworm with it).
    struct Gates: Codable, Equatable {
        var connectorFetch: Bool?
        var feedFetch: Bool?
        var logoFetch: Bool?
    }
}

// MARK: - Date parsing helpers

extension StatusSnapshot {
    /// Parse an ISO8601 timestamp from the snapshot. Tolerant of the
    /// with/without fractional-seconds variants the backend emits.
    ///
    /// A string with no zone is read as local time in `naiveTimeZone`
    /// (Track O review, R-O10): `sleep_scheduler.next_run_at` returns a naive
    /// `datetime.now()`-based ISO string for the daily and interval modes
    /// (e.g. `2026-09-24T03:00:00`), and `.withInternetDateTime` requires a
    /// zone, so every schedule read as "not scheduled". The backend and the
    /// app share one machine, so naive means local. This only ever turns a
    /// `nil` into a date — an offset-bearing string parses exactly as before.
    static func parseDate(_ iso: String?, naiveTimeZone: TimeZone = .current) -> Date? {
        guard let iso, !iso.isEmpty else { return nil }
        let withFractional = ISO8601DateFormatter()
        withFractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = withFractional.date(from: iso) { return d }
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        if let d = plain.date(from: iso) { return d }
        let naive = DateFormatter()
        naive.locale = Locale(identifier: "en_US_POSIX")
        naive.timeZone = naiveTimeZone
        for format in ["yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd'T'HH:mm:ss.SSSSSS", "yyyy-MM-dd'T'HH:mm:ss.SSS"] {
            naive.dateFormat = format
            if let d = naive.date(from: iso) { return d }
        }
        return nil
    }
}

// MARK: - Pure state derivation

/// Maps a status snapshot to a ``BookwormState``. Pure so the precedence logic
/// is unit-testable. Precedence (highest wins):
/// sleeping > error > digesting > hungry > curious > happy > awake.
func deriveBookwormState(
    _ s: StatusSnapshot,
    justFinishedAt: Date?,
    now: Date = .now
) -> BookwormState {
    if s.sleep.status == "running" {
        return .sleeping(stage: max(1, min(5, s.sleep.stage)))
    }
    if let err = s.sleep.error, !err.isEmpty {
        return .error
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
