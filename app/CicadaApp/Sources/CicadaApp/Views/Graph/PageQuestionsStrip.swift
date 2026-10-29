import SwiftUI

/// Ruling 48 (1), (2) — a page's own questions strip (owner 2026-10-28: the questions live on Home and on each page).
/// At most one question shows, "1 of N", with the arrows to step through the rest: the question in plain words, its
/// reason, and its one-tap answers — the inbox's own resolutions, held for the same Undo window (DR-42,
/// `InboxViewModel.answer`). *Open in the list* opens the full card for what a tap cannot say. Nothing shows when the
/// page has no open question. Drawn from the Store's snapshot: the page never waits on `GET /inbox`.
struct PageQuestionsStrip: View {
    let entityId: String

    @Environment(Store.self) private var store
    @Environment(InboxViewModel.self) private var inboxVM: InboxViewModel?
    @Environment(AppRouter.self) private var router: AppRouter?
    @State private var index = 0

    var body: some View {
        let questions = HomeQuestions.onPage(store.visibleInbox, entityId: entityId)
        if !questions.isEmpty {
            let i = min(index, questions.count - 1)
            let item = questions[i]
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                HStack(spacing: CicadaTheme.spacingXS) {
                    SectionLabel(Copy.Catchup.stripTitle(i + 1, of: questions.count))
                    Spacer(minLength: CicadaTheme.spacingSM)
                    if questions.count > 1 {
                        IconButton(systemName: "chevron.left", help: Copy.Catchup.previous) {
                            index = (i - 1 + questions.count) % questions.count
                        }
                        IconButton(systemName: "chevron.right", help: Copy.Catchup.next) {
                            index = (i + 1) % questions.count
                        }
                    }
                }
                Text(item.askText)
                    .font(CicadaTheme.detailBodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                if let reason = item.askReason, !reason.isEmpty {
                    Text(reason)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                FlowLayout(spacing: CicadaTheme.spacingSM) {
                    ForEach(CatchupAnswers.chips(item, open: store.visibleInbox).filter { $0.role != .skip }) { chip in
                        switch chip.role {
                        case .answer:
                            NeutralButton(title: chip.label, size: .compact) { answer(item, chip) }
                        case .notNow, .skip:
                            TextButton(title: chip.label) { answer(item, chip) }
                        }
                    }
                    TextButton(title: Copy.Catchup.openFull) { openInList(item.id) }
                }
            }
            .padding(CicadaTheme.spacingMD)
            .frame(maxWidth: .infinity, alignment: .leading)
            .glassCard()
        }
    }

    private func answer(_ item: InboxItem, _ chip: CatchupChip) {
        guard let resolution = chip.resolution else { return }
        // A chain's chip answers its own pair.
        let target = chip.itemId.flatMap { id in store.visibleInbox.first { $0.id == id } } ?? item
        inboxVM?.answer(target, resolution)
    }

    private func openInList(_ id: String) {
        router?.pendingInboxItem = id
        router?.pendingTab = .inbox
    }
}
