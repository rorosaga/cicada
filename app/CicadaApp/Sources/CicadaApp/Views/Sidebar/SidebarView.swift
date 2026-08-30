import SwiftUI

enum AppTab: String, CaseIterable {
    case graph = "Graph"
    case clusters = "Clusters"
    case feed = "Feed"
    case sleep = "Sleep"
    case inbox = "Inbox"
    case contributors = "Contributors"
    case connections = "Connections"
    case connect = "Connect"
    case sources = "Capture"
    case usage = "Usage"

    var icon: String {
        switch self {
        case .graph: "point.3.connected.trianglepath.dotted"
        case .clusters: "circle.grid.2x2"
        case .feed: "photo.stack"
        case .sleep: "moon.fill"
        case .inbox: "tray.full"
        case .contributors: "person.2.badge.gearshape"
        case .connections: "person.crop.circle.badge.checkmark"
        case .connect: "cable.connector"
        case .sources: "tray.and.arrow.down"
        case .usage: "chart.bar.xaxis"
        }
    }

    /// The label the user sees. Deliberately separate from `rawValue`, which is
    /// this tab's stable identifier (persisted state, cache keys, the ⌘-slot
    /// order in `allCases`) and must not move when the copy changes — G63
    /// renames Connections → "Plans & keys" and Connect → "Agents".
    var title: String {
        switch self {
        case .connections: "Plans & keys"
        case .connect: "Agents"
        default: rawValue
        }
    }
}

/// Linear/Notion-style sidebar sections. Quiet uppercase labels group the flat
/// tab list by mental model without adding any new theme tokens.
private enum SidebarSection: String, CaseIterable {
    case workspace = "Workspace"
    case capture = "Capture"
    case maintenance = "Maintenance"
    case provenance = "Provenance"
    case setup = "Setup"

    var tabs: [AppTab] {
        switch self {
        case .workspace: [.graph, .clusters, .feed]
        case .capture: [.sources]
        case .maintenance: [.sleep, .inbox]
        case .provenance: [.contributors, .usage]
        case .setup: [.connections, .connect]
        }
    }
}

struct SidebarView: View {
    @Binding var selectedTab: AppTab
    var inboxCount: Int

    // Theme toggle. Persists directly to the same key CicadaApp/ContentView
    // read, so flipping it here propagates everywhere without any extra
    // plumbing.
    @AppStorage("cicada.colorScheme") private var colorSchemeRaw: String = AppColorScheme.dark.rawValue
    private var colorScheme: AppColorScheme { AppColorScheme(rawValue: colorSchemeRaw) ?? .dark }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            ForEach(SidebarSection.allCases, id: \.self) { section in
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    Text(section.rawValue.uppercased())
                        .font(.system(size: 10, weight: .semibold, design: .monospaced))
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .tracking(1.2)
                        .padding(.horizontal, CicadaTheme.spacingLG)
                        .padding(.leading, CicadaTheme.spacingSM)

                    ForEach(section.tabs, id: \.self) { tab in
                        sidebarButton(for: tab)
                    }
                }
            }

            Spacer()

            HStack(spacing: CicadaTheme.spacingSM) {
                Text("Cicada")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)

                Spacer()

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
        switch tab {
        case .graph, .clusters, .feed, .sleep, .contributors, .connections, .connect, .sources, .usage: 0
        case .inbox: inboxCount
        }
    }

    /// Wraps `SidebarRow` in a real `Button` so VoiceOver and UI-automation
    /// tools (which drive the accessibility tree, not gesture recognizers)
    /// can activate a tab, and attaches ⌘1…⌘9 to the first nine tabs in
    /// `AppTab`'s stable declaration order (not per-section order, so the
    /// shortcut a user learns for a tab doesn't shift if a section is
    /// reordered without touching the tab list itself).
    @ViewBuilder
    private func sidebarButton(for tab: AppTab) -> some View {
        let count = badgeCount(for: tab)
        let isSelected = selectedTab == tab
        let label = count > 0 ? "\(tab.title), \(count) pending" : tab.title

        let button = Button {
            withAnimation(.spring(duration: 0.25)) {
                selectedTab = tab
            }
        } label: {
            SidebarRow(tab: tab, isSelected: isSelected, badgeCount: count)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
        .accessibilityAddTraits(isSelected ? [.isSelected] : [])

        if let globalIndex = AppTab.allCases.firstIndex(of: tab), globalIndex < 9 {
            button.keyboardShortcut(KeyEquivalent(Character("\(globalIndex + 1)")), modifiers: .command)
        } else {
            button
        }
    }
}

private struct SidebarRow: View {
    let tab: AppTab
    let isSelected: Bool
    let badgeCount: Int
    @State private var isHovered = false

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            Image(systemName: tab.icon)
                .font(.system(size: 16))
                .foregroundStyle(isSelected ? CicadaTheme.accent : CicadaTheme.textSecondary)
                .frame(width: 24)

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
        .buttonStyle(.plain)
        .help(colorScheme == .dark ? "Switch to light mode" : "Switch to dark mode")
        .onHover { isHovered = $0 }
        .animation(.easeInOut(duration: 0.15), value: isHovered)
    }
}
