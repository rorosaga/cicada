import SwiftUI

/// Round-4 phase B (R-OB1, R-OB20) — the onboarding frame's painting: Welcome's and You're set's full-bleed hero
/// (`WelcomeHero`, the one door to that framing, pinned by `SceneClockTests`), or a working page's pane, crossfading
/// between them on the scene's own curve (R-HO4) as the frame narrows. One component per state, so `PaintedScene`
/// keeps its one clock and its pause rules (R-HO7): `paused` rests it while the See how sheet covers it. Paint only
/// (DR-13) — no word is drawn here.
struct OnboardingPane: View {
    let pane: PaneFraming?
    var paused = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            if let pane {
                PaintedScene(.pane(pane), paused: paused).id(pane).transition(.opacity)
            } else {
                WelcomeHero(paused: paused).transition(.opacity)
            }
        }
        .animation(CicadaMotion.sceneCrossfade(reduceMotion: reduceMotion), value: pane)
        .ignoresSafeArea()   // paint runs under the titlebar; controls never do (R-OB23)
    }
}
