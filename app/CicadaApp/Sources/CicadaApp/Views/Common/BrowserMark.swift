import SwiftUI

/// C9's "real icons": the installed app's own icon (a browser in the inventory is installed by construction), then
/// the bundled mark, then a neutral symbol — bare, never on a tinted tile (DR-52, Track L's precedence).
struct BrowserMark: View {
    let spec: BrowserSpec
    var size: CGFloat = 14

    var body: some View {
        Group {
            if let icon = InstalledAppIcon.image(bundleId: spec.bundleId, size: size) {
                Image(nsImage: icon).resizable().interpolation(.high).scaledToFit()
            } else if let logo = spec.logo, LogoImage.exists(name: logo) {
                LogoImage(name: logo, size: size)
            } else {
                Image(systemName: spec.symbol)
                    .font(CicadaTheme.font(size: size * 0.8, weight: .medium))
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        }
        .frame(width: size, height: size)
        .accessibilityLabel(spec.name)
    }
}
