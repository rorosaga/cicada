import SwiftUI

/// Who asked this question and when, in one quiet line (owner 2026-11-24, DESIGN_RULES §9; DR-38, DR-54, DR-58):
/// "Asked 13 days ago by Sleep's duplicate check". Secondary text in the card's header row, so it adds no height and
/// never moves an answer: it truncates before it pushes, and the page's name beside it yields first (the question already names the page), and the hover carries the whole of it
/// and what kind of asker it was. It names no provider and no model (`InboxAskedLine`); nothing is drawn when the day
/// is unknown. One component for every place a question is answered: the Inbox's focus card, the quick review, a page's
/// questions strip, the catch-up chat's bubble (`wraps`: a line of its own that never truncates) and Home's lead
/// question (`AskedByText`, from the words its row already carries; owner 2026-11-25, "I dont see the asked by even by
/// hovering": a hover alone was no line at all).
struct AskedByLine: View {
    let item: InboxItem
    /// A line of its own (the chat's bubble, Home's lead) wraps rather than truncates; in a header row it truncates.
    var wraps = false

    var body: some View {
        if let text = InboxAskedLine.text(item) {
            AskedByText(text: text, help: InboxAskedLine.help(item), wraps: wraps)
        }
    }
}

/// The line's one look: secondary text at the meta size, the hover carrying what the line leaves out, the same words
/// as its accessibility label. No animation (DR-60).
struct AskedByText: View {
    let text: String
    var help: String? = nil
    var wraps = false

    var body: some View {
        Text(text)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .lineLimit(wraps ? nil : 1)
            .truncationMode(.tail)
            .fixedSize(horizontal: false, vertical: wraps)
            .help(help ?? text)
            .accessibilityLabel(text)
    }
}
