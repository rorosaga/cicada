import SwiftUI

enum SpineKind: String, CaseIterable { case chat, page, note, video, other }

func spineKind(for origin: String) -> SpineKind {
    switch origin {
    case "mcp", "claude-code", "claude-desktop", "cursor", "codex", "gemini-cli", "claude-export", "chatgpt-export",
         "gemini-export", "claude-web", "chatgpt", "perplexity", "claude-code-remote", "codex-remote", "vscode",
         "remote-app", "grok", "opencode", "hermes", "openclaw", "telegram": .chat
    case "chrome-bookmark", "safari-bookmark", "safari-tab", "bookmark", "saved-link", "share-sheet", "brave-bookmark",
         "vivaldi-bookmark", "comet-bookmark", "dia-bookmark", "chrome-tab-group", "rss", "instagram-saved", "pinterest",
         "reddit-saved", "reddit", "x-bookmarks", "x", "linkedin-saved": .page
    case "apple-notes", "wispr-flow", "folder": .note
    case "youtube-playlist", "tiktok-saved", "tiktok-history": .video
    default: .other
    }
}

/// Fifteen left crops, shared across every spine size. Right marks are cheap backing-store crops, never size-cached.
private enum SpineMasks {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var cache: [String: CGImage] = [:]
    static func crop(_ kind: SpineKind, mask: Int, rows: Int?) -> CGImage? {
        let key = "\(kind.rawValue)|\(mask)"
        lock.lock()
        defer { lock.unlock() }
        if rows == nil, let hit = cache[key] { return hit }
        guard let sheet = SpriteSheets.sheet(named: "room-spines"), let clip = sheet.clip(kind.rawValue),
              clip.order.indices.contains(mask), let frame = sheet.frameImage(clip.order[mask]) else { return nil }
        let rect = rows.map { CGRect(x: 20, y: 1 + (10 - $0) / 2, width: 4, height: $0) }
            ?? CGRect(x: 0, y: 0, width: 20, height: 12)
        let crop = frame.cropping(to: rect)
        if rows == nil { cache[key] = crop }
        return crop
    }
}

/// Pixel masks over the origin's colour. The label sits on the uniform centre (DR-50).
struct SpineTexture: View {
    let kind: SpineKind
    let color: Color
    let cell: CGFloat
    let size: CGSize

    static func usesTexture(cell: CGFloat, size: CGSize) -> Bool { size.width >= 9 * cell && size.height >= 5 * cell }

    var body: some View {
        Group {
            if Self.usesTexture(cell: cell, size: size), SpineMasks.crop(kind, mask: 0, rows: nil) != nil {
                ZStack(alignment: .topTrailing) {
                    ForEach(0..<3) { mask in
                        if let crop = SpineMasks.crop(kind, mask: mask, rows: nil) {
                            Image(decorative: crop, scale: 1 / cell)
                                .resizable(capInsets: EdgeInsets(top: cell, leading: 4 * cell, bottom: cell, trailing: 0), resizingMode: .stretch)
                                .renderingMode(.template).interpolation(.none)
                                .foregroundStyle(tint(mask))
                                .frame(width: size.width, height: size.height)
                        }
                    }
                    let rows = min(10, Int(floor(size.height / cell)) - 2)
                    ForEach(1..<3) { mask in
                        if let crop = SpineMasks.crop(kind, mask: mask, rows: rows) {
                            Image(decorative: crop, scale: 1 / cell)
                                .renderingMode(.template).interpolation(.none)
                                .foregroundStyle(tint(mask))
                                .frame(width: 4 * cell, height: CGFloat(rows) * cell)
                                .offset(y: ((size.height - CGFloat(rows) * cell) / 2).rounded())
                        }
                    }
                }
            } else { Rectangle().fill(color) }
        }
        .frame(width: size.width, height: size.height)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    private func tint(_ mask: Int) -> Color {
        mask == 0 ? color : (mask == 1 ? CicadaTheme.onFill.opacity(0.30) : CicadaTheme.spineShade)
    }
}
