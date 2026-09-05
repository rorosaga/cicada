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
    /// An optional leading slot before the title (Track D: the per-source
    /// page's origin mark). `nil` by default so every other page's header
    /// renders byte-identical to before this existed — `AnyView?` rather than
    /// a second generic parameter keeps every existing call site, including
    /// the `Trailing == EmptyView` convenience init below, source compatible
    /// with no changes, and `nil` (not an empty view) means the HStack below
    /// never inserts a spacing gap in front of a title that has no mark.
    var leading: AnyView? = nil
    @ViewBuilder var trailing: () -> Trailing

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingMD) {
            if let leading { leading }
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
