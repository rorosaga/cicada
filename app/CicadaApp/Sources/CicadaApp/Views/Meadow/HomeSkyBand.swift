import SwiftUI

/// Where Home's band art may sit, as geometry (HomeBandLayoutTests): the
/// headline in the middle half, one cloud in the outer quarter with room for
/// its drift, no cloud at all when the band is too narrow to keep them apart.
enum HomeBandLayout {
    static let bandHeight: CGFloat = 168
    static let cloudWidth: CGFloat = 180
    static let minWidthForCloud: CGFloat = 640
    static let headlineSize: CGFloat = 34
    static let edge: CGFloat = 16

    static func headlineFrame(width: CGFloat, scale: CGFloat) -> CGRect {
        let fraction: CGFloat = width >= minWidthForCloud * scale ? 0.5 : 0.8
        let w = width * fraction - 2 * edge * scale
        let h = 2 * headlineSize * scale * 1.25
        return CGRect(x: (width - w) / 2, y: (bandHeight * scale - h) / 2, width: w, height: h)
    }

    static func cloudFrame(width: CGFloat, scale: CGFloat) -> CGRect? {
        guard width >= minWidthForCloud * scale else { return nil }
        let w = min(cloudWidth * scale, width * 0.25 - edge * scale)
        return CGRect(x: width - w - edge * scale, y: 12 * scale, width: w, height: w / 2)
    }
}

/// Home's header band (design §6.2, R9 §7 amended +1): a procedural sky and one
/// painted cloud. Carries no number and no text of its own — HomeView draws the
/// headline over the gradient at `HomeBandLayout.headlineFrame`.
struct HomeSkyBand: View {
    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .topLeading) {
                MeadowSky()
                if let cloud = HomeBandLayout.cloudFrame(width: geo.size.width, scale: CicadaTheme.uiScale) {
                    DriftingCloud(art: .cloud2, width: cloud.width)
                        .position(x: cloud.midX, y: cloud.midY)
                }
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
