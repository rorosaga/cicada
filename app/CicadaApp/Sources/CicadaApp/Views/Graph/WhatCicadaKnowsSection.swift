import SwiftUI

/// F1 R-FX11 — a page whose only prose is its Summary shows what Cicada
/// believes about it, as claims. The owner found these pages empty, or
/// showing raw YAML. Rows since DS-3a (R-DG22), so a belief reads the same
/// here and in Perspectives.
struct WhatCicadaKnowsSection: View {
    let claims: [Claim]
    /// False inside the card's "What Cicada believes" disclosure, which already names the section (DR-38).
    var showsLabel = true
    var onOpenTimeline: (Claim) -> Void = { _ in }
    /// A page at a time (`BeliefPaging`): a summary-only page can carry thousands of beliefs.
    @State private var shown = BeliefPaging.step

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if showsLabel { SectionLabel(Copy.Beliefs.heading(claims.count)) }
            Text(Copy.Beliefs.caption)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
            LazyVStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                ForEach(claims.prefix(shown)) { claim in
                    BeliefRow(claim: claim) { onOpenTimeline(claim) }
                }
            }
            .padding(.horizontal, -CicadaTheme.scaled(10))
            if let more = BeliefPaging.more(shown: shown, total: claims.count) {
                TextButton(title: Copy.People.showMore(more)) {
                    Instant.run { shown = BeliefPaging.next(shown: shown, total: claims.count) }
                }
                .padding(.leading, -CicadaTheme.scaled(10))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
