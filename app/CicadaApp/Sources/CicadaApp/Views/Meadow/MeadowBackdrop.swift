import SwiftUI

// ART NEVER GOES ON DATA (G137, round-3 spec Decision 6, R9 §7). Everything
// in this file is ambient: it may sit behind onboarding, an empty state, a
// non-data page header or an About panel — and NEVER on the graph canvas, a
// list, a grid, a table, a diff, a form, or anything that carries a number.
// Text never sits directly on paint: put it on a `surface` card, or on
// `.liquidGlass(.overImagery, in:)`. Art encodes no quantity (a sunnier
// meadow never means "more memories" — G125's rule). `MeadowPlacementLintTests`
// keeps the allowlist of files that may name these views.

/// A procedural sky (R-M2): zero bytes, so night costs nothing. A `nil`
/// phase follows the theme, read in `body` so a flip repaints it.
struct MeadowSky: View {
    var phase: CicadaTheme.SkyPhase? = nil

    var body: some View {
        LinearGradient(colors: CicadaTheme.skyGradient(phase ?? .current), startPoint: .top, endPoint: .bottom)
            .accessibilityHidden(true)
    }
}

/// One painted cloud drifting a few points side to side (R-M6): ≤ 8 pt, a
/// 60–120 s period, ≤ 30 fps, still under Reduce Motion and whenever the
/// window is not key. Decorative — hidden from VoiceOver, never hit-tested.
struct DriftingCloud: View {
    var art: MeadowArt = .cloud1
    let width: CGFloat
    var amplitude: CGFloat = CicadaMotion.ambientMaxAmplitude
    var period: TimeInterval = CicadaMotion.ambientDefaultPeriod

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.controlActiveState) private var activeState
    @Environment(\.colorSchemeContrast) private var contrast

    var body: some View {
        let paused = MeadowRules.isDriftPaused(reduceMotion: reduceMotion, activeState: activeState)
        TimelineView(.animation(minimumInterval: CicadaMotion.ambientFrameInterval, paused: paused)) { context in
            ArtImage(art: art)
                .frame(width: width)
                .offset(x: MeadowRules.driftOffset(at: context.date.timeIntervalSinceReferenceDate,
                                                   amplitude: amplitude, period: period, reduceMotion: reduceMotion))
        }
        .opacity(MeadowRules.cloudOpacity(mode: CicadaTheme.mode, contrast: contrast))
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

/// Grass and dandelions in the two bottom corners. Grass never moves (R-M6).
/// `height` is in points at `uiScale == 1`; the view scales it.
struct GrassCorners: View {
    var height: CGFloat = 140
    @Environment(\.colorSchemeContrast) private var contrast

    var body: some View {
        HStack(alignment: .bottom, spacing: 0) {
            ArtImage(art: .grassLeft).frame(height: CicadaTheme.scaled(height))
            Spacer(minLength: 0)
            ArtImage(art: .grassRight).frame(height: CicadaTheme.scaled(height))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
        .opacity(MeadowRules.grassOpacity(contrast: contrast))
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

/// A strip of grass tiled along a bottom edge, at the painting's own 2× point
/// height (a tile is drawn at native size, so it is never stretched).
struct GrassEdge: View {
    @Environment(\.colorSchemeContrast) private var contrast

    var body: some View {
        if let image = MeadowArt.image(for: .grassEdge, mode: CicadaTheme.mode) {
            Image(nsImage: image)
                .resizable(capInsets: EdgeInsets(), resizingMode: .tile)
                .frame(height: image.size.height)
                .frame(maxWidth: .infinity)
                .opacity(MeadowRules.grassOpacity(contrast: contrast))
                .allowsHitTesting(false)
                .accessibilityHidden(true)
        }
    }
}

/// The composed backdrop a non-data screen drops behind itself.
struct MeadowBackdrop: View {
    enum Style: Equatable {
        /// Grass in the two bottom corners, nothing else — an empty state.
        case corners
        /// Sky, two drifting clouds, grass along the bottom — onboarding, a
        /// header band, an About panel. `nil` phase follows the theme.
        case meadow(phase: CicadaTheme.SkyPhase? = nil)
    }

    let style: Style

    var body: some View {
        Group {
            switch style {
            case .corners:
                GrassCorners()
            case let .meadow(phase):
                ZStack(alignment: .bottom) {
                    MeadowSky(phase: phase)
                    VStack {
                        HStack(alignment: .top) {
                            DriftingCloud(art: .cloud1, width: CicadaTheme.scaled(220))
                                .padding(.leading, CicadaTheme.spacingXXL)
                            Spacer()
                            DriftingCloud(art: .cloud3, width: CicadaTheme.scaled(150), period: 110)
                                .padding(.trailing, CicadaTheme.spacingXXL)
                        }
                        .padding(.top, CicadaTheme.spacingXL)
                        Spacer()
                    }
                    GrassEdge()
                }
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
