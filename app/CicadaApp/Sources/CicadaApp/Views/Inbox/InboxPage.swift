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
    @AppStorage(ShellMetrics.labelledKey) private var labelledSidebar = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    enum Focus: Hashable { case list, question, reader }
    @FocusState private var focus: Focus?
    /// R-DI4 — a field in the card has focus, so ⌘Z is the field's.
    @State private var editingText = false
    @State private var landingToken = 0

    var body: some View {
        Group {
            if let err = viewModel.errorMessage, viewModel.items.isEmpty, viewModel.held == nil {
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
        .onAppear { consumeLanding(); viewModel.reconcile() }
        .onChange(of: router.pendingInboxItem) { _, _ in consumeLanding() }
        .onChange(of: viewModel.items.map(\.id)) { _, _ in viewModel.reconcile() }
    }

    private var columns: some View {
        ProgressiveColumns(hasDetail: viewModel.openItem != nil, hasTrailing: provenance.isPresented,
                           navWidth: ShellMetrics.navWidth(labelled: labelledSidebar)) { plan in
            EyebrowRow(eyebrow: viewModel.eyebrow,
                       horizontalPadding: viewModel.openItem == nil && !provenance.isPresented
                           ? plan.gutter : CicadaTheme.spacingXL) {
                TextTabs(tabs: viewModel.tabs, selection: Binding(
                    get: { viewModel.columns.kindFilter },
                    set: { viewModel.setFilter($0) }))
            }
        } list: { plan in
            InboxQuestionList(entries: viewModel.rows, style: plan.listStyle, width: plan.list,
                              openId: viewModel.columns.openId,
                              undoShortcut: !editingText, landingToken: landingToken,
                              open: { open($0) }, undo: { undo() }, move: { move($0) },
                              focusQuestion: { focus = .question }, escape: { escape() })
                .focused($focus, equals: .list)
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
            EmptyStateView(title: Copy.Inbox.nothingPending, message: emptyStateDetail)
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

    /// Six skeleton bars, no shimmer (DR-43): a first fetch is short, and motion here would only
    /// say "busy" louder than the sentence does.
    private static let skeleton: [CGFloat] = [0.62, 0.48, 0.71, 0.39, 0.55, 0.66]

    private var loadingState: some View {
        VStack(alignment: .leading, spacing: 0) {
            EyebrowRow(eyebrow: Copy.Inbox.title)
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(24)) {
                Text(Copy.Inbox.checking)
                    .font(CicadaTheme.detailBodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                ForEach(Array(Self.skeleton.enumerated()), id: \.offset) { _, fraction in
                    CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
                        .fill(CicadaTheme.bgSelected)
                        .frame(width: CicadaTheme.scaled(520 * fraction), height: CicadaTheme.scaled(12))
                }
            }
            .padding(.horizontal, CicadaTheme.spacingGutter)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(Copy.Inbox.checking)
            Spacer(minLength: 0)
        }
    }

    /// DR-40 — the Inbox has no primary action, so Retry is neutral: the old `.borderedProminent`
    /// and its accent tint went with it.
    private func errorState(_ message: String) -> some View {
        VStack(spacing: CicadaTheme.spacingMD) {
            Text(Copy.Inbox.loadFailed)
                .font(CicadaTheme.headingFont)
                .foregroundStyle(CicadaTheme.textPrimary)
            Text(message)
                .font(CicadaTheme.detailBodyFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
            NeutralButton(title: Copy.Inbox.retry) { Task { await viewModel.loadInbox() } }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(maxWidth: CicadaTheme.scaled(420))
        .background(CicadaTheme.shape(CicadaTheme.radiusLarge).fill(CicadaTheme.bgFocus))
        .ringed(in: CicadaTheme.shape(CicadaTheme.radiusLarge))
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
