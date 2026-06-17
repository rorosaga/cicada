import SwiftUI

enum AppTab: String, CaseIterable {
    case memory = "Memory"
    case topics = "Topics"
    case sleep = "Sleep"
    case inbox = "Inbox"
    case contributors = "Contributors"

    var icon: String {
        switch self {
        case .memory: "brain.head.profile"
        case .topics: "list.bullet"
        case .sleep: "moon.fill"
        case .inbox: "tray.full"
        case .contributors: "person.2.badge.gearshape"
        }
    }
}

struct SidebarView: View {
    @Binding var selectedTab: AppTab
    var inboxCount: Int

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            ForEach(AppTab.allCases, id: \.self) { tab in
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
        case .memory, .topics, .sleep, .contributors: 0
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
