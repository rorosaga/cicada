import SwiftUI

/// F1 R-FX11 — a page whose only prose is its Summary shows what Cicada
/// believes about it, as claims. The owner found these pages empty, or
/// showing raw YAML. Rows since DS-3a (R-DG22), so a belief reads the same
/// here and in Perspectives.
struct WhatCicadaKnowsSection: View {
    let claims: [Claim]
    var onOpenTimeline: (Claim) -> Void = { _ in }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.Beliefs.heading(claims.count))
            Text(Copy.Beliefs.caption)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                ForEach(claims) { claim in
                    BeliefRow(claim: claim) { onOpenTimeline(claim) }
                }
            }
            .padding(.horizontal, -CicadaTheme.scaled(10))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
