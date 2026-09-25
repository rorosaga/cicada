import SwiftUI

/// One origin, one mark, at any size: the installed app's icon → a bundled
/// PNG → the origin's SF Symbol in its colour (R-L1). The Sleep queue rows,
/// the study desk, the consolidation history and the Sources grid all use it,
/// so an episode reads the same everywhere and the same as its tile in the
/// import catalog.
///
/// The drawn-glyph rung that used to sit between the PNG and the symbol is
/// gone: `ChromeGlyph` was wrong on four independent axes (pre-2015 palette,
/// ~90° rotation, an undersized centre disc, flat fills instead of gradients)
/// and `SafariGlyph` was Apple's compass tinted an invented blue. A
/// wrong-coloured mark that appears only when an asset is missing looks like a
/// logo and isn't — worse than the honest SF Symbol.
struct OriginMark: View {
    let origin: String
    var size: CGFloat = 14

    var body: some View {
        Group {
            if let bundleId = OriginIconography.appBundleId(for: origin),
               let icon = InstalledAppIcon.image(bundleId: bundleId, size: size) {
                Image(nsImage: icon).resizable().interpolation(.high).scaledToFit()
            } else if let name = OriginIconography.logoName(for: origin), LogoImage.exists(name: name) {
                LogoImage(name: name, size: size)
            } else {
                Image(systemName: OriginIconography.symbol(for: origin))
                    .font(CicadaTheme.font(size: size * 0.8, weight: .medium))
                    .foregroundStyle(OriginIconography.color(for: origin))
            }
        }
        .frame(width: size, height: size)
        .accessibilityLabel(OriginIconography.label(for: origin))
    }
}
