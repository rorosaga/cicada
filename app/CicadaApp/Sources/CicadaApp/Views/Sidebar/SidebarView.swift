import SwiftUI

enum AppTab: String, CaseIterable {
    case memory = "Memory"
    case nudges = "Nudges"
    case clarifications = "Clarifications"

    var icon: String {
        switch self {
        case .memory: "brain.head.profile"
        case .nudges: "bell.badge"
        case .clarifications: "questionmark.circle"
        }
    }
}

struct SidebarView: View {
    @Binding var selectedTab: AppTab
    var nudgeCount: Int
    var clarificationCount: Int

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            ForEach(AppTab.allCases, id: \.self) { tab in
                SidebarRow(
                    tab: tab,
                    isSelected: selectedTab == tab,
                    badgeCount: badgeCount(for: tab)
                )
                .onTapGesture { selectedTab = tab }
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
        case .memory: 0
        case .nudges: nudgeCount
        case .clarifications: clarificationCount
        }
    }
}

private struct SidebarRow: View {
    let tab: AppTab
    let isSelected: Bool
    let badgeCount: Int

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
                .fill(isSelected ? CicadaTheme.accent.opacity(0.12) : .clear)
        )
        .contentShape(Rectangle())
        .padding(.horizontal, CicadaTheme.spacingSM)
    }
}
