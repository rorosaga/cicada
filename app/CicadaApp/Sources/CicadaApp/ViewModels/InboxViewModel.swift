import Foundation
import Observation

/// Single ViewModel backing the unified Inbox tab. Thin projection over
/// `Store.inbox` (§5.5): `items` reads straight from the snapshot so a tab
/// switch renders whatever the Store already has, instantly. Resolutions go
/// through `Store.perform(InboxResolve)` (§5.4), which hides the card
/// optimistically, sends `POST /inbox/{id}/resolve`, refreshes `.inbox`, and
/// rolls the card back with a toast if the request never landed.
@Observable
@MainActor
final class InboxViewModel {
    private let store: Store

    var errorMessage: String?

    /// Wired by the App to `menuBarManager.refreshAfterAction()` so the menu-bar
    /// badge updates the instant an item resolves (mirrors `SleepViewModel`'s
    /// callback hooks). `nil` when no menu bar is attached (previews/tests).
    var onResolved: (() async -> Void)?

    init(store: Store) {
        self.store = store
    }

    /// Straight projection over the Store, minus anything an optimistic
    /// `InboxResolve` is hiding (`Store.hiddenInboxIds`). The Task-7 stopgap
    /// (`locallyResolvedIds`, dropped unconditionally after the refresh) is
    /// gone: the Store now un-hides an id only once a snapshot without it
    /// arrives, so a 304 racing the server-side delete can't flash the card
    /// back.
    var items: [InboxItem] { store.visibleInbox }

    var isLoading: Bool { store.inbox.isEmpty && store.inbox.isRefreshing }

    /// Sidebar / menu-bar badge — number of pending items.
    var pendingCount: Int { items.count }

    /// Breakdown by kind, for section headers and counts.
    var countByKind: [InboxKind: Int] {
        Dictionary(grouping: items, by: \.kind).mapValues(\.count)
    }

    /// For the honest empty state (G115 R12): what the backend last said, so an
    /// empty inbox can state a fact instead of promising what the bookworm will
    /// do next. Both read the already-hydrated `status` snapshot — nothing here
    /// triggers a fetch of its own.
    var lastSleepAt: String? { store.status.value?.lastSleepAt }
    var unprocessedEpisodes: Int { store.status.value?.episodes.unprocessed ?? 0 }

    func loadInbox() async {
        errorMessage = nil
        await store.refresh([.inbox])
        if store.inbox.value == nil {
            errorMessage = store.toast
        }
    }

    /// Resolve one item, optimistically (§5.4): every action except `skip`
    /// hides the card the instant it is clicked, and a failed request puts it
    /// back at its original position with a toast. `skip` keeps the item in
    /// the queue, so nothing is hidden — the refresh just picks up any
    /// organic change.
    ///
    /// Returns whether the resolve succeeded, so callers (`InboxCardView` via
    /// `InboxListView`) can reset UI state — e.g. the card's `resolving` dim
    /// — on failure instead of leaving it frozen forever.
    @discardableResult
    func resolve(
        id: String,
        action: String,
        answer: String? = nil,
        optionKey: String? = nil,
        remindDays: Int? = nil,
        mergeTarget: String? = nil,
        mergeSurvivor: String? = nil
    ) async -> Bool {
        errorMessage = nil
        let ok = await store.perform(InboxResolve(
            id: id, action: action, answer: answer,
            optionKey: optionKey, remindDays: remindDays,
            mergeTarget: mergeTarget, mergeSurvivor: mergeSurvivor
        ))
        if ok {
            // Keep the menu-bar badge in lockstep with the resolve.
            await onResolved?()
        } else {
            errorMessage = store.toast
        }
        return ok
    }
}
