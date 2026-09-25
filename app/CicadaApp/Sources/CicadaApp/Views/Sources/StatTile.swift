import SwiftUI

/// One labelled number. Lived in `UsageView.swift` until G124 deleted that
/// page; the Advanced section and the harness panel keep using it for their
/// counts and percentages — never a price.
struct StatTile: View {
    let title: String
    let value: String
    var footnote: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(title).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            Text(value).font(CicadaTheme.titleFont).foregroundStyle(CicadaTheme.textPrimary)
            if let footnote { Text(footnote).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(2) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CicadaTheme.spacingMD)
        .glassCard()
    }
}
