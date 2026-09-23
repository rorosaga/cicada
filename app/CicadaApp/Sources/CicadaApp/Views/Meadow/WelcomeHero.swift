import SwiftUI

/// The Welcome's band (R-IB11): the bundled onboarding hero, `-dark` in dark
/// mode (`MeadowArt.image` picks it; reading `CicadaTheme.mode` here subscribes
/// the view, so a theme flip swaps the painting), filling the band and anchored
/// at the bottom so the meadow shows. No words: the headline lives on the card
/// that rises into the grass, so no text ever sits on paint (R-M6). No drifting
/// sprite — the hero's clouds are painted, and a moving one over them would
/// double them. A bundle that lost the file falls back to the procedural sky,
/// never a blank band.
struct WelcomeHero: View {
    var body: some View {
        GeometryReader { geo in
            if let image = MeadowArt.image(for: .heroDay, mode: CicadaTheme.mode) {
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
