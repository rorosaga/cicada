import SwiftUI

/// The Inbox in progressive columns (DESIGN_RULES §5.3, the owner's Direction D). With nothing open
/// it is the questions alone at full width; a click narrows them to the triage column and opens the
/// question beside them; "Show in conversation" opens the Reader as the third column. One tap
/// answers, and an Undo row holds the answer for 5 s before anything is sent (DR-42, R-DI2).
///
/// It replaced `InboxListView` — one list of cards that each expanded in place, kind chips, and an
/// in-page search field that R-DI14 retires (⌘K's Inbox group is its twin). The order of the page
/// states matters: error first, because a failed `GET /inbox` leaves `items` empty and would
/// otherwise read as the happy state; loading second, because an empty snapshot mid-first-fetch is
/// not "nothing pending".
struct InboxPage: View {
    @Environment(InboxViewModel.self) private var viewModel
    @Environment(AppRouter.self) private var router
    @Environment(ProvenanceRouter.self) private var provenance
    @Environment(Store.self) private var store
    @AppStorage(ShellMetrics.labelledKey) private var labelledSidebar = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    enum Focus: Hashable { case list, question, reader }
    @FocusState private var focus: Focus?
    /// R-DI4 — a field in the card has focus, so ⌘Z is the field's.
    @State private var editingText = false
    @State private var landingToken = 0
    /// R-DL4 — the column plan's DR-27 answer, mirrored out of the header builder so the focus policy can read it.
    @State private var listHidden = false
    /// Owner ruling 2026-10-16 — "Settled by a check", in memory (not a Store domain).
    @State private var settled = SettledChecks()

