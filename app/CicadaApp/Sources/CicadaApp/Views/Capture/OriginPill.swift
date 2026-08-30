import SwiftUI

// MARK: - Origin pill

/// One capture-origin readout in the Capture page's "where your memory comes
/// from" strip. Pill/capsule styling mirrors `ContributorAvatar`/`ClaimChip`'s
/// provenance pills so provenance reads consistently across the app; icon and
/// brand color mirror `CaptureSourceCatalog` where the origin has a known source.
struct OriginPill: View {
    let origin: OriginStat

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: symbol)
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(color)
            Text(label)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(CicadaTheme.textPrimary)
            Text("\(origin.episodeCount) ep · \(origin.entityCount) ent")
                .font(.system(size: 10, weight: .regular))
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .background(color.opacity(0.12))
        .clipShape(Capsule())
        .overlay(Capsule().stroke(color.opacity(0.3), lineWidth: 1))
        .help(origin.lastSeen.isEmpty ? label : "\(label) · last seen \(origin.lastSeen)")
    }

    private var label: String {
        switch origin.origin {
        case "mcp": "MCP"
        case "chrome-bookmark": "Chrome"
        case "safari-bookmark": "Safari"
        case "telegram": "Telegram"
        case "claude-export": "Claude export"
        case "chatgpt-export": "ChatGPT export"
        case "rss": "RSS"
        case "calendar": "Calendar"
        case "apple-notes": "Apple Notes"
        case "share-sheet": "Share Sheet"
        case "instagram-saved": "Instagram Saved"
        case "youtube-playlist": "YouTube Playlist"
        case "unknown": "Unknown"
        default: origin.origin.capitalized
        }
    }

    private var symbol: String {
        switch origin.origin {
        case "mcp": "bubble.left.and.bubble.right"
        case "chrome-bookmark": "globe"
        case "safari-bookmark": "safari"
        case "telegram": "paperplane.fill"
        case "claude-export", "chatgpt-export": "square.and.arrow.down"
        case "rss": "dot.radiowaves.up.forward"
        case "calendar": "calendar"
        case "apple-notes": "note.text"
        case "share-sheet": "square.and.arrow.up"
        case "instagram-saved": "camera.fill"
        case "youtube-playlist": "play.rectangle.fill"
        case "unknown": "questionmark.circle"
        default: "tray"
        }
    }

    private var color: Color {
        switch origin.origin {
        case "mcp": CicadaTheme.accent
        case "chrome-bookmark": Color(hex: 0x4285F4)
        case "safari-bookmark": Color(hex: 0x00A2E8)
        case "telegram": Color(hex: 0x26A5E4)
        case "rss": Color(hex: 0xEE802F)
        case "calendar": Color(hex: 0xFF3B30)
        case "apple-notes": Color(hex: 0xFFCC00)
        case "share-sheet": Color(hex: 0x8896FF)
        case "instagram-saved": Color(hex: 0xE1306C)
        case "youtube-playlist": Color(hex: 0xFF0000)
        case "unknown": CicadaTheme.textTertiary
        default: CicadaTheme.textSecondary
        }
    }
}
