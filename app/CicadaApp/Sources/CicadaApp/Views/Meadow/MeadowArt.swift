import AppKit
import SwiftUI

/// Onboarding's split-pane paintings (ART_DIRECTION §4) — the same meadow from five places, one per working page.
/// The raw value is the file's framing id (`pane-<id>-<scene>.jpg`).
enum PaneFraming: String, CaseIterable, Hashable, Sendable {
    case `import`
    case agents
    case whoReads = "who-reads"
    case keepRunning = "keep-running"
    case ready
}

/// The painted Meadow art, by role (G137; round-4 T-Home, docs/design/ART_DIRECTION.md) — every file under
/// `Resources/art/`, each listed with its provenance in `art.manifest.json` and held to its bytes by `ArtAssetTests`.
///
/// **One composition in three lights** (R-HO8). Every painting ships as `<name>-day`, `-afternoon` and `-night`,
/// painted in one hand with the same forms (ART_DIRECTION §3), so a crossfade between two scenes never moves a hill.
/// The round-3 `-dark` sibling retired with its set: its hills sat 11 % higher than the day file's, so a crossfade
/// jumped. A surface with no Scene setting takes `SceneTime.forTheme` — day under light, night under dark.
/// **Every file is authored at 2×** the point size it is drawn at, so `image(for:time:)` sizes the `NSImage` in
/// points and a tiled strip draws at its intended height.
///
/// Lookups go through `Bundle.cicadaResource(_:ext:in:)` with the bare `"art"` directory: `bundle.sh` re-nests the
/// resource bundle, and a spelled-out `Resources/` prefix resolves only under `swift test` (PR #70).
enum MeadowArt: Hashable, CaseIterable {
    case hero
    case cloud1, cloud2, cloud3
    case grassLeft, grassRight, grassEdge
    case pane(PaneFraming)

    static var allCases: [MeadowArt] {
        [.hero, .cloud1, .cloud2, .cloud3, .grassLeft, .grassRight, .grassEdge] + PaneFraming.allCases.map(MeadowArt.pane)
    }

    static let directory = "art"
    static let pixelsPerPoint: CGFloat = 2

    var baseName: String {
        switch self {
        case .hero: "hero"
        case .cloud1: "cloud-1"
        case .cloud2: "cloud-2"
        case .cloud3: "cloud-3"
        case .grassLeft: "grass-left"
        case .grassRight: "grass-right"
        case .grassEdge: "grass-edge"
        case .pane(let framing): "pane-\(framing.rawValue)"
        }
    }

    /// The opaque paintings are JPEG q86 4:4:4 (ART_DIRECTION §6); every cut-out layer needs alpha.
    var fileExtension: String {
        switch self {
        case .hero, .pane: "jpg"
        default: "png"
        }
    }

    static func fileName(for art: MeadowArt, time: SceneTime) -> String { "\(art.baseName)-\(time.rawValue)" }

    /// The scene's painting, falling back to the day one — `ArtAssetTests` guarantees all three exist, so the fallback
    /// only guards a bundle that lost a file (a day painting, never a blank).
    static func url(for art: MeadowArt, time: SceneTime, in bundle: Bundle = .cicadaResources) -> URL? {
        bundle.cicadaResource(fileName(for: art, time: time), ext: art.fileExtension, in: directory)
            ?? bundle.cicadaResource(fileName(for: art, time: .day), ext: art.fileExtension, in: directory)
    }

    @MainActor private static var cache: [String: NSImage] = [:]

    /// Loaded once per painting and sized in points at 2×, so a living scene's 30 fps tick is a dictionary hit,
    /// never a decode.
    @MainActor
    static func image(for art: MeadowArt, time: SceneTime) -> NSImage? {
        let key = fileName(for: art, time: time)
        if let hit = cache[key] { return hit }
        guard let url = url(for: art, time: time), let image = NSImage(contentsOf: url),
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

/// One painting in the theme's scene — day under light, night under dark
/// (ART_DIRECTION §6) — at `.high` interpolation (painterly art tolerates
/// scaling; the pixel bookworm never goes through here). Reading
/// `CicadaTheme.mode` in `body` subscribes the view, so a theme flip swaps in
/// the night painting — the `LogoImage` mechanism.
struct ArtImage: View {
    let art: MeadowArt

    var body: some View {
        if let image = MeadowArt.image(for: art, time: .forTheme(CicadaTheme.mode)) {
            Image(nsImage: image).resizable().interpolation(.high).scaledToFit()
        } else {
            Color.clear
        }
    }
}
