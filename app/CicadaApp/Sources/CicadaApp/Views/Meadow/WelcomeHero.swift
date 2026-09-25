import SwiftUI

/// The Welcome's painting (R-IB11; C10's `.fullBleed`): the same living meadow as Home's band, in the person's Scene
/// over the clock — never the theme (G144) — with the meadow line at 0.66 of the space so the card rises into the low
/// meadow. No words: the headline lives on the card, so no text ever sits on paint (R-M6, DR-13). Phase B's full-window
/// Welcome keeps this framing.
struct WelcomeHero: View {
    /// R-HO7 — rests while something covers it (onboarding's See how sheet).
    var paused = false
    var body: some View { PaintedScene(.fullBleed, paused: paused) }
}
