import SwiftUI

/// Where Home's painting sits in its band (R-HS2), as pure geometry (`HomeBandLayoutTests`).
enum HomeBandLayout {
    /// The D-Home mock's band.
    static let bandHeight: CGFloat = 120
    /// `object-position: center 63%` — the painting's meadow line, not its empty sky.
    static let focusY: CGFloat = 0.63
    /// `mask-image: linear-gradient(to bottom, #000 40%, transparent 100%)` — the painting fades
    /// into `bgBase`, so the headline row below it sits on the window, never on paint (DR-50).
    static let fadeStart: CGFloat = 0.4

    /// How far to move the filled painting, translated from the mock's CSS: `object-position:
    /// center 63%` puts the painting's 63 % line on the band's 63 % line, so the centred painting
    /// (`.scaledToFill()` centres it) moves by `(focusY − 0.5)` of its overflow. That fraction is
    /// under a half, so the band can never show past the painting's edge — no clamp is needed.
    /// This is the one number that turns "centre" into "centre 63 %".
    static func imageOffsetY(imageSize: CGSize, bandSize: CGSize) -> CGFloat {
        guard imageSize.width > 0, imageSize.height > 0, bandSize.width > 0, bandSize.height > 0 else { return 0 }
        let fill = max(bandSize.width / imageSize.width, bandSize.height / imageSize.height)
        let overflow = max(0, imageSize.height * fill - bandSize.height)
        return -overflow * (focusY - 0.5)
    }
}

/// Home's band (DS-3b, D-Home; DR-13): the bundled onboarding hero — `-dark` at dusk and night by
/// the clock (`SceneStore`, reading it here subscribes) and Settings → General → Scene — never the
/// theme (round-4 D4, DESIGN_RULES §9 2026-09-24) — filled into 120 pt
/// with its meadow in view and faded into `bgBase` below. **Paint only:** no word and no number
/// sits on it (DR-13, DR-50); Home's headline is the next row down. No drifting cloud — the
/// hero's clouds are painted, and a moving one over them would double them (`WelcomeHero`'s
/// reason). Under Increase Contrast it steps back like every Meadow decoration (R9 §7). A bundle
/// that lost the file draws nothing, and the band is just the window.
///
/// It replaced the procedural sky band (one cloud under a two-line headline drawn over it).
struct HomeHeroBand: View {
    @Environment(\.colorSchemeContrast) private var contrast
    @AppStorage(HeroScenePreference.defaultsKey) private var sceneRaw = HeroScenePreference.automatic.rawValue

    private var scene: CicadaTheme.SkyPhase { HeroScenePreference.stored(sceneRaw).scene(clock: SceneStore.shared.phase) }

    var body: some View {
        GeometryReader { geo in
            if let image = MeadowArt.image(for: .heroDay, mode: MeadowArt.heroMode(for: scene)) {
                Image(nsImage: image)
                    .resizable()
                    .interpolation(.high)
                    .scaledToFill()
                    .frame(width: geo.size.width, height: geo.size.height)
                    .offset(y: HomeBandLayout.imageOffsetY(imageSize: image.size, bandSize: geo.size))
                    .frame(width: geo.size.width, height: geo.size.height)
                    .clipped()
                    .mask(LinearGradient(stops: [.init(color: .black, location: HomeBandLayout.fadeStart),
                                                 .init(color: .clear, location: 1)],
                                         startPoint: .top, endPoint: .bottom))
                    .opacity(contrast == .increased ? MeadowRules.increasedContrastCeiling : 1)
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
