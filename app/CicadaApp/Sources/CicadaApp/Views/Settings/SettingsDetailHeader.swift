import SwiftUI

/// The detail pane's header (design §2.1): a section shows its title in the
/// display face (SF Pro Display semibold, tracked — F1 R-FX12) with its
/// subtitle beneath; a sub-page shows `‹ Parent /
/// Title`, the chevron and parent being the way back (⌘[ — a visible
/// button's shortcut, never a hidden one; R-O5). The header is its section's
/// landing anchor (R-O14). The title is DR-16's H1 (22), and the header keeps
/// clear of the panel's floating `esc` keycap and close × through
/// `settingsHeaderTrailingInset` (R-DS26).
struct SettingsDetailHeader: View {
    struct Subpage {
        let title: String
        let back: () -> Void
    }

    let section: SettingsSection
    var subpage: Subpage? = nil
    var trailing: AnyView? = nil
    @Environment(\.settingsHeaderTrailingInset) private var trailingInset

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                if let subpage {
                    HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                        Button(action: subpage.back) {
                            Label(section.title, systemImage: "chevron.left")
                                .font(CicadaTheme.bodyFont)
                                .foregroundStyle(CicadaTheme.textSecondary)
                        }
                        .buttonStyle(.cicadaPlain)
                        .keyboardShortcut("[", modifiers: .command)
                        .accessibilityLabel("Back to \(section.title)")
                        Text("/")
                            .font(CicadaTheme.bodyFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                        Text(subpage.title)
                            .font(CicadaTheme.displayFont(size: 22))
                            .tracking(CicadaTheme.displayTracking(size: 22))
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .accessibilityAddTraits(.isHeader)
                    }
                } else {
                    Text(section.title)
                        .font(CicadaTheme.displayFont(size: 22))
                        .tracking(CicadaTheme.displayTracking(size: 22))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .accessibilityAddTraits(.isHeader)
                    Text(section.subtitle)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: CicadaTheme.spacingMD)
            if let trailing { trailing }
        }
        .padding(.trailing, trailingInset)
        .padding(.top, CicadaTheme.spacingXL)
        .padding(.bottom, CicadaTheme.spacingSM)
        .settingsRow(.page(section))
    }
}

/// One Settings page: its header, then its group cards, in the one scroll
/// view that can land on a row. No header wash on any page (DR-13).
struct SettingsPage<Content: View>: View {
    let section: SettingsSection
    var trailing: AnyView? = nil
    @ViewBuilder var content: () -> Content

    var body: some View {
        SettingsScroll {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                SettingsDetailHeader(section: section, trailing: trailing)
                content()
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            .padding(.bottom, CicadaTheme.spacingXL)
            .frame(maxWidth: CicadaTheme.scaled(760), alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

/// R-DS26 — the panel floats its `esc` keycap and close × over the detail's top-right; the
/// header reserves their width so a page's own trailing control is never under them.
private struct SettingsHeaderTrailingInsetKey: EnvironmentKey { static let defaultValue: CGFloat = 0 }
extension EnvironmentValues {
    var settingsHeaderTrailingInset: CGFloat {
        get { self[SettingsHeaderTrailingInsetKey.self] }
        set { self[SettingsHeaderTrailingInsetKey.self] = newValue }
    }
}
