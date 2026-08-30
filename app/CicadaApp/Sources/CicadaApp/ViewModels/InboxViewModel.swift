import Foundation
import Observation

/// Single ViewModel backing the unified Inbox tab. Thin projection over
/// `Store.inbox` (§5.5): `items` reads straight from the snapshot so a tab
/// switch renders whatever the Store already has, instantly. Resolutions
/// still go straight to `POST /inbox/{id}/resolve` via `APIClient` (mutations
/// aren't a sync domain) and then ask the Store to refresh `.inbox`.
@Observable
@MainActor
final class InboxViewModel {
    private let store: Store

    var errorMessage: String?

    /// Items resolved locally but not yet reflected in `store.inbox` (the
    /// refresh is in flight). Filtered out of `items` so a resolve removes
    /// the card instantly instead of waiting on the round-trip; put back on
    /// failure so the card reappears (a rollback) instead of vanishing for a
    /// request that didn't actually happen.
    private var locallyResolvedIds: Set<String> = []

    /// Wired by the App to `menuBarManager.refreshAfterAction()` so the menu-bar
    /// badge updates the instant an item resolves (mirrors `SleepViewModel`'s
    /// callback hooks). `nil` when no menu bar is attached (previews/tests).
    var onResolved: (() async -> Void)?

    init(store: Store) {
        self.store = store
    }

    var items: [InboxItem] {
        (store.inbox.value ?? []).filter { !locallyResolvedIds.contains($0.id) }
    }

    var isLoading: Bool { store.inbox.isEmpty && store.inbox.isRefreshing }

    /// Sidebar / menu-bar badge — number of pending items.
    var pendingCount: Int { items.count }

    /// Breakdown by kind, for section headers and counts.
    var countByKind: [InboxKind: Int] {
        Dictionary(grouping: items, by: \.kind).mapValues(\.count)
    }

    func loadInbox() async {
        errorMessage = nil
        await store.refresh([.inbox])
        if store.inbox.value == nil {
            errorMessage = store.toast
        }
    }

    /// Resolve one item. Every action except `skip` removes the card locally
    /// (the file is unlinked server-side). `skip` keeps the item in the queue,
    /// so we reload to reflect any organic changes since last fetch.
    ///
    /// Returns whether the resolve succeeded, so callers (`InboxCardView` via
    /// `InboxListView`) can reset UI state — e.g. the card's `resolving` dim
    /// — on failure instead of leaving it frozen forever.
    @discardableResult
    func resolve(
        id: String,
        action: String,
        answer: String? = nil,
        mergeTarget: String? = nil,
        mergeSurvivor: String? = nil
    ) async -> Bool {
        // Optimistically hide the card for every action except `skip` (which
        // intentionally keeps the item in the queue).
        let hideLocally = action != "skip"
        if hideLocally { locallyResolvedIds.insert(id) }
        do {
            try await APIClient.shared.resolveInboxItem(
                id: id, action: action, answer: answer,
                mergeTarget: mergeTarget, mergeSurvivor: mergeSurvivor
            )
            // The resolve always changes what `/inbox` should return next —
            // whether the item was removed or (on `skip`) organically
            // updated — so re-pull that domain from the Store. Once the new
            // snapshot lands the item is genuinely gone from `store.inbox`,
            // so the local hide can be dropped.
            await store.refresh([.inbox])
            if hideLocally { locallyResolvedIds.remove(id) }
            // Keep the menu-bar badge in lockstep with the resolve.
            await onResolved?()
            return true
        } catch {
            // Rollback: the request never landed, so the card must reappear.
            if hideLocally { locallyResolvedIds.remove(id) }
            errorMessage = error.localizedDescription
            return false
        }
    }
}
