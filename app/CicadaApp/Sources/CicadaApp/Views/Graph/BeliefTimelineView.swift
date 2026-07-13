import SwiftUI

// MARK: - BeliefTimelineView
//
// The flagship C3 demo (§4 of d2-companion-showcase.md): a single belief's life,
// `valid_from → valid_to`, with `superseded_by` chains drawn as a vertical
// thread plus a compact horizontal validity-bar strip. Different from the
// entity-card history tab (which shows file commits) — this shows one claim
// line's temporal evolution as a belief.

struct BeliefTimelineView: View {
    let subject: String
    let predicate: String
    let context: String

    @State private var timeline: ClaimTimeline?
    @State private var isLoading = true

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            header

            if isLoading {
                ProgressView().controlSize(.small)
                    .frame(maxWidth: .infinity, alignment: .center)
            } else if let t = timeline, !t.claims.isEmpty {
                ValidityBarStrip(claims: t.claims)
                Divider().background(CicadaTheme.border)
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(orderedClaims(t.claims).enumerated()), id: \.element.id) { idx, claim in
                        SupersededRow(
                            claim: claim,
                            isCurrent: claim.isValid,
                            isLast: idx == orderedClaims(t.claims).count - 1
                        )
                    }
                }
            } else {
                emptyState
            }
        }
        .padding(CicadaTheme.spacingLG)
        .task { await load() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text("Belief timeline")
                .font(CicadaTheme.headingFont)
                .foregroundStyle(CicadaTheme.textPrimary)
            HStack(spacing: 6) {
                Text(subject)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.accent)
                Text("·").foregroundStyle(CicadaTheme.textTertiary)
                Text(predicate)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                ContextPill(context)
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: "clock.arrow.circlepath")
                .font(.system(size: 24))
                .foregroundStyle(CicadaTheme.textTertiary)
            Text("No timeline for this belief yet.")
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, CicadaTheme.spacingXL)
    }

    /// Newest (currently-valid) first, then the superseded chain descending.
    private func orderedClaims(_ claims: [Claim]) -> [Claim] {
        claims.sorted { lhs, rhs in
            if lhs.isValid != rhs.isValid { return lhs.isValid }   // valid first
            return lhs.validFrom > rhs.validFrom                    // newest first
        }
    }

    private func load() async {
        isLoading = true
        timeline = try? await APIClient.shared.fetchClaimTimeline(
            subject: subject, predicate: predicate, context: context
        )
        isLoading = false
    }
}

// MARK: - ValidityBarStrip
//
// A horizontal strip drawing each claim as a segment on a shared time axis
// (`valid_from` → `valid_to`, open claims extend to "now"), context-colored —
// so contradiction reads as "the orange segment ends exactly where the green
// one begins." That single image IS the bi-temporal story.

struct ValidityBarStrip: View {
    let claims: [Claim]

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text("Validity")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)

            GeometryReader { geo in
                let span = timeSpan
                ZStack(alignment: .topLeading) {
                    ForEach(Array(claims.enumerated()), id: \.element.id) { idx, claim in
                        segment(for: claim, span: span, width: geo.size.width, row: idx)
                    }
                }
            }
            .frame(height: CGFloat(max(1, claims.count)) * 16)
        }
    }

    private struct Span { let start: Double; let end: Double }

    private var timeSpan: Span {
        let froms = claims.map { dayValue($0.validFrom) }
        let tos = claims.map { $0.validTo.map(dayValue) ?? Double.greatestFiniteMagnitude }
        let nowVal = dayValue(todayString)
        let start = froms.min() ?? 0
        let rawEnd = tos.filter { $0 != Double.greatestFiniteMagnitude }.max() ?? start
        let end = max(rawEnd, nowVal)
        return Span(start: start, end: max(end, start + 1))
    }

    @ViewBuilder
    private func segment(for claim: Claim, span: Span, width: CGFloat, row: Int) -> some View {
        let total = span.end - span.start
        let from = dayValue(claim.validFrom)
        let to = claim.validTo.map(dayValue) ?? dayValue(todayString)
        let x = total > 0 ? CGFloat((from - span.start) / total) * width : 0
        let w = total > 0 ? max(4, CGFloat((to - from) / total) * width) : width
        RoundedRectangle(cornerRadius: 3)
            .fill(CicadaTheme.contextColor(claim.context).opacity(claim.isValid ? 0.95 : 0.5))
            .frame(width: w, height: 10)
            .overlay(alignment: .leading) {
                if claim.isValid {
                    RoundedRectangle(cornerRadius: 3)
                        .stroke(CicadaTheme.contextColor(claim.context), lineWidth: 1)
                        .frame(width: w, height: 10)
                }
            }
            .offset(x: x, y: CGFloat(row) * 16)
            .help("\(claim.object) · \(claim.validFrom) → \(claim.validTo ?? "now")")
    }

    /// One shared formatter for the whole strip — `dayValue`/`todayString` are
    /// called once per claim per layout pass, so building a fresh DateFormatter
    /// each time (they're expensive to allocate) was needless churn on long
    /// supersede chains.
    private static let ymdFormatter: DateFormatter = {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    private var todayString: String {
        Self.ymdFormatter.string(from: .now)
    }

    /// Days-since-epoch as a Double for axis math; 0 on an unparseable date.
    private func dayValue(_ ymd: String) -> Double {
        guard let d = Self.ymdFormatter.date(from: ymd) else { return 0 }
        return d.timeIntervalSince1970 / 86_400.0
    }
}

// MARK: - SupersededRow
//
// One claim row in the vertical chain: a colored left rail (solid green for the
// currently-valid claim at the top, fading for superseded ones below), the
// claim object with a strikethrough + closed window for superseded claims, and
// a "superseded by" chevron linking to its replacement. Reuses the history-tab
// rail geometry almost verbatim.

struct SupersededRow: View {
    let claim: Claim
    let isCurrent: Bool
    let isLast: Bool

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            // Left rail
            VStack(spacing: 0) {
                Circle()
                    .fill(isCurrent ? Color(hex: 0x22C55E) : CicadaTheme.contextColor(claim.context))
                    .frame(width: 10, height: 10)
                if !isLast {
                    Rectangle()
                        .fill(CicadaTheme.border)
                        .frame(width: 1)
                        .frame(maxHeight: .infinity)
                }
            }
            .frame(width: 10)

            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                ClaimChip(claim: claim)

                if !isCurrent, claim.supersededBy != nil {
                    HStack(spacing: 4) {
                        Image(systemName: "arrow.down")
                            .font(.system(size: 9, weight: .semibold))
                        Text("superseded by \(claim.supersededBy ?? "")")
                            .font(CicadaTheme.captionFont)
                    }
                    .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .padding(.bottom, CicadaTheme.spacingLG)

            Spacer(minLength: 0)
        }
    }
}
