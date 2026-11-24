import SwiftUI

/// Who asked this question and when, in one quiet line (owner 2026-11-24, DESIGN_RULES §9; DR-38, DR-54, DR-58):
/// "Asked 13 days ago by Sleep's duplicate check". Secondary text in the card's header row, so it adds no height and
/// never moves an answer: it truncates before it pushes, and the page's name beside it yields first (the question already names the page), and the hover carries the whole of it
/// and what kind of asker it was. It names no provider and no model (`InboxAskedLine`); nothing is drawn when the day
/// is unknown. One component for every place the card is drawn: the Inbox's focus card, the quick review, a page's
/// questions strip; Home's lead question says the same words in its hover (`HomeQuestions.Row.asked`).
struct AskedByLine: View {
    let item: InboxItem

    var body: some View {
        if let text = InboxAskedLine.text(item) {
            Text(text)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
                .truncationMode(.tail)
                .help(InboxAskedLine.help(item) ?? text)
                .accessibilityLabel(text)
        }
    }
}
