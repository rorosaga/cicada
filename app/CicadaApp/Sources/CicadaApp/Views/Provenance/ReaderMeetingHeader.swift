import SwiftUI

/// The card under a meeting's title (owner, 2026-11-23: "something at the top that maybe can be hidden … always the top
/// with the title"): the recorder's summary, the meeting's facts and, when a tool on this Mac split the voices, a line
/// saying `Speaker 1`/`2` are its guess. It is pinned above the chat's scroll — a chat opens at its newest message, so a
/// row inside the history would never be seen first — and the summary is no bubble: it is the recorder's words, never
/// the person's or another speaker's (ruling 52a), which is why it is told apart from the turns.
///
/// Compact by default (owner 2026-11-23: "a bit smaller, and if anything we can expand it"; then "kind of wack … icons
/// instead of words for Google Meet, Teams, Zoom"): one quiet line — the call app's mark, the length, how many were
/// invited — and the summary's first two lines; the chevron opens the whole summary, the voices line and the recorder's
/// note on who wrote it. The recorder itself is the title's mark, so the line never says it again (DR-38). A summary
/// holding a cited passage opens whole, so a wash is never cut off.
///
/// D (DESIGN_RULES §9): the fill is the other side's quiet bubble fill with the resting ring, never a shadow (DR-9,
/// DR-10) and never the accent (DR-5); the call app is its real mark (DR-52) with its name in `.help` and VoiceOver; the
/// one control is the disclosure chevron (DR-39), remembered per viewer on this Mac. Opening never animates.
struct ReaderMeetingHeaderView: View {
    @Environment(\.revealedNumbers) private var numbers
    let header: ReaderChat.MeetingHeader
    let revealed: Bool
    /// The viewer's choice (`ReaderMeetingHeaderView.expandedKey`), per viewer and never in the bank.
    @AppStorage(ReaderMeetingHeaderView.expandedKey) private var expanded = false
    @State private var hovering = false

    static let expandedKey = "reader.meetingSummaryExpanded"
    /// The summary's lines while the card is compact.
    static let compactLines = 2
    /// The tallest the open summary grows before it scrolls inside the card, so a long one never takes the column.
    static let summaryMaxHeight: CGFloat = 220
    static let markSize: CGFloat = 14

    private var open: Bool { expanded || header.holdsFocus }
    /// Something more to show than the compact card holds.
    private var expandable: Bool {
        !header.holdsFocus && (header.hasSummary || header.voices != nil || header.writer != nil)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
            if expandable {
                Button { Instant.run { expanded.toggle() } } label: { factsLine }
                    .buttonStyle(.plain)
                    .onHover { hovering = $0 }
                    .help(open ? Copy.Provenance.meetingSummaryLess : Copy.Provenance.meetingSummaryMore)
                    .accessibilityLabel(header.facts ?? Copy.Provenance.meetingSummary(by: nil))
                    .accessibilityValue(open ? Copy.Provenance.meetingSummaryOpen : Copy.Provenance.meetingSummaryClosed)
            } else {
                factsLine
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel(header.facts ?? "")
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
        .padding(.vertical, CicadaTheme.scaled(8))
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.chatBubbleOtherFill))
        .overlay(CicadaTheme.shape(CicadaTheme.cornerRadius).strokeBorder(CicadaTheme.ring(.resting), lineWidth: 1))
        .padding(.horizontal, CicadaTheme.scaled(ReaderColumn.inset))
        .padding(.bottom, CicadaTheme.spacingSM)
        .accessibilityElement(children: .contain)
        .help(Copy.Provenance.meetingSummaryHelp)
    }

    /// `[Meet] 17 min · 👥 6 ……… ⌄` — the call app as its mark (its name when no mark is known), the length, the invitees.
    private var factsLine: some View {
        HStack(alignment: .center, spacing: CicadaTheme.scaled(6)) {
            if let mark = header.appMark {
                OriginMark(origin: mark, size: CicadaTheme.scaled(Self.markSize))
                    .help(header.appName ?? "")
                    .accessibilityHidden(true)
            } else if let name = header.appName, !name.isEmpty {
                Text(name)
            }
            if let length = header.length {
                if header.appMark == nil, header.appName?.isEmpty == false { dot }
                Text(length).monospacedDigit()
            }
            if let attendees = header.attendees, attendees > 0 {
                if header.length != nil || header.appName?.isEmpty == false { dot }
                HStack(spacing: CicadaTheme.scaled(3)) {
                    Image(systemName: "person.2.fill").font(CicadaTheme.icon(.badge))
                    Text("\(attendees)").monospacedDigit()
                }
                .help(Copy.Provenance.meetingInvited(attendees))
            }
            Spacer(minLength: 0)
            if expandable {
                Image(systemName: open ? "chevron.up" : "chevron.down")
                    .font(CicadaTheme.icon(.disclosure))
                    .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                    .accessibilityHidden(true)
            }
        }
        .font(CicadaTheme.metaFont)
        .foregroundStyle(CicadaTheme.textSecondary)
        .lineLimit(1)
        .contentShape(Rectangle())
    }

    private var dot: some View { Text("·").foregroundStyle(CicadaTheme.textTertiary) }

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
