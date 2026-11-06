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

    /// ROR-118 round 2 — Claude Code draws the Claude mark itself: the terminal badge on its own asset read as noise at
    /// 26 pt and made the two Claude rows look unlike each other.
    private var slug: String? {
        if let logo { return logo }
        return origin == "claude-code" || origin == "mcp" ? "claude" : OriginIconography.logoName(for: origin)
    }

    private var hasMark: Bool {
        if let bundle = OriginIconography.appBundleId(for: origin), InstalledAppIcon.image(bundleId: bundle, size: 18) != nil {
            return true
        }
        return slug.map { LogoImage.exists(name: $0) } ?? false
    }

    private var tile: CGFloat { LogoTile.tileSide(size == .row ? .regular : .dense) }

    var body: some View {
        // G217 — UI-A's one `LogoTile`: the installed app's icon, else the umbrella's bundled mark. A source with no
        // mark of its own (files, folders, exports) draws its glyph in the primary ink, heavier, so it sits beside the
        // full-colour marks instead of fading under them (ROR-118 round 2).
        if hasMark {
            LogoTile(logo: slug, bundleId: OriginIconography.appBundleId(for: origin),
                     density: size == .row ? .regular : .dense, systemFallback: OriginIconography.symbol(for: origin))
        } else {
            ZStack {
                CicadaTheme.shape(tile * 0.25).fill(CicadaTheme.surfaceElevated)
                Image(systemName: OriginIconography.symbol(for: origin))
                    .font(CicadaTheme.font(size: tile * 0.46, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
            }
            .frame(width: tile, height: tile)
            .ringed(in: CicadaTheme.shape(tile * 0.25))
            .accessibilityHidden(true)
        }
    }
}

/// Status as a dot and one word (ruling 36's connection model; design-refs pattern 4). The dot's colour is a data hue
/// (DR-8): success, warning, or the tertiary ink for Off — never the accent (DR-5).
struct StatusWord: View {
    /// `browser` (ROR-114): the info hue for a source the person's own agent reads in their browser, told apart from
    /// a green connection.
    enum Tone { case on, attention, off, browser }

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
        case .browser: CicadaTheme.info
        }
    }
}

extension SourceCatalogStatus {
    var tone: StatusWord.Tone {
        switch self {
        case .connected: .on
        case .needsSignIn: .attention
        // Grey, not amber: nothing is broken and nothing is read yet; the words say what it waits for.
        case .off, .waitingForAgent: .off
        }
    }
}
