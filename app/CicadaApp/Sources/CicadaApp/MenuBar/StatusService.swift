import Foundation

/// Single abstraction over the menu-bar status source. Today it delegates to
/// ``APIClient/fetchStatus()`` which itself tries `GET /status` and falls back
/// to a client-side compose from the legacy endpoints. Keeping the indirection
/// here means the poll loop and the quick-action refresh share one source, and
/// the eventual switch to a pure `/status` path is contained.
actor StatusService {
    static let shared = StatusService()

    /// Returns the latest snapshot, or `nil` if the backend is unreachable (the
    /// menu bar then holds its last state — `awake` on cold start).
    func fetch() async -> StatusSnapshot? {
        try? await APIClient.shared.fetchStatus()
    }
}
