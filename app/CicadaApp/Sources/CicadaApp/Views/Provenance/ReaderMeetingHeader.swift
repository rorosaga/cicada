import SwiftUI

/// The card under a meeting's title (owner, 2026-11-23: "something at the top that maybe can be hidden … always the top
/// with the title"): the recorder's summary, the meeting's facts and, when a tool on this Mac split the voices, a line
/// saying `Speaker 1`/`2` are its guess. It is pinned above the chat's scroll — a chat opens at its newest message, so a
/// row inside the history would never be seen first — and the summary is no bubble: it is the recorder's words, never
/// the person's or another speaker's (ruling 52a), which is why it is told apart from the turns.
///
/// Compact by default (owner 2026-11-23: "a bit smaller, and if anything we can expand it"): the title with the meeting's
/// facts on one line and the summary's first lines; "More" opens the whole summary, the voices line and the recorder's
/// note. A summary holding a cited passage opens whole, so a wash is never cut off.
///
/// D (DESIGN_RULES §9): the fill is the other side's quiet bubble fill with the resting ring, never a shadow (DR-9,
/// DR-10) and never the accent (DR-5); the state is said in words (DR-37, DR-11); the one control is a text button
/// (DR-40) and the choice is remembered per viewer, on this Mac, in the app's own defaults. Opening never animates.
struct ReaderMeetingHeaderView: View {
    @Environment(\.revealedNumbers) private var numbers
    let header: ReaderChat.MeetingHeader
    let revealed: Bool
    /// The viewer's choice (`ReaderMeetingHeaderView.expandedKey`), per viewer and never in the bank.
    @AppStorage(ReaderMeetingHeaderView.expandedKey) private var expanded = false

    static let expandedKey = "reader.meetingSummaryExpanded"
    /// The summary's lines while the card is compact.
    static let compactLines = 2
    /// The tallest the open summary grows before it scrolls inside the card, so a long one never takes the column.
    static let summaryMaxHeight: CGFloat = 220

    private var open: Bool { expanded || header.holdsFocus }
    /// Something more to show than the compact card holds.
    private var expandable: Bool { !header.holdsFocus && (header.hasSummary || header.voices != nil) }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                Text(headline)
                    .font(CicadaTheme.metaMediumFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .help(Copy.Provenance.meetingSummaryHelp)
                Spacer(minLength: 0)
                if expandable {
                    TextButton(title: open ? Copy.Provenance.meetingSummaryLess : Copy.Provenance.meetingSummaryMore,
                               help: Copy.Provenance.meetingSummaryHelp, inline: true) { Instant.run { expanded.toggle() } }
                        // The text button's own inset, pulled back so its words align with the card's edge.
                        .padding(.trailing, -CicadaTheme.scaled(6))
                }
            }
            if header.hasSummary {
                if open {
                    ScrollView {
                        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) { summary }
                    }
                    .frame(maxHeight: CicadaTheme.scaled(Self.summaryMaxHeight))
                    .fixedSize(horizontal: false, vertical: true)
                } else {
                    // The first lines only; the whole summary is one click away.
                    CitedPassage(segments: NumberTokens.shown(ReaderText.segments(header.summary[0]), numbers),
                                 font: CicadaTheme.metaFont, color: CicadaTheme.textPrimary, reveal: revealed ? 1 : 0)
                        .lineLimit(Self.compactLines)
                }
            }
            if open || !header.hasSummary {
                if let voices = header.voices { quiet(voices) }
                if header.hasSummary, let writer = header.writer { quiet(writer) }
            }
        }
        .padding(.horizontal, CicadaTheme.scaled(10))
        .padding(.vertical, CicadaTheme.scaled(6))
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.chatBubbleOtherFill))
        .overlay(CicadaTheme.shape(CicadaTheme.cornerRadius).strokeBorder(CicadaTheme.ring(.resting), lineWidth: 1))
        .padding(.horizontal, CicadaTheme.scaled(ReaderColumn.inset))
        .padding(.bottom, CicadaTheme.spacingSM)
        .accessibilityElement(children: .contain)
    }

    /// "Summary · written by Hex · 17 min · Google Meet" — or the facts alone when the recorder wrote no summary.
    private var headline: String {
        [header.title, header.facts].compactMap { $0 }.joined(separator: " · ")
    }

    @ViewBuilder private var summary: some View {
        ForEach(header.summary, id: \.id) { block in
            CitedPassage(segments: NumberTokens.shown(ReaderText.segments(block), numbers),
                         font: CicadaTheme.metaFont, color: CicadaTheme.textPrimary, reveal: revealed ? 1 : 0)
        }
    }

    private func quiet(_ words: String) -> some View {
        Text(words)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}
