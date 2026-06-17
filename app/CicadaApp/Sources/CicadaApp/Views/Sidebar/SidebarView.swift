import SwiftUI

enum AppTab: String, CaseIterable {
    case graph = "Graph"
    case clusters = "Clusters"
    case feed = "Feed"
    case sleep = "Sleep"
    case inbox = "Inbox"
    case contributors = "Contributors"

    var icon: String {
        switch self {
        case .graph: "point.3.connected.trianglepath.dotted"
        case .clusters: "circle.grid.2x2"
        case .feed: "photo.stack"
        case .sleep: "moon.fill"
        case .inbox: "tray.full"
        case .contributors: "person.2.badge.gearshape"
        }
    }
}

/// Linear/Notion-style sidebar sections. Quiet uppercase labels group the flat
/// tab list by mental model without adding any new theme tokens.
private enum SidebarSection: String, CaseIterable {
    case workspace = "Workspace"
    case maintenance = "Maintenance"
    case provenance = "Provenance"

    var tabs: [AppTab] {
        switch self {
        case .workspace: [.graph, .clusters, .feed]
        case .maintenance: [.sleep, .inbox]
        case .provenance: [.contributors]
        }
    }
}

struct SidebarView: View {
    @Binding var selectedTab: AppTab
    var inboxCount: Int

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

            Text("Cicada")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .padding(.horizontal, CicadaTheme.spacingLG)
                .padding(.bottom, CicadaTheme.spacingMD)
        }
        .padding(.top, CicadaTheme.spacingXL)
        .frame(minWidth: 180)
        .background(CicadaTheme.background)
    }

    private func badgeCount(for tab: AppTab) -> Int {
        switch tab {
        case .graph, .clusters, .feed, .sleep, .contributors: 0
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
