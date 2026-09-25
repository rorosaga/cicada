import SwiftUI

/// Seam 3 on Home: after onboarding's *Open Cicada* (`TourOffer.request()`), the first Home offers the tour once —
/// "Take a quick tour?" with *Take the tour* and *Not now*. A grouped block in Home's column (DR-20's `glassCard`),
/// with a `NeutralButton`: Home has no primary (DS-3b). *Not now* is remembered like a skip; Settings → General and
/// the `?` still replay it.
struct TourOfferCard: View {
    @Environment(TourController.self) private var tour

    var body: some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(Copy.Tour.offerTitle)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .accessibilityAddTraits(.isHeader)
                Text(Copy.Tour.offerLine)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            TextButton(title: Copy.Tour.offerNotNow) { tour.declineOffer() }
            NeutralButton(title: Copy.Tour.offerTake, size: .compact) { tour.requestStart() }
        }
        .padding(CicadaTheme.spacingMD)
        .glassCard()
    }
}

/// The `?` popover's replay row (G152: "replayable from … the `?` popover"). The closure is built by the button that
/// owns the popover, so the popover's content needs nothing from the environment.
struct TourReplayRow: View {
    let start: () -> Void

    var body: some View {
        HStack {
            TextButton(title: Copy.Tour.helpRow, action: start)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, CicadaTheme.spacingSM)
        .padding(.bottom, CicadaTheme.spacingSM)
        .background(CicadaTheme.bgMenu)
    }
}
