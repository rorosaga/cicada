import Foundation

/// Single ViewModel backing the unified Inbox tab. Replaces the old
/// `NudgeViewModel` + `ClarificationViewModel`. Reads `GET /inbox` and routes
/// every resolution through `POST /inbox/{id}/resolve`, dispatched server-side
/// on the item's `kind`.
@Observable
final class InboxViewModel {
    var items: [InboxItem] = []
    var isLoading = false
    var errorMessage: String?

    /// Wired by the App to `menuBarManager.refreshAfterAction()` so the menu-bar
    /// badge updates the instant an item resolves (mirrors `SleepViewModel`'s
    /// callback hooks). `nil` when no menu bar is attached (previews/tests).
    var onResolved: (() async -> Void)?

    /// Sidebar / menu-bar badge — number of pending items.
    var pendingCount: Int { items.count }

    /// Breakdown by kind, for section headers and counts.
    var countByKind: [InboxKind: Int] {
        Dictionary(grouping: items, by: \.kind).mapValues(\.count)
    }

    func loadInbox() async {
        isLoading = true
        errorMessage = nil
        do {
            items = try await APIClient.shared.fetchInbox()
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
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
        do {
            try await APIClient.shared.resolveInboxItem(
                id: id, action: action, answer: answer,
                mergeTarget: mergeTarget, mergeSurvivor: mergeSurvivor
            )
            if action == "skip" {
                await loadInbox()
            } else {
                items.removeAll { $0.id == id }
            }
            // Keep the menu-bar badge in lockstep with the resolve.
            await onResolved?()
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }
}
