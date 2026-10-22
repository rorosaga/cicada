import SwiftUI

/// G217 — the one adapter every Sources, Inbox and Sleep mark goes through on this branch. Today it draws the existing
/// `LogoImage.platformTile` (the installed app's icon, else the bundled mark, else a symbol, in a ringed tile); once
/// UI-A's `LogoTile` lands, `body` becomes that one call and nothing else moves (ruling 36: one logo tile; a dated
/// departure from DR-52's bare mark, decided by the owner 2026-10-22).
struct SourceLogoTile: View {
    enum Size {
        /// 36 pt tile, 26 pt mark (a row, a detail head).
        case row
        /// 24 pt tile for dense lists and chips.
        case dense

        var points: CGFloat {
            switch self {
            case .row: 36
            case .dense: 24
            }
        }
    }

    /// An `OriginIconography` key.
    let origin: String
    var size: Size = .row
    /// A provider umbrella's logo slug (`GET /providers`, an agent request's `logo`), drawn before the origin's.
    var logo: String? = nil

    /// The bundled file an umbrella slug draws today (the umbrella set is UI-A's; until it lands, OpenAI wears the
    /// ChatGPT mark and Anthropic the Claude one).
    static func bundledName(forLogo slug: String) -> String {
        switch slug {
        case "openai": "chatgpt"
        case "anthropic": "claude"
        case "google": "gemini"
        default: slug
        }
    }

    var body: some View {
        LogoImage.platformTile(name: logo.map(Self.bundledName(forLogo:)) ?? OriginIconography.logoName(for: origin) ?? "",
                               bundleId: OriginIconography.appBundleId(for: origin),
                               size: CicadaTheme.scaled(size.points),
                               systemFallback: OriginIconography.symbol(for: origin))
            .accessibilityHidden(true)
    }
}

/// Status as a dot and one word (ruling 36's connection model; design-refs pattern 4). The dot's colour is a data hue
/// (DR-8): success, warning, or the tertiary ink for Off — never the accent (DR-5).
struct StatusWord: View {
    enum Tone { case on, attention, off }

    let word: String
    let tone: Tone

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(6)) {
            Circle()
                .fill(color)
                .frame(width: CicadaTheme.scaled(7), height: CicadaTheme.scaled(7))
            Text(word)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(1)
        }
        .accessibilityElement(children: .combine)
    }

    private var color: Color {
        switch tone {
        case .on: CicadaTheme.success
        case .attention: CicadaTheme.warning
        case .off: CicadaTheme.textTertiary
        }
    }
}

extension SourceCatalogStatus {
    var tone: StatusWord.Tone {
        switch self {
        case .connected: .on
        case .needsSignIn: .attention
        case .off: .off
        }
    }
}
