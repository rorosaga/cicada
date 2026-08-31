import Foundation
import Observation

// M3 (backlog A2): repo-wide model/user attribution.
/// Thin projection over `Store.contributors` (§5.5). Moved from a per-view
/// `@State` to an app-level, environment-injected VM in Task 7 so switching
/// away from and back to this tab no longer re-fetches or blanks the list.
@Observable
@MainActor
final class ContributorsViewModel {
    private let store: Store

    init(store: Store) {
        self.store = store
    }

    var contributors: [Contributor] { store.contributors.value ?? [] }

    /// `false` until a payload (network or disk-hydrated) has ever landed.
    /// `contributors == []` only means "nothing attributed" once this is true.
    var hasLoaded: Bool { store.contributors.value != nil }

    var isLoading: Bool { store.contributors.isEmpty && store.contributors.isRefreshing }

    var totalCommits: Int { contributors.reduce(0) { $0 + $1.commitCount } }

    /// Surfaced only while nothing has ever loaded — a failed background
    /// refresh over good data stays silent, the same rule `Store.toast` uses.
    /// Computed rather than stored so it clears itself the moment a payload
    /// lands, with no view left holding a stale banner.
    var errorMessage: String? { hasLoaded ? nil : store.toast }

    /// The Retry button's action. The Store hydrates and refreshes this domain
    /// itself (§5.5), so this is the ONLY caller — never an `.onAppear`.
    func load() async {
        await store.refresh([.contributors])
    }
}
