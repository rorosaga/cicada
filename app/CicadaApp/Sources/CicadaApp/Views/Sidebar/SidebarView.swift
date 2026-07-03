import SwiftUI

enum AppTab: String, CaseIterable {
    case graph = "Graph"
    case clusters = "Clusters"
    case feed = "Feed"
    case sleep = "Sleep"
    case inbox = "Inbox"
    case contributors = "Contributors"
    case connect = "Connect"

    var icon: String {
        switch self {
        case .graph: "point.3.connected.trianglepath.dotted"
        case .clusters: "circle.grid.2x2"
        case .feed: "photo.stack"
        case .sleep: "moon.fill"
        case .inbox: "tray.full"
        case .contributors: "person.2.badge.gearshape"
        case .connect: "cable.connector"
        }
    }
}

/// Linear/Notion-style sidebar sections. Quiet uppercase labels group the flat
/// tab list by mental model without adding any new theme tokens.
private enum SidebarSection: String, CaseIterable {
    case workspace = "Workspace"
    case maintenance = "Maintenance"
    case provenance = "Provenance"
    case setup = "Setup"

    var tabs: [AppTab] {
        switch self {
        case .workspace: [.graph, .clusters, .feed]
        case .maintenance: [.sleep, .inbox]
        case .provenance: [.contributors]
        case .setup: [.connect]
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
                        SidebarRow(
                            tab: tab,
                            isSelected: selectedTab == tab,
                            badgeCount: badgeCount(for: tab)
                        )
                        .onTapGesture {
                            withAnimation(.spring(duration: 0.25)) {
                                selectedTab = tab
                            }
                        }
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
        case .graph, .clusters, .feed, .sleep, .contributors, .connect: 0
        case .inbox: inboxCount
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

            Text(tab.rawValue)
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
