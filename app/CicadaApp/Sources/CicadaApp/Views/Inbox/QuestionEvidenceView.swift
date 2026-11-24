import SwiftUI

/// The evidence under a question, one component for every kind of card that has a cause (owner 2026-11-24, DESIGN_RULES
/// §9; DR-18, DR-38, DR-54, DR-57). What it draws is `QuestionEvidence`'s decision: a conversation as the Reader's own
/// chat bubbles — each turn on the side of who said it, the mention washed — or a note as a quote in whole sentences;
/// then, under it, where it came from in a person's words (DR-54) with "Show in conversation ›" where a Reader can open
/// beside the card, and the one line that says a name was found by searching rather than quoted (R-DI11).
///
/// It never fetches a page and never writes: the words are the server's excerpt (`inbox_context`), the digits of a
/// number token are asked for here as the card's quote has always done.
struct QuestionEvidenceView: View {
    let item: InboxItem
    /// "Show in conversation ›" — only on the card that has a Reader column beside it.
    var opensConversation = true

    @Environment(Store.self) private var store: Store?
    @Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?
    @State private var numbers: [String: String] = [:]

    var body: some View {
        let shape = QuestionEvidence.of(item, links: store.links)
        VStack(alignment: .leading, spacing: 0) {
            switch shape {
            case let .chat(chat):
                // The Reader's rows over the turns the server cut; a sitting of someone else's chat reads on their side.
                VStack(alignment: .leading, spacing: 0) {
                    ReaderChatRows(rows: chat.rows, landingTurn: chat.focusTurn, revealed: true,
                                   messagesChat: chat.messagesChat)
                }
                .environment(\.revealedNumbers, numbers)
                .padding(.top, CicadaTheme.scaled(20))
                .task(id: chat.text) { await reveal(chat.text) }
            case let .quote(segments):
                // Selectable and washed: a selectable `Text` never reaches the span renderer, so the washes ride `CitedPassage`.
                RevealingPassage(segments: segments)
                    .quoteBlock()
                    .padding(.top, CicadaTheme.scaled(20))
            case .none:
                EmptyView()
            }
            sourceLine(hasEvidence: shape != .none)
            if QuoteSegments.isDerived(item), shape != .none {
                Text(Copy.Provenance.derivedCaption)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.top, CicadaTheme.scaled(2))
            }
        }
    }

    private func reveal(_ text: String) async {
        let tokens = NumberTokens.ids(in: text)
        guard !tokens.isEmpty, let answer = await APIClient.shared.revealNumbers(tokens) else { return }
        numbers = answer.numbers
    }

    /// DR-54 — the mark, the app, the conversation's title and the day; the episode id only in `.help`.
    private func sourceLine(hasEvidence: Bool) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            if let origin = InboxSourceLine.markOrigin(item) {
                OriginMark(origin: origin, size: CicadaTheme.scaled(14)).markHover()
            }
            Text(InboxSourceLine.full(item))
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer(minLength: CicadaTheme.spacingSM)
            if opensConversation, let provenance,
               let target = item.cause?.readerTarget(subjectId: item.entityId.isEmpty ? nil : item.entityId) {
                let showing = provenance.isPresented && provenance.current?.episode == target.episode
                Button { showing ? provenance.close() : provenance.open(target) } label: {
                    HStack(spacing: CicadaTheme.scaled(3)) {
                        Text(showing ? Copy.Inbox.hideConversation : Copy.Provenance.showInConversation)
                        Image(systemName: showing ? "chevron.left" : "chevron.right").font(CicadaTheme.icon(.inline))
                    }
                }
                .buttonStyle(.cicadaPlain)
                .font(CicadaTheme.metaMediumFont)
                .foregroundStyle(CicadaTheme.accentText)
                .help(showing ? Copy.Inbox.hideConversationHelp : Copy.Inbox.showConversationHelp)
            }
        }
        .frame(minHeight: CicadaTheme.scaled(22))
        .help(InboxSourceLine.help(item) ?? "")
        .padding(.top, CicadaTheme.scaled(hasEvidence ? 12 : 10))
    }
}
