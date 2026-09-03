import SwiftUI

/// One origin, one mark, at any size: bundled PNG → drawn browser glyph →
/// the origin's SF Symbol in its color. The Sleep queue rows and the
/// "Catching up on" block both use it (G105 companion: "where did this
/// come from" answerable at a glance), so an episode reads the same in
/// both places and the same as its tile in the import catalog.
struct OriginMark: View {
    let origin: String
    var size: CGFloat = 14

    var body: some View {
        Group {
            if let name = OriginIconography.logoName(for: origin), LogoImage.exists(name: name) {
                LogoImage(name: name, size: size)
            } else if let glyph = OriginIconography.brandGlyph(for: origin) {
                switch glyph {
                case .safari: SafariGlyph(size: size)
                case .chrome: ChromeGlyph(size: size)
                }
            } else {
                Image(systemName: OriginIconography.symbol(for: origin))
                    .font(.system(size: size * 0.8, weight: .medium))
                    .foregroundStyle(OriginIconography.color(for: origin))
            }
        }
        .frame(width: size, height: size)
        .accessibilityLabel(OriginIconography.label(for: origin))
    }
}
