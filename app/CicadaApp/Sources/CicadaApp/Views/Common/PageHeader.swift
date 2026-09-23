import SwiftUI

/// A page's title in its one face (G137 R-M16, F1 R-FX12): the display face —
/// SF Pro Display semibold at 28 pt with `displayTracking` — in `textPrimary`.
/// `PageHeader` draws its title through this, and so does the Sleep page's
/// header, which sits inside its centred column with the staleness chip beside
/// it (Z-B4) — the live check found that header still in SF 20 semibold because
/// it had copied the old font instead of sharing it.
///
/// One line that shrinks up to 20 % before it truncates (R-FX12): SF sets about
/// 30 % wider than the serif it replaced — "Integrations" 114 → 152 pt measured
/// — so a long per-source title at 1.4× would otherwise wrap the header.
struct PageTitle: View {
    static let size: CGFloat = 28
    let text: String

    init(_ text: String) { self.text = text }

    var body: some View {
        Text(text)
            .font(CicadaTheme.displayFont(size: Self.size))
            .tracking(CicadaTheme.displayTracking(size: Self.size))
            .lineLimit(1)
            .minimumScaleFactor(0.8)
            .foregroundStyle(CicadaTheme.textPrimary)
    }
}

/// Shared page header (Linear/Notion convention): a title, an optional one-line
/// subtitle, and an optional right-aligned trailing action. Promotes the
/// ad-hoc header that SleepView established into one reusable component so every
/// primary screen (Graph, Clusters, Feed, Sleep, Inbox, Contributors) lays out
/// identically: `spacingXL` outer padding, a display title in `textPrimary`
/// (`PageTitle`, shared with the Sleep page's header — the display face since
/// F1 R-FX12), `bodyFont` subtitle in `textSecondary`.
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
                PageTitle(title)
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
