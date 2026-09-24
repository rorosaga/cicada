import Foundation
import Observation

/// Single ViewModel backing the unified Inbox tab. Thin projection over
/// `Store.inbox` (§5.5): `items` reads straight from the snapshot so a tab
/// switch renders whatever the Store already has, instantly. An answer is
/// HELD for its Undo window (DR-42, `Store.hold`): the question leaves every
/// list on the tap, and only when the window closes does the ordinary
/// `Store.perform(InboxResolve)` (§5.4) send `POST /inbox/{id}/resolve`,
/// refresh `.inbox`, and roll the card back with a toast if it never landed.
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
        // The menu-bar badge follows the SEND, not the tap: the POST is what changes the server's count.
        store.onHeldResolveSent = { [weak self] in await self?.onResolved?() }
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

    /// DR-42 — the one tap. The answer is held (`Store.hold`) and its question leaves every list at
    /// once; the POST waits for the Undo window (R-DI2). Nothing to await: there is no request yet.
    func answer(_ item: InboxItem, _ resolution: QuestionResolution) {
        let words = UndoLabel.of(resolution, item: item)
        store.hold(InboxResolve(id: item.id, action: resolution.action, answer: resolution.answer,
                                optionKey: resolution.optionKey, remindDays: resolution.remindDays,
                                mergeTarget: resolution.mergeTarget, mergeSurvivor: resolution.mergeSurvivor),
                   label: words.full, shortLabel: words.short, question: item.questionText,
                   kind: item.kind, channel: item.channel)
    }

    /// DR-42 — Undo: the held answer is dropped unsent. Returns the question so the page can reopen
    /// it; `reopen: false` is the Sources page's, which has no columns (R-DI16). The flag is carried
    /// now so the columns (Task 5) need no signature change.
    @discardableResult
    func undo(reopen: Bool = true) -> InboxItem? {
        guard let id = store.undoHeld() else { return nil }
        return store.inbox.value?.first { $0.id == id }
    }
}
