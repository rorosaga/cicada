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

    var errorMessage: String?

    init(store: Store) {
        self.store = store
    }

    var contributors: [Contributor] { store.contributors.value ?? [] }

    var isLoading: Bool { store.contributors.isEmpty && store.contributors.isRefreshing }

    var totalCommits: Int { contributors.reduce(0) { $0 + $1.commitCount } }

    func load() async {
        errorMessage = nil
        await store.refresh([.contributors])
        if store.contributors.value == nil {
            errorMessage = store.toast
        }
    }
}
