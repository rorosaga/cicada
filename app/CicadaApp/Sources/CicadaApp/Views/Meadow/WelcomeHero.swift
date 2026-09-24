import SwiftUI

/// The Welcome's band (R-IB11): the bundled onboarding hero, `-dark` at dusk
/// and night by the clock (`SceneStore`, reading it here subscribes) and
/// Settings → General → Scene — never the theme (round-4 D4, DESIGN_RULES §9
/// 2026-09-24), filling the band and anchored
/// at the bottom so the meadow shows. No words: the headline lives on the card
/// that rises into the grass, so no text ever sits on paint (R-M6). No drifting
/// sprite — the hero's clouds are painted, and a moving one over them would
/// double them. A bundle that lost the file falls back to the procedural sky,
/// never a blank band.
struct WelcomeHero: View {
    @AppStorage(HeroScenePreference.defaultsKey) private var sceneRaw = HeroScenePreference.automatic.rawValue

    private var scene: CicadaTheme.SkyPhase { HeroScenePreference.stored(sceneRaw).scene(clock: SceneStore.shared.phase) }

    var body: some View {
        GeometryReader { geo in
            if let image = MeadowArt.image(for: .heroDay, mode: MeadowArt.heroMode(for: scene)) {
                Image(nsImage: image)
                    .resizable()
                    .interpolation(.high)
                    .scaledToFill()
                    .frame(width: geo.size.width, height: geo.size.height, alignment: .bottom)
                    .clipped()
            } else {
                MeadowSky()
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
