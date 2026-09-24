import SwiftUI

/// Round 4, owner addendum 2 (R-AG8): Claude Code's mark is the official Claude mark with a small `>_` badge the
/// app draws — chosen over a drawn mascot (Anthropic publishes none) and over a Cicada-original glyph. Claude (the
/// app and claude.ai) keeps the plain mark, so the two never read as the same thing (decision 4: "never the
/// Anthropic asterisk twice"). The mark file is never edited or recoloured (DR-52); the badge is a separate glyph
/// on its own plate, composed in `LogoImage`, the one place every bundled mark is drawn — so every caller keeps
/// passing the logical name it passes today.
///
/// The two byte-identical legacy rasters `claude-code.png` and `claude-desktop.png` are deleted: once the logical
/// names resolve to `claude.png` here, they are unlicensed dead bytes in every shipped app.
enum BrandMark {
    enum Badge: Equatable { case terminal }

    struct Composition: Equatable {
        /// The bundled file (without `.png`) the mark is drawn from.
        let file: String
        /// The app-drawn glyph over its bottom-trailing corner, if any.
        let badge: Badge?
    }

    static func composition(for name: String) -> Composition {
        switch name {
        case "claude-code": Composition(file: "claude", badge: .terminal)
        case "claude-desktop": Composition(file: "claude", badge: nil)
        default: Composition(file: name, badge: nil)
        }
    }

    /// Half the mark, never under 7 pt: a 12 pt row mark keeps a badge you can still see.
    static func badgeSide(for size: CGFloat) -> CGFloat { max(size * 0.5, 7) }
}

/// The `>_` badge: SF Symbol `terminal.fill` in `textPrimary` on a `bgMenu` plate with the resting ring — a
/// floating-surface token, so it reads on every card the mark sits on in either theme (DR-52, R-AG8).
struct MarkBadgeView: View {
    let side: CGFloat

    var body: some View {
        Image(systemName: "terminal.fill")
            .resizable()
            .scaledToFit()
            .foregroundStyle(CicadaTheme.textPrimary)
            .padding(side * 0.16)
            .frame(width: side, height: side)
            .background(CicadaTheme.shape(side * 0.28).fill(CicadaTheme.bgMenu))
            .ringed(in: CicadaTheme.shape(side * 0.28))
            .accessibilityHidden(true)
    }
}
