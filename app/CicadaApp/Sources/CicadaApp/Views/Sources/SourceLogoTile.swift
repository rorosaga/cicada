import SwiftUI

/// G217 — the one adapter every Sources and Inbox mark goes through: an origin key (or an umbrella's logo slug) in,
/// UI-A's `LogoTile` out (ruling 36: one logo tile, every mark the same size and style).
struct SourceLogoTile: View {
    enum Size {
        /// 36 pt tile, 26 pt mark (a row, a detail head).
        case row
        /// 24 pt tile for dense lists and chips.
        case dense

    }

    /// An `OriginIconography` key.
    let origin: String
    var size: Size = .row
    /// A provider umbrella's logo slug (`GET /providers`, an agent request's `logo`), drawn before the origin's.
    var logo: String? = nil

    var body: some View {
        // G217 — UI-A's one `LogoTile` (cherry-picked from feat/ui-settings-agents): the installed app's icon, else the
        // umbrella's bundled mark, else a symbol, 26 pt in a 36 pt ringed tile (dense: 18 in 24).
        LogoTile(logo: logo ?? OriginIconography.logoName(for: origin),
                 bundleId: OriginIconography.appBundleId(for: origin),
                 density: size == .row ? .regular : .dense,
                 systemFallback: OriginIconography.symbol(for: origin))
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
