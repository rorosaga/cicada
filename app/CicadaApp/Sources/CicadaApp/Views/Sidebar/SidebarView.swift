import SwiftUI

/// The six primary views. Raw values are this tab's **stable identity** —
/// the persisted selection (`cicada.selectedTab`) and the ⌘-slot order in
/// `allCases` — so a surviving tab's raw value must never move, even when its
/// label changes.
///
/// G68 retired five tabs: Capture merged into Feed, Contributors + Usage
/// merged into Activity, and Connections + Connect became Settings tabs
/// (⌘,). G124 then replaced Activity with Sources. All six retired raw values
/// still sit in some user's defaults, so decode through `restored(from:)` —
/// never `AppTab(rawValue:)!`.
enum AppTab: String, CaseIterable {
    case graph = "Graph"
    case clusters = "Clusters"
    case feed = "Feed"
    case sleep = "Sleep"
    case inbox = "Inbox"
    case sources = "Sources"

    /// Decodes a persisted selection, mapping every retired tab to whichever
    /// page inherited its content. Anything unrecognised falls back to Graph.
    static func restored(from raw: String?) -> AppTab {
        guard let raw, !raw.isEmpty else { return .graph }
        if let tab = AppTab(rawValue: raw) { return tab }
        switch raw {
        case "Capture": return .feed
        case "Activity", "Contributors", "Usage": return .sources   // G124: Activity → Sources
        case "Connections", "Connect": return .graph   // now Settings tabs (⌘,)
        default: return .graph
        }
    }

    var icon: String {
        switch self {
        case .graph: "point.3.connected.trianglepath.dotted"
        case .clusters: "circle.grid.2x2"
        case .feed: "photo.stack"
        case .sleep: "moon.fill"
        case .inbox: "tray.full"
        case .sources: "tray.2"
        }
    }

    /// The label the user sees. Identical to `rawValue` since G68 — the two
    /// renamed pages (Plans & keys, Agents) are Settings tabs now, not rows.
    var title: String { rawValue }
}

struct SidebarView: View {
    @Binding var selectedTab: AppTab
    var inboxCount: Int
    /// Drives the small spinner on the Sleep row while a cycle runs.
    var isSleeping: Bool
    /// Raises the gear's attention dot when a subscription login has expired.
    var needsAttention: Bool
    var onOpenSettings: () -> Void

    @AppStorage("cicada.colorScheme") private var colorSchemeRaw: String = AppColorScheme.dark.rawValue
    private var colorScheme: AppColorScheme { AppColorScheme(rawValue: colorSchemeRaw) ?? .dark }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            // No section labels. Six rows do not need to be grouped into five
            // buckets — the labels were longer than the lists they introduced.
            ForEach(AppTab.allCases, id: \.self) { tab in
                sidebarButton(for: tab)
            }

            Spacer()

            HStack(spacing: CicadaTheme.spacingSM) {
                Text("Cicada")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)

                Spacer()

                SettingsGearButton(needsAttention: needsAttention, action: onOpenSettings)

                ThemeToggleButton(colorScheme: colorScheme) {
                    colorSchemeRaw = (colorScheme == .dark ? AppColorScheme.light : AppColorScheme.dark).rawValue
                }
            }
            .padding(.horizontal, CicadaTheme.spacingLG)
            .padding(.bottom, CicadaTheme.spacingMD)
        }
        .padding(.top, CicadaTheme.spacingXL)
        .frame(minWidth: 180)
        .background(CicadaTheme.background)
    }

    private func badgeCount(for tab: AppTab) -> Int {
        tab == .inbox ? inboxCount : 0
    }

    /// Wraps `SidebarRow` in a real `Button` so VoiceOver and UI automation
    /// (which drive the accessibility tree, not gesture recognizers) can
    /// activate a tab, and attaches ⌘1–⌘6 in visual order.
    @ViewBuilder
    private func sidebarButton(for tab: AppTab) -> some View {
        let count = badgeCount(for: tab)
        let isSelected = selectedTab == tab
        let isBusy = tab == .sleep && isSleeping
        let label = accessibilityLabel(for: tab, count: count, isBusy: isBusy)

        let button = Button {
            withAnimation(.spring(duration: 0.25)) { selectedTab = tab }
        } label: {
            SidebarRow(tab: tab, isSelected: isSelected, badgeCount: count, isBusy: isBusy)
        }
        .buttonStyle(.cicadaPlain)
        .accessibilityLabel(label)
        .accessibilityAddTraits(isSelected ? [.isSelected] : [])

        if let index = AppTab.allCases.firstIndex(of: tab), index < 9 {
            button.keyboardShortcut(KeyEquivalent(Character("\(index + 1)")), modifiers: .command)
        } else {
            button
        }
    }

    /// Plain (non-`@ViewBuilder`) helper: the accessibility label is built by
    /// mutating a `String`, and a result-builder context can't host that
    /// control flow (an `if` with no `else` in a `@ViewBuilder` body must
    /// itself produce a `View`).
    private func accessibilityLabel(for tab: AppTab, count: Int, isBusy: Bool) -> String {
        var label = tab.title
        if count > 0 { label += ", \(count) pending" }
        if isBusy { label += ", consolidating" }
        return label
    }
}

