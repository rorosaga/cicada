import CoreGraphics
import Foundation

/// The waiting pile's books (2026-10-16, owner pick "A · Stack"): a colour per source KIND, every one an existing
/// palette key (`room-books`, authored in `parts/room-parts.aseprite`, built by `lua/build_books.lua`). Agent
/// conversations are the worm's own book blue; conversations with people (Messages, Telegram) are leaf green.
enum BookKind: String, CaseIterable { case chat, message, page, note, video, other }

func bookKind(for origin: String) -> BookKind {
    switch origin {
    case "imessage", "telegram": .message
    case "mcp", "claude-code", "claude-desktop", "cursor", "codex", "gemini-cli", "claude-export", "chatgpt-export",
         "gemini-export", "claude-web", "chatgpt", "perplexity", "claude-code-remote", "codex-remote", "vscode",
         "remote-app", "grok", "opencode", "hermes", "openclaw": .chat
    case "chrome-bookmark", "safari-bookmark", "safari-tab", "bookmark", "saved-link", "share-sheet", "brave-bookmark",
         "vivaldi-bookmark", "comet-bookmark", "dia-bookmark", "chrome-tab-group", "rss", "instagram-saved", "pinterest",
         "reddit-saved", "reddit", "x-bookmarks", "x-likes", "x", "linkedin-saved": .page
    case "apple-notes", "wispr-flow", "folder": .note
    case "youtube-playlist", "youtube-history", "tiktok-saved", "tiktok-history": .video
    default: .other
    }
}

/// One book as pixels: the sheet's leading cap, its middle column repeated to `width`, its trailing cap. The middle
/// column is the same in every column of the authored frame (`verify_room.py`, `BookArtTests`), so any whole width
/// is the drawing as authored, never a resample.
enum BookArt {
    static let sheetName = "room-books"
    /// The count steps' thicknesses in rows (1, 2–9, 10–49, 50+), one frame each, drawn from the frame's top row.
    static let rows = [7, 9, 11, 13]
    static let sheetWidth = 24
    static let leadingCap = 4
    static let trailingCap = 8
    static var minWidth: Int { leadingCap + trailingCap + 1 }

    static func step(count: Int) -> Int { count <= 1 ? 0 : count < 10 ? 1 : count < 50 ? 2 : 3 }

    private static let lock = NSLock()
    nonisolated(unsafe) private static var cache: [String: CGImage] = [:]

    /// The book `width` cells wide, `rows[step]` tall, one pixel per cell; nil without the sheet. Cached by its inputs
    /// (six kinds × four steps × two lightings × the handful of widths the layout uses).
    static func image(kind: BookKind, step: Int, width: Int, night: Bool,
                      sheet: SpriteSheet? = SpriteSheets.sheet(named: sheetName)) -> CGImage? {
        guard rows.indices.contains(step), width >= minWidth else { return nil }
        let key = "\(kind.rawValue)|\(step)|\(width)|\(night)"
        lock.lock()
        defer { lock.unlock() }
        if let hit = cache[key] { return hit }
        guard let sheet, let clip = sheet.clip(kind.rawValue + (night ? "-night" : "")),
              clip.order.indices.contains(step), let frame = sheet.frameImage(clip.order[step]) else { return nil }
        let h = rows[step]
        guard let lead = frame.cropping(to: CGRect(x: 0, y: 0, width: leadingCap, height: h)),
              let middle = frame.cropping(to: CGRect(x: leadingCap, y: 0, width: 1, height: h)),
              let trail = frame.cropping(to: CGRect(x: sheetWidth - trailingCap, y: 0, width: trailingCap, height: h)),
              let ctx = CGContext(data: nil, width: width, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                                  space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
        ctx.interpolationQuality = .none
        ctx.setShouldAntialias(false)
        ctx.draw(lead, in: CGRect(x: 0, y: 0, width: leadingCap, height: h))
        for x in leadingCap..<(width - trailingCap) { ctx.draw(middle, in: CGRect(x: x, y: 0, width: 1, height: h)) }
        ctx.draw(trail, in: CGRect(x: width - trailingCap, y: 0, width: trailingCap, height: h))
        guard let out = ctx.makeImage() else { return nil }
        cache[key] = out
        return out
    }
}
