import Foundation

/// The convergence rules behind `ConnectView`'s live-memory-root override
/// (G88 follow-up, Devin PR #28 round 2). The page renders its setup
/// snippets against `installRoot()`'s `<home>/memory` guess until the app's
/// own backend says which `CICADA_MEMORY_PATH` it actually runs with; this
/// type decides, from a sequence of `GET /healthz` outcomes, which root to
/// show and whether to ask again. Split out of the view so those rules are
/// testable without a view, a timer or a network.
///
/// A failed probe is retried with 0.5 s → 8 s backoff — the just-spawned
/// backend is usually not listening yet on first paint, and one attempt
/// used to leave the guess in place for good. An answer that carries a root
/// ends the retries; an answer without one (an older backend) ends them
/// too, since asking again can't change it. A live root, once seen, is
/// never replaced by the guess: a later failure keeps it, and only another
/// live root can supersede it.
struct LiveMemoryRootProbe: Equatable {
    enum Outcome: Equatable {
        /// The request threw — the backend isn't listening (yet).
        case unreachable
        /// The backend answered; `nil`/empty means it doesn't report a root.
        case answered(String?)
    }

    static let minDelay: TimeInterval = 0.5
    static let maxDelay: TimeInterval = 8

    /// The root the backend last reported; `nil` while none has.
    private(set) var liveRoot: String?
    /// Seconds to wait before asking again; `nil` once there's nothing left
    /// to learn from asking.
    private(set) var nextDelay: TimeInterval? = LiveMemoryRootProbe.minDelay

    /// (Re)arm the retry schedule — on first appearance, and whenever the
    /// backend-reachability signal flips to connected. Never touches
    /// `liveRoot`.
    mutating func beginAttempts() {
        nextDelay = Self.minDelay
    }

    /// Record one probe outcome. Returns `true` when the shown root changed
    /// and the catalog must be rebuilt.
    @discardableResult
    mutating func observe(_ outcome: Outcome) -> Bool {
        switch outcome {
        case .unreachable:
            // Converged already: a blip can't undo it, and there's no reason
            // to keep hammering — the next reconnect re-asks.
            if liveRoot != nil { nextDelay = nil; return false }
            nextDelay = min(Self.maxDelay, (nextDelay ?? Self.minDelay) * 2)
            return false
        case .answered(let root):
            nextDelay = nil
            guard let root, !root.isEmpty, root != liveRoot else { return false }
            liveRoot = root
            return true
        }
    }
}
