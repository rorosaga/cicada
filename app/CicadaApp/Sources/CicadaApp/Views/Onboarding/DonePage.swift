import SwiftUI

/// Onboarding's last step (G92, G153; v3 2026-10-24, after HeyClicky's "Meet your Clickys"): it ends on the person's
/// own memory, not on "You're set." The menu-bar worm stands over the card, as on *Meet your bookworm* (the same
/// 18 × 18 sheet at a whole number of points per art pixel, nearest-neighbour — the item itself, never a second
/// illustration, DR-13), and the card shows what is already there (`DoneReveal`: the first pages and conversations,
/// "and N more"), what happens next in one line (`DoneLine`: tonight's read, and the one read after an import when
/// something came in), the reviewed public-domain line the owner asked for (`MemoryQuotes`, G153), and Open Cicada.
/// Nothing here starts a read: a read that is already running shows its pages as they land (the Store's graph is
/// live), under "Reading now". Open Cicada by pointer flies the worm into the menu bar as the closing beat
/// (`MenuBarFlight`, #454's); ⏎ shows it with no flight (DR-60); Reduce Motion fades it (DR-66). DR-9, DR-10, DR-17,
/// DR-40, DR-59.
struct DonePage: View {
    let line: String
    let reveal: DoneReveal
    /// The badge's own number (`StatusSnapshot.waitingForSleep`), so the worm here is the one about to fly up.
    let waiting: Int?
    let busy: Bool
    let onBack: () -> Void
    /// Open Cicada by pointer, with the worm's frame on screen (nil when it cannot be measured: no flight then).
    let onOpen: (CGRect?) -> Void

    /// Six points per art pixel at 1×: 108 pt — the card's companion, smaller than *Meet your bookworm*'s.
    static let wormPointSize: CGFloat = 108

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var quote = MemoryQuotes.chosen()
    @State private var anchor = ScreenFrameAnchor.Holder()

    private var wormState: BookwormState {
        if let waiting, waiting > 0 { return .curious(count: waiting) }
        return .happy
    }

    var body: some View {
        VStack(spacing: CicadaTheme.scaled(OnboardingRoomLayout.cardGap)) {
            BookwormView(state: wormState, pointSize: Self.wormPointSize, artSet: .small)
                .background(ScreenFrameAnchor(holder: anchor))
                .accessibilityElement(children: .ignore)
                .accessibilityAddTraits(.isImage)
                .accessibilityLabel(Copy.MeetWorm.imageLabel)
            card
        }
    }

    private var card: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(Copy.doneTitle)
                .font(CicadaTheme.displayFont(size: 28))
                .tracking(CicadaTheme.displayTracking(size: 28))
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)
            revealBlock
            Text(line)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            quoteBlock
            HStack(spacing: CicadaTheme.spacingSM) {
                TextButton(title: Copy.onboardingBack, flushLeading: true, action: onBack)
                Spacer()
                PrimaryActionButton(title: Copy.onboardingOpenCicada) { onOpen(anchor.screenFrame()) }
                    .disabled(busy)
                KeyHint("⏎")
            }
        }
        .padding(CicadaTheme.spacingXL)
        .onboardingCard()
    }

    /// What is already in this memory: the label, up to three rows and "and N more" — or "Nothing yet." A row that
    /// lands while the step shows fades in (DR-61's card fade; a plain fade under Reduce Motion, DR-66).
    private var revealBlock: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            if let label = reveal.label {
                Text(label)
                    .font(CicadaTheme.metaMediumFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            if reveal.isEmpty {
                Text(Copy.doneEmpty)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            ForEach(reveal.items) { item in
                row(item).transition(.opacity)
            }
            if reveal.more > 0 {
                Text(Copy.doneMore(reveal.more))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .monospacedDigit()
            }
        }
        .animation(CicadaMotion.cardFade(reduceMotion: reduceMotion), value: reveal.items.map(\.id))
    }

    private func row(_ item: DoneReveal.Item) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            switch item.kind {
            case .page:
                Image(systemName: "doc.text")
                    .font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: CicadaTheme.scaled(16))
            case .conversation(let origin):
                OriginMark(origin: origin, size: CicadaTheme.scaled(16))
            }
            Text(item.title)
                .font(CicadaTheme.rowFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(1)
                .truncationMode(.tail)
        }
        .frame(minHeight: CicadaTheme.scaled(24))
        .accessibilityElement(children: .combine)
        .accessibilityValue(item.kind == .page ? Copy.donePage : Copy.doneWaiting)
    }

    /// Words through `Copy`, never `Text("\(…)")`: Views/Onboarding/ is in `CountLiteralLintTests`' scope, and a year
    /// must never be grouped ("1,895") — `Copy.readyQuoteYear` prints it with `String(_:)`.
    private var quoteBlock: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(Copy.readyQuoteLine(quote.text))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
            (Text(Copy.readyQuoteAuthor(quote.author)) + Text(quote.work).italic() + Text(Copy.readyQuoteYear(quote.year)))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        .accessibilityElement(children: .combine)
    }
}
