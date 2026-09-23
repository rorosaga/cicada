import SwiftUI

/// The list page's header (DR-25): no page-title band — an eyebrow on the left ("Inbox · 6
/// pending", 12 medium, `textTertiary`, tabular) and the page's text tabs on the right, in one
/// row at least 28 pt tall, 20 pt below the titlebar. The old subtitle moves into the `?`
/// popover and the empty state. Built here; each list page adopts it in its DS track (R-DS27).
struct EyebrowRow<Trailing: View>: View {
    static var topPadding: CGFloat { 20 }
    static var minHeight: CGFloat { 28 }

    let eyebrow: String
    /// 40 pt with nothing open (the list alone), 24 pt once columns open (§5.3).
    var horizontalPadding: CGFloat = CicadaTheme.spacingGutter
    @ViewBuilder var trailing: () -> Trailing

    var body: some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
            Text(eyebrow)
                .font(CicadaTheme.metaMediumFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
            Spacer(minLength: CicadaTheme.spacingSM)
            trailing()
        }
        .frame(minHeight: CicadaTheme.scaled(Self.minHeight))
        .padding(.top, CicadaTheme.scaled(Self.topPadding))
        .padding(.horizontal, horizontalPadding)
        .padding(.bottom, CicadaTheme.spacingMD)
    }
}

extension EyebrowRow where Trailing == EmptyView {
    init(eyebrow: String, horizontalPadding: CGFloat = CicadaTheme.spacingGutter) {
        self.init(eyebrow: eyebrow, horizontalPadding: horizontalPadding, trailing: { EmptyView() })
    }
}

/// "Inbox · 1 of 6 · Conflict" — the eyebrow's grammar: parts joined by a middle dot, an
/// empty part dropped so a page with nothing pending never reads "Clusters · ".
enum Eyebrow {
    static func text(_ parts: String...) -> String {
        parts.filter { !$0.isEmpty }.joined(separator: " · ")
    }
}
