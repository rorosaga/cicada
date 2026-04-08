import SwiftUI

enum AppTab: String, CaseIterable {
    case memory = "Memory"
    case nudges = "Nudges"
    case clarifications = "Clarifications"
    case upload = "Upload"

    var icon: String {
        switch self {
        case .memory: "brain.head.profile"
        case .nudges: "bell.badge"
        case .clarifications: "questionmark.circle"
        case .upload: "arrow.up.doc"
        }
    }
}

struct SidebarView: View {
    @Binding var selectedTab: AppTab
    var nudgeCount: Int
    var clarificationCount: Int
    @State private var isSleepRunning = false
    @State private var sleepButtonHovered = false

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

            // Manual Sleep trigger
            Divider().background(CicadaTheme.border).padding(.horizontal, CicadaTheme.spacingLG)

            Button {
                triggerSleep()
            } label: {
                HStack(spacing: CicadaTheme.spacingMD) {
                    if isSleepRunning {
                        ProgressView()
                            .controlSize(.small)
                            .frame(width: 16, height: 16)
                    } else {
                        Image(systemName: "moon.fill")
                            .font(.system(size: 14))
                            .foregroundStyle(CicadaTheme.accent)
                    }

                    Text(isSleepRunning ? "Sleeping..." : "Run Sleep Cycle")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(isSleepRunning ? CicadaTheme.textTertiary : CicadaTheme.textSecondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, CicadaTheme.spacingLG)
                .padding(.vertical, CicadaTheme.spacingMD)
                .background(
                    RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                        .fill(sleepButtonHovered ? CicadaTheme.accent.opacity(0.08) : .clear)
                )
                .padding(.horizontal, CicadaTheme.spacingSM)
            }
            .buttonStyle(.plain)
            .disabled(isSleepRunning)
            .onHover { sleepButtonHovered = $0 }
            .animation(.easeInOut(duration: 0.15), value: sleepButtonHovered)

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
        case .upload: 0
        }
    }

    private func triggerSleep() {
        isSleepRunning = true
        // Mock: simulate sleep cycle for 3 seconds
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
            withAnimation(.spring(duration: 0.3)) {
                isSleepRunning = false
            }
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
