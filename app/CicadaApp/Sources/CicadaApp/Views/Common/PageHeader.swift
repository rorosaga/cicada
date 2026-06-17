import SwiftUI

/// Shared page header (Linear/Notion convention): a title, an optional one-line
/// subtitle, and an optional right-aligned trailing action. Promotes the
/// ad-hoc header that SleepView established into one reusable component so every
/// primary screen (Graph, Clusters, Feed, Sleep, Inbox, Contributors) lays out
/// identically: `spacingXL` outer padding, `titleFont` title in `textPrimary`,
/// `bodyFont` subtitle in `textSecondary`.
struct PageHeader<Trailing: View>: View {
    let title: String
    var subtitle: String? = nil
    @ViewBuilder var trailing: () -> Trailing

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text(title)
                    .font(CicadaTheme.titleFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                if let subtitle {
                    Text(subtitle)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: CicadaTheme.spacingMD)
            trailing()
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
        .padding(.top, CicadaTheme.spacingXL)
        .padding(.bottom, CicadaTheme.spacingLG)
    }
}

extension PageHeader where Trailing == EmptyView {
    init(title: String, subtitle: String? = nil) {
        self.title = title
        self.subtitle = subtitle
        self.trailing = { EmptyView() }
    }
}
