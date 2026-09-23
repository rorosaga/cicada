import SwiftUI

/// Track Z Z10 (spec decision 16, Z-B16) — the optional wash across the top of
/// the Sleep page that follows the window's weather. State, never quantity
/// (R-Z1): its only input is the weather, which is the mood alone (R-Z11), and
/// its text twin is the window's legend. It is a procedural wash of Meadow's
/// sky tokens — not painted art — fading to clear before the room card, so
/// it never sits behind a number, and nothing in it moves but the crossfade.
enum SkyBand {
    /// THE switch (the brief: "behind a single constant"). Decided 2026-09-23
    /// from the composites: OFF — against the no-band control, the light-mode
    /// night and dusk bands read as a neutral grey haze pressing on the title
    /// (a smudge, not a sky), the dark night band is invisible and dark day a
    /// lighter slate strip, while only light day read as a tint; measured
    /// tint / title ratios (: 1) light day 1.04 / 14.8, dusk 1.26 / 12.2,
    /// night 1.29 / 11.9, dark day 1.29 / 12.4, dusk 1.02 / 15.7, night
    /// 1.00 / 16.0 — every gate passed, so the eye decided (TODO ruling 10,
    /// the G125 row). Revisit by flipping this and re-running
    /// `CICADA_WRITE_COMPOSITES=1 swift test --filter SkyBandTests`.
    static let ships = false
    /// Points at uiScale 1: the title's band, clear before the room card
    /// starts (≥ 24 + 28 + 16 = 68 pt down, pinned by `SkyBandTests`).
    static let height: CGFloat = 64
    /// "A tint, not a block": the band's top, composited, against the page.
    static let maxTintRatio: Double = 1.35
    /// Text over the band (the page title) stays comfortably legible.
    static let minTitleContrast: Double = 7

    /// Only a sky the window agrees with: night while a cycle runs, dusk at
    /// dawn, day for clear and fair. Overcast, storm and curtains draw no band
    /// — a grey wash would be the "dirt" the owner's §16 question names, and
    /// the window and the sentence already say those states.
    static func phase(for weather: WindowWeather) -> CicadaTheme.SkyPhase? {
        switch weather {
        case .night: .night
        case .dawn: .dusk
        case .clear, .fair: .day
        case .overcast, .storm, .curtains: nil
        }
    }

    /// The sky's top stop at full strength; the view fades it to clear.
    static func top(_ phase: CicadaTheme.SkyPhase) -> Color { CicadaTheme.skyGradient(phase)[0] }

    /// Hidden under Increase Contrast (§11) and whenever the switch is off.
    static func isDrawn(ships: Bool = SkyBand.ships, contrast: ColorSchemeContrast) -> Bool {
        ships && contrast != .increased
    }
}

/// The band itself: the weather's sky at `skyBandOpacity`, fading to clear,
/// crossfading when the weather changes (a jump under Reduce Motion).
struct SleepSkyBand: View {
    let weather: WindowWeather

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let phase = SkyBand.phase(for: weather)
        ZStack {
            if let phase {
                LinearGradient(colors: [SkyBand.top(phase).opacity(CicadaTheme.skyBandOpacity), .clear],
                               startPoint: .top, endPoint: .bottom)
                    .id(phase)
                    .transition(.opacity)
            }
        }
        .animation(SleepMotion.weather(reduceMotion: reduceMotion), value: phase)
        .frame(height: CicadaTheme.scaled(SkyBand.height))
        .frame(maxWidth: .infinity)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
