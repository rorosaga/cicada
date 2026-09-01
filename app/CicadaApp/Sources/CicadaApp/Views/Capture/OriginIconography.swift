import SwiftUI

/// The single source of truth for "how does this origin id read as a label
/// / SF Symbol / brand color" — extracted out of `OriginPill` (G106
/// amendment) so the Sleep debt breakdown's per-source grouping can reuse
/// the exact same iconography instead of re-declaring its own switch
/// statements that would inevitably drift from this one.
enum OriginIconography {
    static func label(for origin: String) -> String {
        switch origin {
        // "mcp" is the legacy label, kept byte-for-byte so any existing
        // OriginPill caller (the Activity origins strip) never silently
        // renames — "claude-code" is the newer G9-normalized id for the
        // same source and gets its own, equally legible label.
        case "mcp": "MCP"
        case "claude-code": "Claude Code"
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
        case "pinterest": "Pinterest"
        case "reddit-saved", "reddit": "Reddit"
        case "x-bookmarks", "x": "X"
        case "linkedin-saved": "LinkedIn Saved"
        case "tiktok-saved": "TikTok Saved"
        case "tiktok-history": "TikTok History"
        case "bookmark": "Bookmark"
        case "unknown": "Unknown"
        default: origin.capitalized
        }
    }

    static func symbol(for origin: String) -> String {
        switch origin {
        case "mcp", "claude-code": "bubble.left.and.bubble.right"
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
        case "pinterest": "pin.fill"
        case "reddit-saved", "reddit": "bubble.left.and.text.bubble.right.fill"
        case "x-bookmarks", "x": "x.circle"
        case "linkedin-saved": "briefcase.fill"
        case "tiktok-saved": "music.note"
        case "tiktok-history": "clock.arrow.circlepath"
        case "bookmark": "bookmark.fill"
        case "unknown": "questionmark.circle"
        default: "tray"
        }
    }

    static func color(for origin: String) -> Color {
        switch origin {
        case "mcp", "claude-code": CicadaTheme.accent
        case "chrome-bookmark": Color(hex: 0x4285F4)
        case "safari-bookmark": Color(hex: 0x00A2E8)
        case "telegram": Color(hex: 0x26A5E4)
        case "rss": Color(hex: 0xEE802F)
        case "calendar": Color(hex: 0xFF3B30)
        case "apple-notes": Color(hex: 0xFFCC00)
        case "share-sheet": Color(hex: 0x8896FF)
        case "instagram-saved": Color(hex: 0xE1306C)
        case "youtube-playlist": Color(hex: 0xFF0000)
        case "pinterest": Color(hex: 0xE60023)
        case "reddit-saved", "reddit": Color(hex: 0xFF4500)
        case "x-bookmarks", "x": Color(hex: 0x14171A)
        case "linkedin-saved": Color(hex: 0x0A66C2)
        case "tiktok-saved", "tiktok-history": Color(hex: 0xFE2C55)
        case "unknown": CicadaTheme.textTertiary
        default: CicadaTheme.textSecondary
        }
    }
}
