import SwiftUI

/// The card under a meeting's title (owner, 2026-11-23: "something at the top that maybe can be hidden … always the top
/// with the title"): the recorder's summary, the meeting's facts and, when a tool on this Mac split the voices, a line
/// saying `Speaker 1`/`2` are its guess. It is pinned above the chat's scroll — a chat opens at its newest message, so a
/// row inside the history would never be seen first — and the summary is no bubble: it is the recorder's words, never
/// the person's or another speaker's (ruling 52a), which is why it is told apart from the turns.
///
/// D (DESIGN_RULES §9): the fill is the other side's quiet bubble fill with the resting ring, never a shadow (DR-9,
/// DR-10) and never the accent (DR-5); the state is said in words (DR-37, DR-11); the one control is a text button
/// (DR-40) and the choice is remembered per viewer, on this Mac, in the app's own defaults. Showing or hiding never
/// animates. A summary holding a cited passage stays open, so a wash is never hidden.
struct ReaderMeetingHeaderView: View {
    @Environment(\.revealedNumbers) private var numbers
    let header: ReaderChat.MeetingHeader
    let revealed: Bool
    /// The viewer's choice (`ReaderMeetingHeaderView.hiddenKey`), per viewer and never in the bank.
    @AppStorage(ReaderMeetingHeaderView.hiddenKey) private var hidden = false

    static let hiddenKey = "reader.meetingSummaryHidden"
    /// The tallest the summary grows before it scrolls inside the card, so a long one never takes the column.
    static let summaryMaxHeight: CGFloat = 220

    private var open: Bool { header.hasSummary && (!hidden || header.holdsFocus) }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            if let title = header.title {
                HStack(alignment: .center, spacing: CicadaTheme.spacingSM) {
                    Text(title)
                        .font(CicadaTheme.metaMediumFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .lineLimit(1)
                        .help(Copy.Provenance.meetingSummaryHelp)
                    Spacer(minLength: 0)
                    if !header.holdsFocus {
                        TextButton(title: open ? Copy.Provenance.meetingSummaryHide : Copy.Provenance.meetingSummaryShow,
                                   help: Copy.Provenance.meetingSummaryHelp, inline: true) { Instant.run { hidden.toggle() } }
                            // The text button's own inset, pulled back so its words align with the card's edge.
                            .padding(.trailing, -CicadaTheme.scaled(6))
                    }
                }
            }
            if let facts = header.facts { quiet(facts) }
            if let voices = header.voices { quiet(voices) }
            if open {
                ScrollView {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                        ForEach(header.summary, id: \.id) { block in
                            CitedPassage(segments: NumberTokens.shown(ReaderText.segments(block), numbers),
                                         color: CicadaTheme.textPrimary, reveal: revealed ? 1 : 0)
                        }
                    }
                }
                .frame(maxHeight: CicadaTheme.scaled(Self.summaryMaxHeight))
                .fixedSize(horizontal: false, vertical: true)
                if let writer = header.writer { quiet(writer) }
            }
        }
        .padding(.horizontal, CicadaTheme.scaled(12))
        .padding(.vertical, CicadaTheme.scaled(8))
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius).fill(CicadaTheme.chatBubbleOtherFill))
        .overlay(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius).strokeBorder(CicadaTheme.ring(.resting), lineWidth: 1))
        .padding(.horizontal, CicadaTheme.scaled(ReaderColumn.inset))
        .padding(.bottom, CicadaTheme.spacingSM)
        .accessibilityElement(children: .contain)
    }

    private func quiet(_ words: String) -> some View {
        Text(words)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}
