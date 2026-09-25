import SwiftUI

/// F-07 (G145, G153; owner: "just show a you're set message, and a nice quote about forgetting or memory") — back on
/// the full painting, the card: the step counter complete, "You're set.", one reviewed public-domain line
/// (`MemoryQuotes`, SF 17 — neither the quote face nor a display line, R-OB15), what still runs, what keeps up and who
/// is connected (`SetupProgress.summary`, `ReadySummary` — the same numbers Home's Getting started continues with,
/// R-OB4), and Open Cicada, which marks the bank, offers the tour (seam 3) and lands on Home.
struct ReadyPage: View {
    let summary: SetupSummary
    let agents: String?
    /// The connected agents' own marks beside their names (DR-52: a service named is a service marked).
    let agentMarks: [AgentCatalogEntry]
    let startup: String?
    /// `OnboardingScheduleLine` — "Nothing is read until you say so" only on a first run; a rerun after a schedule was
    /// chosen reads what that schedule does.
    let scheduleLine: String?
    let busy: Bool
    let onBack: () -> Void
    let onOpen: () -> Void

    @State private var quote = MemoryQuotes.chosen()

    var body: some View {
        TimelineView(.periodic(from: .now, by: SourceRowText.refreshInterval)) { context in
            VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                HStack {
                    Text(Copy.onboardingStepOf(OnboardingPage.ready.step)).font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                    Spacer()
                    HStack(spacing: CicadaTheme.scaled(4)) {
                        ForEach(OnboardingPage.allCases, id: \.self) { _ in
                            Capsule().fill(CicadaTheme.textPrimary)
                                .frame(width: CicadaTheme.scaled(18), height: CicadaTheme.scaled(3))
                        }
                    }
                    .accessibilityHidden(true)
                }
                Text(Copy.readyTitle)
                    .font(CicadaTheme.displayFont(size: 40))
                    .tracking(CicadaTheme.displayTracking(size: 40))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .accessibilityAddTraits(.isHeader)
                quoteBlock
                rows(now: context.date)
                if let scheduleLine {
                    Text(scheduleLine).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
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
    }

    /// Words through `Copy`, never `Text("\(…)")`: Views/Onboarding/ is in `CountLiteralLintTests`' scope, and a year
    /// must never be grouped ("1,895") — `Copy.readyQuoteYear` prints it with `String(_:)`.
    private var quoteBlock: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(Copy.readyQuoteLine(quote.text))
                .font(CicadaTheme.font(size: 17))
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            (Text(Copy.readyQuoteAuthor(quote.author)) + Text(quote.work).italic() + Text(Copy.readyQuoteYear(quote.year)))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
        }
        .padding(.leading, CicadaTheme.spacingMD)
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    private func rows(now: Date) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            ForEach(summary.comingIn.prefix(2)) { snapshot in SourceRow(model: snapshot.model, now: now) }
            if !summary.keepingUp.isEmpty {
                HStack(spacing: CicadaTheme.spacingSM) {
                    HStack(spacing: CicadaTheme.scaled(3)) {
                        ForEach(summary.keepingUp.prefix(7)) { OriginMark(origin: $0.model.origin, size: CicadaTheme.scaled(14)) }
                    }
                    Text(Copy.readyKeepUp(summary.keepingUp.count)).font(CicadaTheme.font(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Spacer()
                    if let newest = summary.newestSync {
                        Text(SourceRowText.lastSynced(newest, now: now)).font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
                .padding(.horizontal, CicadaTheme.scaled(10))
                .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
            }
            if agents != nil || startup != nil {
                HStack(spacing: CicadaTheme.spacingSM) {
                    HStack(spacing: CicadaTheme.scaled(3)) {
                        ForEach(agentMarks) { AgentMark(entry: $0, size: 14).accessibilityHidden(true) }
                    }
                    if let agents { Text(agents).font(CicadaTheme.font(size: 13, weight: .medium)).foregroundStyle(CicadaTheme.textPrimary) }
                    Spacer()
                    if let startup { Text(startup).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary) }
                }
                .padding(.horizontal, CicadaTheme.scaled(10))
                .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
            }
        }
        .padding(CicadaTheme.spacingXS)
        .background(CicadaTheme.bgPane, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
    }
}
