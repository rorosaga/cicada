import SwiftUI

struct NudgeCardView: View {
    let nudge: Nudge
    let onResolve: () -> Void
    @State private var isExpanded = false
    @State private var isHovered = false
    @State private var clarificationText = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Collapsed header — entire area is tappable
            HStack(spacing: CicadaTheme.spacingMD) {
                Image(systemName: nudge.type.icon)
                    .font(.system(size: 16))
                    .foregroundStyle(Color(hex: nudge.type.color))
                    .frame(width: 24)

                VStack(alignment: .leading, spacing: 2) {
                    Text(nudge.entityName)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)

                    Text(nudge.shortDescription)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .lineLimit(1)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .rotationEffect(.degrees(isExpanded ? 90 : 0))
                    .animation(.spring(duration: 0.2), value: isExpanded)
            }
            .padding(CicadaTheme.spacingLG)
            .contentShape(Rectangle())
            .onTapGesture {
                withAnimation(.spring(duration: 0.3, bounce: 0.15)) {
                    isExpanded.toggle()
                }
            }

            if isExpanded {
                Divider().background(CicadaTheme.border)

                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    Text(nudge.fullContext)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)

                    actionButtons
                }
                .padding(CicadaTheme.spacingLG)
                .transition(.asymmetric(
                    insertion: .opacity.combined(with: .scale(scale: 0.95, anchor: .top)).combined(with: .move(edge: .top)),
                    removal: .opacity.combined(with: .scale(scale: 0.95, anchor: .top))
                ))
            }
        }
        .glassCard()
        .scaleEffect(isHovered ? 1.01 : 1.0)
        .animation(.spring(duration: 0.2), value: isHovered)
        .onHover { isHovered = $0 }
    }

    @ViewBuilder
    private var actionButtons: some View {
        switch nudge.type {
        case .decay:
            HStack(spacing: CicadaTheme.spacingSM) {
                ActionButton(title: "Still Active", icon: "checkmark", color: 0x22C55E, action: onResolve)
                ActionButton(title: "Archive", icon: "archivebox", color: 0x6B7280, action: onResolve)
                ActionButton(title: "Remind Later", icon: "clock", color: 0xF59E0B, action: onResolve)
            }

        case .conflict:
            VStack(spacing: CicadaTheme.spacingSM) {
                if let options = nudge.options {
                    ForEach(options, id: \.self) { option in
                        ActionButton(title: option, icon: "arrow.right.circle", color: 0x7C8FFF, action: onResolve, fullWidth: true)
                    }
                }
            }

        case .clarification:
            VStack(spacing: CicadaTheme.spacingSM) {
                TextField("Type your answer...", text: $clarificationText)
                    .textFieldStyle(.plain)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .padding(CicadaTheme.spacingMD)
                    .background(CicadaTheme.surface)
                    .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
                    .overlay(
                        RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                            .stroke(CicadaTheme.border, lineWidth: 1)
                    )

                HStack {
                    Spacer()
                    ActionButton(title: "Submit", icon: "paperplane", color: 0x22C55E, action: onResolve)
                }
            }
        }
    }
}

struct ActionButton: View {
    let title: String
    let icon: String
    let color: UInt32
    let action: () -> Void
    var fullWidth: Bool = false
    @State private var isHovered = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingXS) {
                Image(systemName: icon)
                    .font(.system(size: 11))
                Text(title)
                    .font(.system(size: 12, weight: .medium))
            }
            .foregroundStyle(Color(hex: color))
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingSM)
            .frame(maxWidth: fullWidth ? .infinity : nil)
            .background(Color(hex: color).opacity(isHovered ? 0.2 : 0.12))
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
            .scaleEffect(isHovered ? 1.03 : 1.0)
        }
        .buttonStyle(.plain)
        .onHover { isHovered = $0 }
        .animation(.spring(duration: 0.15), value: isHovered)
    }
}
