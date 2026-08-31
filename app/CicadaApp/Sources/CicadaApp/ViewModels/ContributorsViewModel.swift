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

    /// VM-owned, persistent load-error text. `Store.toast` is transient —
    /// `ContentView` auto-clears it ~4s after it's set — so a screen that
    /// merely *mirrored* `store.toast` (the old implementation) showed Retry
    /// for those 4 seconds and then silently decayed into an endless
    /// "loading" spinner even though nothing had ever loaded. This is set the
    /// moment a never-loaded refresh finishes without landing data, and holds
    /// that value until either a retry starts or contributor data actually
    /// lands — whichever comes first.
    ///
    /// Latched lazily on every read of `errorMessage`, not only from
    /// `load()`: the Store hydrates and refreshes `.contributors` on its own
    /// (§5.5, cold hydrate + SSE-driven `refreshAll`/`refresh`), so the
    /// failure this is meant to catch is very often NOT triggered by this
    /// VM's own `load()` call at all.
    private var loadError: String?

    /// Error → never-loaded → loaded. A failed background refresh over good
    /// data stays silent (same rule `Store.toast` uses) because this only
    /// ever latches a new value while `!hasLoaded`.
    var errorMessage: String? {
        if hasLoaded {
            loadError = nil
        } else if !store.contributors.isRefreshing, let toast = store.toast {
            loadError = toast
        }
        return hasLoaded ? nil : loadError
    }

    /// The Retry button's action. The Store hydrates and refreshes this domain
    /// itself (§5.5), so this is the ONLY caller — never an `.onAppear`.
    func load() async {
        // Clear the stale error immediately so the view falls back to its
        // loading branch for the duration of the retry, instead of showing a
        // Retry button beside a request that's already in flight.
        loadError = nil
        await store.refresh([.contributors])
    }
}
