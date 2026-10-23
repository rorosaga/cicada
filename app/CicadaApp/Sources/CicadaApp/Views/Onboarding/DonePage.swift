import SwiftUI

/// Onboarding v2, step 5 (G92, G153; 2026-10-22) — the card under the study room: "You're set.", one reviewed
/// public-domain line (`MemoryQuotes`, SF 17 — neither the quote face nor a display line, R-OB15; the owner asked for
/// it), what happens next in one line (`DoneLine`: imports coming in now, the schedule's own time, or Read now on
/// Home — never a promise the schedule does not keep), and Open Cicada, which marks the bank, offers the tour (seam 3)
/// and lands on Home. Under 40 words with the quote. DR-13, DR-17, DR-40, DR-60.
struct DonePage: View {
    let line: String
    let busy: Bool
    let onBack: () -> Void
    let onOpen: () -> Void

    @State private var quote = MemoryQuotes.chosen()

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(Copy.readyTitle)
                .font(CicadaTheme.displayFont(size: 40))
                .tracking(CicadaTheme.displayTracking(size: 40))
                .foregroundStyle(CicadaTheme.textPrimary)
                .accessibilityAddTraits(.isHeader)
            Text(line)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            quoteBlock
            HStack(spacing: CicadaTheme.spacingSM) {
                TextButton(title: Copy.onboardingBack, action: onBack)
                Spacer()
                PrimaryActionButton(title: Copy.onboardingOpenCicada, action: onOpen).disabled(busy)
                KeyHint("⏎")
            }
        }
        .padding(CicadaTheme.spacingXL)
        .floatingSurface(in: CicadaTheme.shape(CicadaTheme.radiusLarge))
    }

    /// Words through `Copy`, never `Text("\(…)")`: Views/Onboarding/ is in `CountLiteralLintTests`' scope, and a year
    /// must never be grouped ("1,895") — `Copy.readyQuoteYear` prints it with `String(_:)`.
    private var quoteBlock: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(Copy.readyQuoteLine(quote.text))
                .font(CicadaTheme.font(size: 17))
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            (Text(Copy.readyQuoteAuthor(quote.author)) + Text(quote.work).italic() + Text(Copy.readyQuoteYear(quote.year)))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        .padding(.leading, CicadaTheme.spacingMD)
        .accessibilityElement(children: .combine)
    }
}
