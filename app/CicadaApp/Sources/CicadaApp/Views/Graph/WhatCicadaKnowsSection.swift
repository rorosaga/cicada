import SwiftUI

/// F1 R-FX11 — a page whose only prose is its Summary shows what Cicada
/// believes about it, as claims, with the Perspectives tab's `ClaimChip`, so a
/// belief looks the same wherever it appears. The owner found these pages
/// empty, or showing raw YAML.
struct WhatCicadaKnowsSection: View {
    let claims: [Claim]
    var onOpenTimeline: (Claim) -> Void = { _ in }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(Copy.Beliefs.title)
                .font(CicadaTheme.headingFont)
                .foregroundStyle(CicadaTheme.textPrimary)
            Text(Copy.Beliefs.caption)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            ForEach(claims) { claim in
                ClaimChip(claim: claim, onOpenTimeline: { onOpenTimeline(claim) })
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
