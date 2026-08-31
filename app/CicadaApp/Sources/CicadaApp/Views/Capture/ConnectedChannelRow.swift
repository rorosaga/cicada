import SwiftUI

/// One connected capture channel (G62): a 28-pt circular icon, the channel
/// label, the server's own `detail` line, and a trailing ⋯ menu carrying
/// exactly the actions the backend said this channel supports.
///
/// The whole row is a `Button` (opens "Manage…") so VoiceOver and UI automation
/// can reach it; the ⋯ menu is a second, separately-labelled control.
struct ConnectedChannelRow: View {
    let channel: SourceChannel
    /// Receives an action id from `channel.actions`, or `"manage"` when the row
    /// itself is activated.
    let onAction: (String) -> Void

    @State private var isHovered = false

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            Button { onAction("manage") } label: {
                HStack(spacing: CicadaTheme.spacingMD) {
                    Image(systemName: Self.icon(for: channel.id))
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(Self.tint(for: channel.id))
                        .frame(width: 28, height: 28)
                        .background(Circle().fill(Self.tint(for: channel.id).opacity(0.12)))
                        .overlay(Circle().stroke(CicadaTheme.border, lineWidth: 1))

                    VStack(alignment: .leading, spacing: 2) {
                        Text(channel.label)
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .lineLimit(1)
                        if let detail = channel.detail {
                            Text(detail)
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textSecondary)
                                .lineLimit(1)
                        }
                    }
                    Spacer()
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(channel.detail.map { "\(channel.label). \($0)" } ?? channel.label)

            if !channel.actions.isEmpty {
                Menu {
                    ForEach(channel.actions, id: \.self) { action in
                        Button(Self.actionTitle(action, channel: channel)) { onAction(action) }
                    }
                } label: {
                    Image(systemName: "ellipsis")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .frame(width: 24, height: 24)
                }
                .menuStyle(.borderlessButton)
                .menuIndicator(.hidden)
                .frame(width: 24)
                .accessibilityLabel("Actions for \(channel.label)")
            }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .background(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .fill(isHovered ? CicadaTheme.surfaceHover : .clear)
        )
        .onHover { isHovered = $0 }
        .animation(.easeInOut(duration: 0.12), value: isHovered)
    }

    static func actionTitle(_ action: String, channel: SourceChannel) -> String {
        switch action {
        case "poll": "Poll now"
        case "sync": "Sync now"
        case "manage": "Manage…"
        case "import": "Import another file…"
        case "remove": "Remove"
        default: action.capitalized
        }
    }

    /// Icons/tints mirror `OriginPill` so a channel and its origin pill read as
    /// the same thing on the same page.
    static func icon(for id: String) -> String {
        switch id {
        case "rss": "dot.radiowaves.up.forward"
        case "calendar": "calendar"
        case "bookmarks": "globe"
        case "notes": "note.text"
        case "telegram": "paperplane.fill"
        case "chat-export:claude", "chat-export:chatgpt": "bubble.left.and.bubble.right"
        case "files": "link"
        default: "tray"
        }
    }

    static func tint(for id: String) -> Color {
        switch id {
        case "rss": Color(hex: 0xEE802F)
        case "calendar": Color(hex: 0xFF3B30)
        case "bookmarks": Color(hex: 0x4285F4)
        case "notes": Color(hex: 0xFFCC00)
        case "telegram": Color(hex: 0x26A5E4)
        case "chat-export:claude", "chat-export:chatgpt": CicadaTheme.accent
        case "files": Color(hex: 0x8896FF)
        default: CicadaTheme.textSecondary
        }
    }
}
