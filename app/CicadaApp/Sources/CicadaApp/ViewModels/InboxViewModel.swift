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

    /// R-DI19 — the page's selection, kept across page switches, reset by a bank switch.
    var columns = InboxColumns()

    var visible: [InboxItem] { InboxColumns.visible(items, filter: columns.kindFilter) }
    var openItem: InboxItem? { columns.openId.flatMap { id in items.first { $0.id == id } } }
    var held: ResolveGrace? { store.currentHeld }
    /// The held answer's question, from the snapshot (`visibleInbox` hides it) — the Undo row's words.
    var heldQuestion: InboxItem? { held.flatMap { h in store.inbox.value?.first { $0.id == h.id } } }
    var rows: [InboxRowEntry] {
        InboxRows.entries(visible: visible, held: held, snapshot: store.inbox.value ?? [], filter: columns.kindFilter)
    }
    var eyebrow: String { InboxEyebrow.text(visible: visible, openId: columns.openId) }
    /// DR-45 — the tabs replace the kind chips and their `countByKind`, their one reader.
    var tabs: [TextTab<InboxKind>] { InboxTabs.tabs(items) }

    func setFilter(_ kind: InboxKind?) {
        columns.filter(kind, visibleAfter: InboxColumns.visible(items, filter: kind))
    }
    func reconcile() { columns.reconcile(visible: visible, kinds: Set(items.map(\.kind))) }
    func resetColumns() { columns = InboxColumns() }

    /// R-DI16 — the Sources page's own Undo row: a held removal for that browser channel, with its
    /// question (still in the snapshot; only `visibleInbox` hides it).
    func heldRemoval(channel: String?) -> (held: ResolveGrace, item: InboxItem)? {
        guard let held, held.kind == .removal, held.channel == channel,
              let item = store.inbox.value?.first(where: { $0.id == held.id }) else { return nil }
        return (held, item)
    }

    /// DR-29 — answer, then the Reader follows the next question: it stays only for the same
    /// conversation (R-DI9), and closes after the last answer. The router is passed in because it is
    /// an environment value, not the model's; the Sources page calls plain `answer`.
    func answerAndFollow(_ item: InboxItem, _ resolution: QuestionResolution, reader: ProvenanceRouter) {
        answer(item, resolution)
        let episode = reader.isPresented ? reader.current?.episode : nil
        switch InboxColumns.readerEffect(for: openItem, readerEpisode: episode) {
        case .keep: break
        case .close: reader.close()
        case .refocus(let target): reader.refocus(target)
        }
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
        let words = UndoLabel.of(resolution, item: item, names: store.entityNames)
        store.hold(InboxResolve(id: item.id, action: resolution.action, answer: resolution.answer,
                                optionKey: resolution.optionKey, remindDays: resolution.remindDays,
                                mergeTarget: resolution.mergeTarget, mergeSurvivor: resolution.mergeSurvivor),
                   label: words.full, shortLabel: words.short, question: item.questionText,
                   kind: item.kind, channel: item.channel)
        // DR-29 — the next row opens at once (`visible` already leaves the held one out).
        columns.afterAnswer(item.id, remaining: visible)
    }

    /// DR-42 — Undo: the held answer is dropped unsent. Returns the question so the page can reopen
    /// it; `reopen: false` is the Sources page's, which has no columns (R-DI16) — its Undo must not
    /// move the Inbox's open question.
    @discardableResult
    func undo(reopen: Bool = true) -> InboxItem? {
        guard let id = store.undoHeld(), let item = store.inbox.value?.first(where: { $0.id == id }) else { return nil }
        if reopen { columns.undo(item) }
        return item
    }
}
