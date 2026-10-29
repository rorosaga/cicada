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

    /// Say it once (review of #363) — the questions with a half-typed answer in one of their fields (Other…, a free
    /// answer, a name, the review's field). Inbox clicked again in the rail never closes a question or ends a review
    /// while one holds a draft: the person's words are not thrown away by a navigation click.
    private(set) var drafts: Set<String> = []
    var hasDraft: Bool { !drafts.isEmpty }

    /// A field reports its text; empty (or only whitespace) clears the question's draft.
    func noteDraft(_ id: String, _ text: String) {
        if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            if drafts.contains(id) { drafts.remove(id) }
        } else if !drafts.contains(id) {
            drafts.insert(id)
        }
    }

    /// G205 / G61 — agent requests and the grouped Where-to-check review are small cards above the questions; the
    /// list, its tabs and its walk read the questions only.
    var questions: [InboxItem] { derived.questions }
    var agentRequests: [InboxItem] { derived.agentRequests }
    var whereToCheckReviews: [InboxItem] { derived.whereToCheckReviews }

    /// The questions in the order the list draws them (owner 2026-10-26): grouped by kind under All, by page inside
    /// (`InboxGroups`), so ↑/↓ and the next question after an answer follow the screen.
    var visible: [InboxItem] { derived.visible }

    // MARK: - Built once per change (inbox freeze, owner 2026-10-29)

    /// Everything the page derives from the inbox and its tab, built once per change to either. The page's body, the
    /// list, the tabs, the keys and the focus policy each read these several times per draw; rebuilt on every read
    /// they cost ~2.4 s of main thread on the click that opened 465 questions (debug build, `InboxAllListBenchTests`).
    /// Reading `items` first keeps every view that asks observing the Store's inputs.
    struct Derived {
        let questions: [InboxItem]
        let agentRequests: [InboxItem]
        let whereToCheckReviews: [InboxItem]
        let visible: [InboxItem]
        let sections: [InboxGroups.Section]
        let tabs: [TextTab<InboxKind>]
        let reviewEntries: [ReviewEntries.Entry]
        let byId: [String: InboxItem]
        let kinds: Set<InboxKind>
    }

    private struct DerivedKey: Equatable {
        let revision: Int
        let filter: InboxKind?
    }

    private struct LinesKey: Equatable {
        let derived: DerivedKey
        let groupChoices: [InboxKind: Bool]
        let openKind: InboxKind?
    }

    @ObservationIgnored private var derivedMemo: (key: DerivedKey, value: Derived)?
    @ObservationIgnored private var linesMemo: (key: LinesKey, value: [InboxListLine])?
    @ObservationIgnored private var rowsMemo: (key: DerivedKey, value: [InboxRowEntry])?

    private var derivedKey: DerivedKey { DerivedKey(revision: store.inboxRevision, filter: columns.kindFilter) }

    var derived: Derived {
        let items = items
        let key = derivedKey
        if let memo = derivedMemo, memo.key == key { return memo.value }
        let questions = items.filter { !$0.isTopCard }
        let sections = InboxGroups.sections(InboxColumns.visible(questions, filter: key.filter),
                                            byKind: key.filter == nil)
        let value = Derived(
            questions: questions,
            agentRequests: items.filter { $0.kind == .agentRequest },
            whereToCheckReviews: items.filter(\.isWhereToCheckReview),
            visible: sections.flatMap(\.items),
            sections: sections,
            tabs: InboxTabs.tabs(questions),
            reviewEntries: ReviewEntries.of(questions),
            byId: Dictionary(questions.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first }),
            kinds: Set(questions.map(\.kind)))
        derivedMemo = (key, value)
        return value
    }

    private static func ordered(_ questions: [InboxItem], filter: InboxKind?) -> [InboxItem] {
        InboxGroups.ordered(InboxColumns.visible(questions, filter: filter), byKind: filter == nil)
    }

    /// The person's own open/closed choice per kind's group, for this memory (a bank switch forgets it).
    private(set) var groupChoices: [InboxKind: Bool] = [:]

    var sections: [InboxGroups.Section] { derived.sections }

    func isGroupOpen(_ kind: InboxKind?, in sections: [InboxGroups.Section]) -> Bool {
        InboxGroups.isOpen(kind, sections: sections, chosen: groupChoices, openKind: openItem?.kind)
    }

    /// A kind's header was clicked: open or close its group. Nothing is answered.
    func toggleGroup(_ kind: InboxKind) {
        let sections = sections
        groupChoices[kind] = !isGroupOpen(kind, in: sections)
    }

    /// The held answer's question, when the list on screen would show it (a kind's tab hides another kind's).
    private var heldInList: InboxItem? {
        guard let item = heldQuestion, columns.kindFilter == nil || columns.kindFilter == item.kind else { return nil }
        return item
    }

    /// The full-width list's lines: kind headers with counts and their quick review, page headers, questions.
    var lines: [InboxListLine] {
        let derived = derived
        let key = LinesKey(derived: derivedKey, groupChoices: groupChoices, openKind: openItem?.kind)
        if let memo = linesMemo, memo.key == key { return memo.value }
        let sections = derived.sections
        let value = InboxListLine.lines(sections, byKind: key.derived.filter == nil, held: held, heldItem: heldInList,
                                        reviews: derived.reviewEntries) {
            isGroupOpen($0, in: sections)
        }
        linesMemo = (key, value)
        return value
    }
    var openItem: InboxItem? { columns.openId.flatMap { derived.byId[$0] } }
    var held: ResolveGrace? { store.currentHeld }
    /// The held answer's question, from the snapshot (`visibleInbox` hides it) — the Undo row's words.
    var heldQuestion: InboxItem? { held.flatMap { h in store.inbox.value?.first { $0.id == h.id } } }
    /// Every question as one flat list in the groups' order (the narrow columns beside an open question), with the
    /// held answer's Undo row in its question's place.
    var rows: [InboxRowEntry] {
        let derived = derived
        let key = derivedKey
        if let memo = rowsMemo, memo.key == key { return memo.value }
        let value = InboxListLine.lines(derived.sections, byKind: key.filter == nil, held: held, heldItem: heldInList,
                                        reviews: []) { _ in true }
            .compactMap { if case .entry(let entry, _) = $0 { return entry } else { return nil } }
        rowsMemo = (key, value)
        return value
    }
    var eyebrow: String { InboxEyebrow.text(visible: visible, openId: columns.openId) }
    /// DR-45 — the tabs replace the kind chips and their `countByKind`, their one reader.
    var tabs: [TextTab<InboxKind>] { derived.tabs }

    func setFilter(_ kind: InboxKind?) {
        columns.filter(kind, visibleAfter: Self.ordered(questions, filter: kind))
    }
    func reconcile() {
        let derived = derived
        columns.reconcile(visible: derived.visible, kinds: derived.kinds)
    }
    func resetColumns() {
        columns = InboxColumns()
        groupChoices = [:]
        review = nil   // ids repeat across banks: a review never crosses a switch
    }

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
    @discardableResult
    func answer(_ item: InboxItem, _ resolution: QuestionResolution) -> Bool {
        let words = UndoLabel.of(resolution, item: item, names: store.entityNames)
        let held = store.hold(InboxResolve(id: item.id, action: resolution.action, answer: resolution.answer,
                                optionKey: resolution.optionKey, remindDays: resolution.remindDays,
                                mergeTarget: resolution.mergeTarget, mergeSurvivor: resolution.mergeSurvivor,
                                quote: resolution.quote, relayedBy: resolution.quote == nil ? nil : CatchupAnswers.relayedBy,
                                sessionId: resolution.sessionId),
                   label: words.full, shortLabel: words.short, question: item.questionText,
                   kind: item.kind, channel: item.channel)
        guard held else { return false }   // a bank switch is in flight: the question stays open (G183(d))
        // DR-29 — the next row opens at once (`visible` already leaves the held one out).
        columns.afterAnswer(item.id, remaining: visible)
        return true
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

    // MARK: - The quick review (owner 2026-10-19)

    /// One kind at a time, one card at a time. `nil` is the Inbox as it always was. Held here, not in the page, so a
    /// page switch keeps the place; a bank switch ends it (`resetColumns`).
    var review: InboxReview?

    /// The entry points: "Fading pages · 49", one per kind with something to review.
    var reviewEntries: [ReviewEntries.Entry] { derived.reviewEntries }

    /// The card on screen. `items` already hides a held answer, so the current card is never the one just answered.
    var reviewItem: InboxItem? { review?.currentId.flatMap { id in items.first { $0.id == id } } }

    func startReview(_ kind: ReviewKind) {
        review = InboxReview(kind: kind, items: questions)
    }

    func endReview() { review = nil }

    /// The card's answer, through the Inbox's own hold (`answer` → `Store.hold`): the same resolver, the same Undo
    /// window, the same send. Recorded only when the Store took it (a bank switch refuses it and the card stays).
    ///
    /// `itemId` is the card the key or the button was drawn for: an answer for any other card is ignored (review B1 —
    /// the card on screen can change between the draw and the press, and an option's key is valid on both cards).
    @discardableResult
    func reviewAnswer(itemId: String, _ resolution: QuestionResolution) -> Bool {
        guard let item = reviewItem, item.id == itemId, answer(item, resolution) else { return false }
        review?.record(.answered(item.id))
        return true
    }

    /// Skip writes nothing: the question stays in the Inbox, and the review moves on. Only the card drawn.
    func reviewSkip(itemId: String) {
        guard let id = review?.currentId, id == itemId else { return }
        review?.record(.skipped(id))
    }

    var canUndoReview: Bool { review?.undoable(heldId: held?.id) != nil }

    /// ⌘Z — the last skip, or the last answer while it is still held (the Inbox's Undo window): that card is on
    /// screen again and nothing was sent.
    func reviewUndo() {
        guard let step = review?.undoable(heldId: held?.id) else { return }
        if case .answered = step { undo(reopen: false) }
        review?.undo(heldId: step.id)
    }

    /// What the review's undo line says: the held answer's words, or "Skipped".
    var reviewLastStep: String? {
        guard let step = review?.undoable(heldId: held?.id) else { return nil }
        switch step {
        case .answered: return held?.label
        case .skipped: return Copy.Inbox.skipped
        }
    }

    /// The Inbox moved under the review (a refresh, a rollback, Sleep settled one).
    func reconcileReview() {
        review?.reconcile(visible: Set(items.map(\.id)))
    }
}
