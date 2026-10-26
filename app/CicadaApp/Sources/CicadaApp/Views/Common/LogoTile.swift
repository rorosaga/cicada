import SwiftUI

/// G217 (owner 2026-10-22: "all logos the same size and style"): the one tile a third-party mark sits in wherever a
/// connection is listed — Settings → Intelligence, the Agents page, Devices, You's profiles, and (UI-B) Sources.
///
/// One size per density, never a per-call number: `.regular` is a 26 pt mark in a 36 pt tile, `.dense` an 18 pt mark
/// in a 24 pt tile for long lists. The tile is the neutral elevated surface with the resting 1 pt ring (DR-9, never a
/// tint and never a shadow), its radius concentric with the mark's clip (DR-12), and every size scales with `uiScale`
/// (DR-70). The mark itself is never altered (DR-52): it is drawn as the vendor published it, clipped to the tile's own
/// curvature so a vendor that publishes a tiled app icon (Grok, OpenCode, Amp …) and one that publishes a bare glyph
/// (Claude, Gemini …) read as one family.
///
/// The lookup order is DR-52's: the app installed on this Mac (`bundleId` — Apple's apps are never bundled, R-L3),
/// then the bundled mark (`logo`, a slug in the shared set, resolved through `BrandMark` so `codex` draws OpenAI's
/// mark), then a monogram of `name` for an agent the set has no mark for (CLAUDE.md's picture precedence ends there),
/// or `systemFallback` when the caller named a glyph.
struct LogoTile: View {
    enum Density { case regular, dense }

    let logo: String?
    var name: String = ""
    var bundleId: String? = nil
    var density: Density = .regular
    /// The glyph when there is no mark. Left at its default, a named row draws its monogram instead; a caller that
    /// names a glyph (a device's laptop, a key, a link) gets the glyph.
    var systemFallback: String = LogoTile.monogramFallback
    static let monogramFallback = "app"

    static func tileSide(_ density: Density) -> CGFloat {
        CicadaTheme.scaled(density == .regular ? 36 : 24)
    }

    static func markSide(_ density: Density) -> CGFloat {
        CicadaTheme.scaled(density == .regular ? 26 : 18)
    }

    private var tile: CGFloat { Self.tileSide(density) }
    private var mark: CGFloat { Self.markSide(density) }
    private var radius: CGFloat { tile * 0.25 }

    var body: some View {
        ZStack {
            CicadaTheme.shape(radius).fill(CicadaTheme.surfaceElevated)
            content
        }
        .frame(width: tile, height: tile)
        .ringed(in: CicadaTheme.shape(radius))
        .accessibilityHidden(true)
    }

    @ViewBuilder
    private var content: some View {
        if let bundleId, let icon = InstalledAppIcon.image(bundleId: bundleId, size: mark) {
            Image(nsImage: icon).resizable().interpolation(.high).scaledToFit()
                .frame(width: mark, height: mark)
        } else if let logo, LogoImage.exists(name: logo) {
            LogoImage(name: logo, size: mark)
                .clipShape(CicadaTheme.shape(radius * (mark / tile)))
        } else if !name.isEmpty, systemFallback == Self.monogramFallback {
            Text(LogoImage.monogram(for: name))
                .font(CicadaTheme.font(size: mark * 0.5, weight: .semibold))
                .foregroundStyle(CicadaTheme.textSecondary)
                .minimumScaleFactor(0.6)
                .lineLimit(1)
        } else {
            Image(systemName: systemFallback)
                .font(CicadaTheme.font(size: mark * 0.62, weight: .regular))
                .foregroundStyle(CicadaTheme.textSecondary)
        }
    }
}

/// The marks in the shared set (`app/assets/logo-set/manifest.json`, G217) that no origin, channel or agent pill
/// claims yet: the provider table's umbrellas (`GET /providers` names them by slug, drawn by the Agents page and
/// Settings → Intelligence) and the source marks the Sources page (UI-B) and You's profiles draw. `LogoAssetTests`
/// reads this list so an orphaned file still fails.
enum LogoSet {
    static let umbrellaMarks: [String] = [
        "claude", "openai", "gemini", "grok", "muse", "cursor", "opencode", "hermes", "openclaw", "copilot", "zed",
        "devin", "warp", "amp", "instinct", "openrouter", "fireworks", "deepinfra", "together", "groq", "mistral",
    ]
    static let sourceMarks: [String] = [
        "x", "instagram", "youtube", "linkedin", "reddit", "tiktok", "github", "scholar", "telegram", "whatsapp",
        "spotify", "pinterest", "chrome", "firefox", "arc", "brave", "rss", "gmail", "google-calendar", "wispr",
        "notion", "readwise", "raindrop", "tailscale",
    ]
    static var all: [String] { umbrellaMarks + sourceMarks }
}
