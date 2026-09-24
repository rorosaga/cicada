import AppKit
import SwiftUI

/// The painted Meadow art, by role (G137, spec R-M6) — every file under
/// `Resources/art/`, each listed with its provenance in `art.manifest.json`
/// and held to its bytes by `ArtAssetTests`.
///
/// **Every painting has a `-dark` sibling**, painted as dusk or night — never
/// the light file dimmed — and the dark theme always gets it — except the
/// hero, which follows the clock (`heroMode(for:)`, round-4 D4) — the way
/// `LogoImage` picks a `-dark` mark (R-L5). **Every file is authored at 2×**
/// the point size it is drawn at, so `image(for:mode:)` sizes the `NSImage`
/// in points and a tiled strip draws at its intended height.
///
/// Lookups go through `Bundle.cicadaResource(_:ext:in:)` with the bare `"art"`
/// directory: `bundle.sh` re-nests the resource bundle, and a spelled-out
/// `Resources/` prefix resolves only under `swift test` (PR #70).
enum MeadowArt: String, CaseIterable {
    case cloud1 = "cloud-1"
    case cloud2 = "cloud-2"
    case cloud3 = "cloud-3"
    case grassLeft = "grass-left"
    case grassRight = "grass-right"
    case grassEdge = "grass-edge"
    /// The onboarding hero — bundled here, drawn by the onboarding track.
    case heroDay = "hero-day"

    static let directory = "art"
    static let darkSuffix = "-dark"
    static let pixelsPerPoint: CGFloat = 2

    /// The hero is opaque and ships as JPEG (plan R-M20); every sprite needs alpha.
    var fileExtension: String { self == .heroDay ? "jpg" : "png" }

    static func fileName(for art: MeadowArt, mode: AppColorScheme) -> String {
        mode == .dark ? art.rawValue + darkSuffix : art.rawValue
    }

    /// Round-4 D4 (R-FA4) — the hero follows the scene, not the theme; every other painting keeps following the theme.
    /// Task 1 interim (round-4 T-Home, R-HO1) — the afternoon paints the day file until the three-scene set lands;
    /// night paints the `-dark` sibling.
    static func heroMode(for scene: SceneTime) -> AppColorScheme { scene == .night ? .dark : .light }

    /// The theme's painting, falling back to the light one — `ArtAssetTests`
    /// guarantees the sibling exists, so the fallback only guards a bundle
    /// that lost a file (a lighter painting, never a blank).
    static func url(for art: MeadowArt, mode: AppColorScheme, in bundle: Bundle = .cicadaResources) -> URL? {
        bundle.cicadaResource(fileName(for: art, mode: mode), ext: art.fileExtension, in: directory)
            ?? bundle.cicadaResource(art.rawValue, ext: art.fileExtension, in: directory)
    }

    @MainActor private static var cache: [String: NSImage] = [:]

    /// Loaded once per painting and sized in points at 2×, so a drifting
    /// cloud's 30 fps tick is a dictionary hit, never a decode.
    @MainActor
    static func image(for art: MeadowArt, mode: AppColorScheme) -> NSImage? {
        let key = fileName(for: art, mode: mode)
        if let hit = cache[key] { return hit }
        guard let url = url(for: art, mode: mode), let image = NSImage(contentsOf: url),
              let rep = image.representations.first else { return nil }
        image.size = NSSize(width: CGFloat(rep.pixelsWide) / pixelsPerPoint,
                            height: CGFloat(rep.pixelsHigh) / pixelsPerPoint)
        cache[key] = image
        return image
    }
}

/// The rules the Meadow views follow, as pure functions (MeadowTests), so a
/// number tuned after a live look is one line, not a hunt (plan R-M22).
enum MeadowRules {
    static let lightCloudOpacity = 0.85
    /// R9 §5.3: the moon cloud at ≤ 40 %.
    static let darkCloudOpacity = 0.4
    /// R9 §7: under Increase Contrast, decoration steps back to ≤ 30 %.
    static let increasedContrastCeiling = 0.3

    static func cloudOpacity(mode: AppColorScheme, contrast: ColorSchemeContrast) -> Double {
        let base = mode == .dark ? darkCloudOpacity : lightCloudOpacity
        return contrast == .increased ? min(base, increasedContrastCeiling) : base
    }

    static func grassOpacity(contrast: ColorSchemeContrast) -> Double {
        contrast == .increased ? increasedContrastCeiling : 1
    }

    /// R-M6 "paused … in inactive windows": a window you are not looking at
    /// (not key) does not spend frames on weather.
    static func isDriftPaused(reduceMotion: Bool, activeState: ControlActiveState) -> Bool {
        reduceMotion || activeState != .key
    }

    /// A slow sine, amplitude capped at `CicadaMotion.ambientMaxAmplitude`
    /// and period clamped into `ambientPeriodRange`; exactly 0 under Reduce
    /// Motion (the terminal frame is "at rest").
    static func driftOffset(at t: TimeInterval, amplitude: CGFloat, period: TimeInterval,
                            reduceMotion: Bool) -> CGFloat {
        guard !reduceMotion else { return 0 }
        let a = min(max(amplitude, 0), CicadaMotion.ambientMaxAmplitude)
        let p = min(max(period, CicadaMotion.ambientPeriodRange.lowerBound), CicadaMotion.ambientPeriodRange.upperBound)
        return a * CGFloat(sin(2 * Double.pi * t / p))
    }
}

/// One painting in the theme's variant, at `.high` interpolation (painterly
/// art tolerates scaling; the pixel bookworm never goes through here).
/// Reading `CicadaTheme.mode` in `body` subscribes the view, so a theme flip
/// swaps in the `-dark` painting — the `LogoImage` mechanism.
struct ArtImage: View {
    let art: MeadowArt

    var body: some View {
        if let image = MeadowArt.image(for: art, mode: CicadaTheme.mode) {
            Image(nsImage: image).resizable().interpolation(.high).scaledToFit()
        } else {
            Color.clear
        }
    }
}