    var body: some View {
        Group {
            if viewModel.review != nil {
                InboxReviewView(onEnd: { endReview() }, onOpenInInbox: { openInInbox($0) })
            } else if let err = viewModel.errorMessage, viewModel.items.isEmpty, viewModel.held == nil {
                errorState(err)
            } else if viewModel.isLoading {
                loadingState
            } else if viewModel.items.isEmpty && viewModel.held == nil && !provenance.isPresented {
                emptyState
            } else {
                columns
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(CicadaTheme.bgBase)
        .onAppear { consumeLanding(); viewModel.reconcile(); viewModel.reconcileReview() }
        .onChange(of: router.pendingInboxItem) { _, _ in consumeLanding() }
        // Say it once — Inbox clicked again in the rail: All, nothing open, no review.
        .onRailReselect(.inbox, router: router) { popToRoot() }
        .onChange(of: viewModel.items.map(\.id)) { _, _ in
            viewModel.reconcile()
            viewModel.reconcileReview()
            Task { await settled.load() }   // a run may have settled some; an undo brought one back
        }
        // Per memory: a switch reloads it even when the two memories' question ids happen to match (`inbox-001`…).
        .task(id: store.bank) { await settled.load() }
    }

    private var settledSection: some View {
        SettledChecksSection(model: settled) { await viewModel.loadInbox() }
    }

    private var columns: some View {
        ProgressiveColumns(hasDetail: viewModel.openItem != nil, hasTrailing: provenance.isPresented,
                           navWidth: ShellMetrics.navWidth(labelled: labelledSidebar)) { plan in
            EyebrowRow(eyebrow: viewModel.eyebrow,
                       horizontalPadding: viewModel.openItem == nil && !provenance.isPresented
                           ? plan.gutter : CicadaTheme.spacingXL,
                       adaptiveTrailing: true) {
                // Owner 2026-10-16: when the kinds do not fit (1200 pt with the Reader open, 1100), All and the
                // selected kind stay and the rest go under More — never a truncated label.
                OverflowTextTabs(tabs: viewModel.tabs, selection: Binding(
                    get: { viewModel.columns.kindFilter },
                    set: { viewModel.setFilter($0) }), moreAccessibilityLabel: Copy.Inbox.moreKinds)
            }
            .onChange(of: plan.listHidden, initial: true) { _, hidden in listHidden = hidden }
        } list: { plan in
            InboxQuestionList(entries: viewModel.rows, style: plan.listStyle, width: plan.list,
                              openId: viewModel.columns.openId,
                              undoShortcut: !editingText, landingToken: landingToken,
                              open: { open($0) }, undo: { undo() }, move: { move($0) },
                              focusQuestion: { focus = .question }, escape: { escape() },
                              footer: AnyView(settledSection),
                              header: AnyView(VStack(alignment: .leading, spacing: 0) {
                                  // G205 / G61 — agents asking, then the grouped Where-to-check review, above the
                                  // questions.
                                  InboxTopCards(requests: viewModel.agentRequests,
                                                reviews: viewModel.whereToCheckReviews,
                                                answer: { item, resolution in viewModel.answer(item, resolution) },
                                                openPage: { router.routeToClustersEntity($0) })
                                  // Say it once: under All each kind's group carries its own review.
                                  if viewModel.columns.kindFilter != nil {
                                      InboxReviewEntriesRow(entries: viewModel.reviewEntries
                                          .filter { $0.kind.inboxKind == viewModel.columns.kindFilter }) {
                                          startReview($0)
                                      }
                                  }
                              }),
                              lines: viewModel.lines,
                              toggleGroup: { viewModel.toggleGroup($0) },
                              startReview: { startReview($0) })
                .focused($focus, equals: .list)
                .tourAnchor(.inbox)
        } detail: { plan in
            if let item = viewModel.openItem {
                ScrollView {
                    VStack(spacing: CicadaTheme.spacingMD) {
                        // R-DI25 — the list is hidden, so its Undo row (and ⌘Z) moves here.
                        if plan.listHidden, let held = viewModel.held, let question = viewModel.heldQuestion {
                            InboxUndoRow(held: held, item: question, style: .titles,
                                         shortcutEnabled: !editingText) { undo() }
                        }
                        InboxFocusCard(item: item, padding: plan.cardPadding,
                                       onClose: { closeQuestion() },
                                       hiddenListCount: plan.listHidden ? viewModel.visible.count : nil,
                                       onShowList: { showList() },
                                       onEscape: { escape() },
                                       onEditingChange: { editingText = $0 }) { resolution in
                            // DR-29 / DR-61 — the swap after an answer is instant for pointer and key alike;
                            // a Reader that closes because the next question cites another conversation
                            // closes with it, never on the drawer curve (DR-60 for 1–9 and ⏎).
                            Instant.run { viewModel.answerAndFollow(item, resolution, reader: provenance) }
                            // R-DL4 — after an answer the list takes the keys (Undo holds one answer).
                            DispatchQueue.main.async {
                                focus = InboxFocusPolicy.afterArrivalOrAnswer(listHidden: listHidden,
                                                                               questionOpen: viewModel.openItem != nil)
                            }
                        }
                        .id(item.id)
                        .focused($focus, equals: .question)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.horizontal, plan.gutter)
                    .padding(.bottom, CicadaTheme.scaled(72))
                }
            }
        } trailing: { _ in
            ReaderColumn().focused($focus, equals: .reader)
        }
        .onAppear { arrive() }
    }

    /// R-DL4 — the keys land where the policy says, one turn later: a `FocusState` write in the same update that
    /// inserts the focusable view is dropped by SwiftUI on macOS (the arrival case), and after an answer the card that
    /// held focus has just been replaced by the next one (keyed by its id).
    private func arrive() {
        DispatchQueue.main.async {
            focus = InboxFocusPolicy.afterArrivalOrAnswer(listHidden: listHidden, questionOpen: viewModel.openItem != nil)
        }
    }

    // MARK: - The quick review (owner 2026-10-19) — a pointer starts it, Esc ends it; neither animates (DR-60/61)

    private func startReview(_ kind: ReviewKind) {
        Instant.run {
            provenance.close()
            viewModel.startReview(kind)
        }
    }

    private func endReview() {
        viewModel.endReview()
        arrive()
    }

    /// The full card for one question: the review ends and the Inbox opens that question (DR-30's landing).
    private func openInInbox(_ item: InboxItem) {
        Instant.run {
            viewModel.endReview()
            viewModel.columns.land(item.id)
            landingToken &+= 1
        }
        DispatchQueue.main.async { focus = .question }
    }

    /// The root is the whole list under All: a review ends, the Reader and the open question close. A half-typed
    /// answer keeps its question (or its review) where it is — only the Reader closes — so a click never drops it.
    private func popToRoot() {
        router.popToRoot(reduceMotion: reduceMotion) {
            provenance.close()
            guard !viewModel.hasDraft else { return }
            if viewModel.review != nil { viewModel.endReview() }
            viewModel.columns.close()
            viewModel.setFilter(nil)
        }
        if !viewModel.hasDraft { arrive() }
    }

    // MARK: - Paths (R-DI10: a pointer path may animate, a keyboard path never does — DR-60)

    /// A closed router keeps its stack (`ProvenanceRouter.close()` only flips `isPresented`), so
    /// `current` alone is not "the Reader is showing".
    private var readerEpisode: String? { provenance.isPresented ? provenance.current?.episode : nil }

    private func apply(_ effect: InboxColumns.ReaderEffect) {
        switch effect {
        case .keep: break
        case .close: provenance.close()
        case .refocus(let target): provenance.refocus(target)
        }
    }

    /// The pointer path: STATE 0 → 1 narrows the list on the drawer curve; a swap in place is
    /// instant (DR-61). Either way the question takes focus, so 1–9 answer at once (R-DI10).
    private func open(_ item: InboxItem) {
        let select = { apply(viewModel.columns.select(item, in: viewModel.visible, readerEpisode: readerEpisode)) }
        if viewModel.openItem == nil {
            withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) { select() }
        } else {
            Instant.run { select() }
        }
        focus = .question
    }

    /// DR-68 — ↑/↓ on the list. Focus stays on the list.
    private func move(_ delta: Int) {
        Instant.run {
            guard let next = viewModel.columns.neighbour(delta, in: viewModel.visible) else { return }
            apply(viewModel.columns.select(next, in: viewModel.visible, readerEpisode: readerEpisode))
        }
    }

    /// ⌘Z is a key, and a click reopens in place, which DR-61 makes instant too.
    private func undo() {
        Instant.run {
            guard let item = viewModel.undo() else { return }
            apply(InboxColumns.readerEffect(for: item, readerEpisode: readerEpisode))
            focus = .question
        }
    }

    /// DR-28 — Esc closes the rightmost open thing (the card has already closed its own field).
    private func escape() {
        Instant.run {
            switch viewModel.columns.escape(readerOpen: provenance.isPresented) {
            case .closeReader: provenance.close()
            case .closeQuestion:
                viewModel.columns.close()
                focus = .list
            case .none: break
            }
        }
    }

    /// The card's × — a pointer path, so the columns close on the drawer curve.
    private func closeQuestion() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            provenance.close()
            viewModel.columns.close()
        }
        focus = .list
    }

    /// DR-27 — "‹ N questions": the list comes back by closing the Reader when one is open, else the
    /// question — the same order as Esc, animated because it is a pointer path.
    private func showList() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            if provenance.isPresented {
                provenance.close()
            } else {
                viewModel.columns.close()
            }
        }
    }

    /// G136 / DR-30 — a ⌘K or Home hand-off: every kind shown, that question open, its row scrolled
    /// into view. Not a pointer path on this page, so it never animates.
    private func consumeLanding() {
        Instant.run {
            guard let id = router.consumeInboxItem() else { return }
            viewModel.columns.land(id)
            apply(InboxColumns.readerEffect(for: viewModel.openItem, readerEpisode: readerEpisode))
            landingToken &+= 1
        }
    }

    // MARK: - Page states (DR-43, DR-50)

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 0) {
            EyebrowRow(eyebrow: viewModel.eyebrow)
            // G117 — "Nothing pending" is a GOOD state, not a deficiency to fix, so it carries no
            // action; `emptyStateDetail` is the R12-honest "what Sleep actually did".
            EmptyStateView(systemImage: "tray", title: Copy.Inbox.nothingPending, message: emptyStateDetail)
            settledSection
                .padding(.horizontal, CicadaTheme.spacingGutter)
        }
    }

    /// R12: say what is true, not what the bookworm will do. Sleep asks questions; if it has not
    /// run, nothing has been asked yet. The old copy ("the bookworm will surface new items after
    /// the next Sleep cycle") promised a future that a disabled schedule or a failed cycle never
    /// delivers.
    private var emptyStateDetail: String {
        var lines: [String] = []
        if let last = viewModel.lastSleepAt,
           let days = InboxAge.days(since: last, now: .now) {
            lines.append(Copy.Inbox.lastSleep(InboxAge.phrase(days: days)))
        } else {
            lines.append(Copy.Inbox.sleepNotRun)
        }
        let queued = viewModel.unprocessedEpisodes
        if queued > 0 { lines.append(Copy.Inbox.waiting(queued)) }
        return lines.joined(separator: "\n")
    }

    /// DR-43 — the list pages' one first-read state (`ListSkeleton`): the sentence over still bars, no shimmer.
    private var loadingState: some View {
        VStack(alignment: .leading, spacing: 0) {
            EyebrowRow(eyebrow: Copy.Inbox.title)
            ListSkeleton(message: Copy.Inbox.checking)
                .padding(.horizontal, CicadaTheme.scaled(30))
            Spacer(minLength: 0)
        }
    }

    /// DR-40 / DR-43 — the list pages' one failed-first-read card (`ListErrorCard`): Retry is neutral, the Inbox has
    /// no primary action.
    private func errorState(_ message: String) -> some View {
        ListErrorCard(title: Copy.Inbox.loadFailed, message: message) { Task { await viewModel.loadInbox() } }
            .frame(maxHeight: .infinity, alignment: .top)
    }
}