private struct SidebarRow: View {
    let tab: AppTab
    let isSelected: Bool
    let badgeCount: Int
    let isBusy: Bool
    @State private var isHovered = false

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            if isBusy {
                ProgressView().controlSize(.small).frame(width: 24)
            } else {
                Image(systemName: tab.icon)
                    .font(.system(size: 16))
                    .foregroundStyle(isSelected ? CicadaTheme.accent : CicadaTheme.textSecondary)
                    .frame(width: 24)
            }

            Text(tab.title)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(isSelected ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)

            Spacer()

            if badgeCount > 0 {
                Text("\(badgeCount)")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(CicadaTheme.accent.opacity(0.8))
                    .clipShape(Capsule())
            }
        }
        .padding(.horizontal, CicadaTheme.spacingLG)
        .padding(.vertical, CicadaTheme.spacingMD)
        .background(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .fill(isSelected ? CicadaTheme.accent.opacity(0.12) : (isHovered ? CicadaTheme.surfaceHover.opacity(0.5) : .clear))
        )
        .contentShape(Rectangle())
        .padding(.horizontal, CicadaTheme.spacingSM)
        .onHover { isHovered = $0 }
        .animation(.easeInOut(duration: 0.15), value: isHovered)
        .animation(.easeInOut(duration: 0.15), value: isSelected)
    }
}

/// Sun/moon toggle in the sidebar footer, next to the "Cicada" wordmark.
/// Purely presentational — the parent owns reading/writing
/// `cicada.colorScheme` so this stays a dumb button.
private struct ThemeToggleButton: View {
    let colorScheme: AppColorScheme
    let action: () -> Void
    @State private var isHovered = false

    var body: some View {
        Button(action: action) {
            Image(systemName: colorScheme == .dark ? "moon.fill" : "sun.max.fill")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(isHovered ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                .frame(width: 22, height: 22)
                .background(
                    Circle().fill(isHovered ? CicadaTheme.surfaceHover : .clear)
                )
        }
        .buttonStyle(.cicadaPlain)
        .help(colorScheme == .dark ? "Switch to light mode" : "Switch to dark mode")
        .onHover { isHovered = $0 }
        .animation(.easeInOut(duration: 0.15), value: isHovered)
    }
}

/// Footer gear → the native Settings window (⌘,). The dot means a
/// subscription is installed but signed out, which is the one connection
/// problem that silently degrades every other page.
private struct SettingsGearButton: View {
    let needsAttention: Bool
    let action: () -> Void
    @State private var isHovered = false

    var body: some View {
        Button(action: action) {
            Image(systemName: "gearshape")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(isHovered ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                .frame(width: 22, height: 22)
                .background(Circle().fill(isHovered ? CicadaTheme.surfaceHover : .clear))
                .overlay(alignment: .topTrailing) {
                    if needsAttention {
                        Circle()
                            .fill(CicadaTheme.warning)
                            .frame(width: 6, height: 6)
                            .offset(x: 1, y: -1)
                    }
                }
        }
        .buttonStyle(.cicadaPlain)
        .help(needsAttention ? "Settings — a connection needs you (⌘,)" : "Settings (⌘,)")
        .accessibilityLabel(needsAttention ? "Settings, a connection needs attention" : "Settings")
        .onHover { isHovered = $0 }
        .animation(.easeInOut(duration: 0.15), value: isHovered)
    }
}
