import SwiftUI

/// The source detail page's own header card (R-S7).
///
/// Clicking a card used to land on a page that answered none of the questions
/// the card had just raised: the `PageHeader` repeated the catalog's long label
/// and one blurb sentence, and the next thing on screen was the queue strip. The
/// state the card had just shown — is this live, how much has it ever fed, is it
/// still growing — was nowhere, and a *failure* was worse: for a harness there
/// is no `ChannelSourceView` state card at all, so the reason a source is broken
/// existed only in the grid tile's tooltip, one navigation behind.
///
/// So this is the tile's five bands again, at page scale, and it is deliberately
/// the SAME five facts from the SAME functions — `SourceDisplayName`,
/// `SourceLiveness`, `SourceOverview.headline`, `SourceDeltaText` — so a card
/// and the page behind it can never name one source two ways (R-S4/R-S19). Two
/// things change with the extra room:
///
/// 1. **The whole error, not its first clause.** `SourceLiveness.verb` folds in
///    `firstClause(of:)` because a tile has one line (critique D2); this page
///    has a paragraph, so `sentence(liveness:fullError:)` re-renders the same
///    verb around the untruncated message.
/// 2. **Thirty days, not fourteen** — `SourceCardMetrics.detailSparkDays`, which
///    is the whole window `source_overview.ACTIVITY_DAYS` ships.
///
/// Everything derived is passed in — `points`, the resolved `liveness`, and the
/// one `today` — so the card stays a plain previewable value view and its
/// parent remains the single place that reads a clock or the `BrowserWatcher`
/// (the same split `SourceCardTile`/`SourceCard` draws).
struct SourceHeaderCard: View {
    let source: SourceOverview
    let liveness: SourceLiveness
    /// The dense 30-day capture series, from Track A's own window function
    /// (R-S8 — called where it lives, never wrapped or re-spelled here).
    let points: [Int]
    /// Resolved ONCE by the parent per body evaluation. `SourceDeltaText`
    /// ignores it today, but its two call sites must not each reach for `.now`,
    /// or a page and the grid it came from can straddle a UTC midnight.
    let today: Date
    var watchState: BrowserWatchState? = nil

    private var delta: String {
        // The window is `points.count`, never a second constant — the sentence
        // under the line cannot claim a span the line does not draw.
        SourceDeltaText.text(points: points, lastActivity: source.lastActivityDate, today: today)
    }

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingLG) {
            identity
            Spacer(minLength: CicadaTheme.spacingMD)
            volume
        }
        .padding(CicadaTheme.spacingMD)
        .glassCard()
        .padding(.horizontal, CicadaTheme.spacingXL)
        .padding(.top, CicadaTheme.spacingSM)
    }

    private var identity: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                OriginMark(origin: source.mark, size: SourceCardMetrics.markSize * 0.72)
                    .frame(width: SourceCardMetrics.markSize, height: SourceCardMetrics.markSize)
                    .background(OriginIconography.color(for: source.mark).opacity(0.12))
                    .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.scaled(6)))
                Text(SourceDisplayName.of(source))
                    .font(CicadaTheme.font(size: 15, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
            }
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingXS) {
                // R-S11 — where a watch exists the G129 light paints the dot, so
                // `.syncing` reads the same blue here as on the tile. `error:
                // nil` on purpose: the `.blocked` state's `FullDiskAccessHint`
                // already renders in `ChannelSourceView`'s state card further
                // down this same page (R-D6 leaves it exactly there), and two
                // identical fix panels one screen apart is the second encoding
                // R-S12 rules out.
                if let watchState {
                    BrowserStatusLight(state: watchState, error: nil, compact: true)
                } else {
                    Circle().fill(liveness.tone.color).frame(width: 7, height: 7)
                }
                Text(Self.sentence(liveness: liveness, fullError: source.lastError))
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(liveness.tone == .danger ? CicadaTheme.danger : CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    /// The lifetime total in the row's own unit above the 30-day line, with the
    /// captures delta under it — R-S3's two nouns, unchanged from the tile, so
    /// 506 saved items never read as 506 recent captures.
    private var volume: some View {
        VStack(alignment: .trailing, spacing: CicadaTheme.spacingXS) {
            if let headline = source.headline {
                HStack(alignment: .firstTextBaseline, spacing: 3) {
                    Text(UsageFormat.count(headline.count))
                        .font(CicadaTheme.font(size: 20, weight: .semibold, design: .rounded))
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Text(headline.count == 1 ? headline.noun : headline.noun + "s")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                .lineLimit(1)
            } else {
                Text("Nothing yet")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            sparkline
            Text(delta)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
        }
        // The number and the delta are spoken; the line between them is the
        // same fact drawn (R-A13 — it never animates and it is never read out).
        .accessibilityElement(children: .combine)
    }

    private var sparkline: some View {
        GeometryReader { geo in
            sparklinePath(points, in: geo.size)
                .stroke(liveness.tone.color.opacity(0.8),
                        style: StrokeStyle(lineWidth: 1, lineCap: .round, lineJoin: .round))
        }
        .frame(width: CicadaTheme.scaled(140), height: CicadaTheme.scaled(28))
        .accessibilityHidden(true)
    }

    /// The card's one status line, with the error at full length.
    ///
    /// It re-renders `SourceLiveness.verb` around the untruncated message rather
    /// than composing its own phrase: the tile and this page must name a failure
    /// with the identical words, and a second sentence template is how "Sync
    /// failed" here becomes "Needs attention" there again (critique D2). A blank
    /// or absent error is no error, so the verb is returned as-is — never a
    /// dangling em dash.
    static func sentence(liveness: SourceLiveness, fullError: String?) -> String {
        let full = fullError?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !full.isEmpty else { return liveness.verb }
        return SourceLiveness(state: liveness.state, detail: full).verb
    }
}
