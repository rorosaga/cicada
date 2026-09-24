import CoreGraphics
import SwiftUI

/// C10 (round-4 phase A contract) — how one painting is framed. Home's band, the Welcome and onboarding's split pane
/// draw the SAME `PaintedScene`; only the crop and the layers differ, so phase B's pages build on this and never on a
/// second painting view (R-HO2).
enum SceneFraming: Hashable, Sendable {
    /// Home's band (F-09): `band` is its height in points at 1× (`PaintedScene` scales it and owns the fade).
    case hero(band: CGFloat)
    /// The Welcome (F-01): the hero fills the space.
    case fullBleed
    /// An onboarding page's painting (F-02 … F-07).
    case pane(PaneFraming)

    var plate: MeadowArt {
        switch self {
        case .pane(let f): .pane(f)
        case .hero, .fullBleed: .hero
        }
    }

    var composition: SceneComposition {
        switch self {
        case .pane(let f): .pane(f)
        case .hero, .fullBleed: .hero
        }
    }

    /// Only the hero has cut-out grass corners; the panes carry no sway layers (ART_DIRECTION §4).
    var hasGrassLayers: Bool { composition == .hero }
}

/// The painting a framing crops: the hero (Home and the Welcome share it) or one pane.
enum SceneComposition: Hashable, Sendable, CaseIterable {
    case hero
    case pane(PaneFraming)

    static var allCases: [SceneComposition] { [.hero] + PaneFraming.allCases.map(SceneComposition.pane) }

    /// Width over height (ART_DIRECTION §3: 16:10; §4: 0.72).
    var aspect: CGFloat { self == .hero ? 1.6 : 0.72 }
}

/// Where a painting and its layers land, as pure geometry (`PaintedSceneTests`).
enum SceneGeometry {
    /// ART_DIRECTION §3 — the meadow line of every hero scene.
    static let heroHorizon: CGFloat = 0.66
    /// §3 — the distant hills' tops; a cloud in Home's band never reaches them (R-HO10).
    static let hillsTop: CGFloat = 0.60
    /// §3 — "the horizon sits at two thirds of the band's height".
    static let bandHorizon: CGFloat = 2.0 / 3.0
    /// R-HO6 — the band fades into the window from 72 % down: rationale-F's 58 % would dim the meadow line at 67 %.
    static let bandFadeStart: CGFloat = 0.72

    /// §4 — each pane's focal point.
    static func focus(_ f: PaneFraming) -> CGPoint {
        switch f {
        case .import: CGPoint(x: 0.42, y: 0.62)
        case .agents: CGPoint(x: 0.45, y: 0.40)
        case .whoReads: CGPoint(x: 0.45, y: 0.50)
        case .keepRunning: CGPoint(x: 0.55, y: 0.35)
        case .ready: CGPoint(x: 0.45, y: 0.55)
        }
    }

    /// §4 — what must survive a crop from aspect 0.60 to 0.90.
    static func keepBox(_ f: PaneFraming) -> CGRect {
        switch f {
        case .import: CGRect(x: 0.15, y: 0.30, width: 0.65, height: 0.65)
        case .agents: CGRect(x: 0.10, y: 0.10, width: 0.75, height: 0.85)
        case .whoReads: CGRect(x: 0.15, y: 0.25, width: 0.65, height: 0.55)
        case .keepRunning: CGRect(x: 0.20, y: 0.10, width: 0.65, height: 0.65)
        case .ready: CGRect(x: 0.10, y: 0.20, width: 0.75, height: 0.70)
        }
    }

    /// R-HO2 — aspect-fill, the framing's point of interest on its anchor, a pane's keep-box kept in view whenever it
    /// fits, then clamped so the container never shows past the painting's edge.
    static func plateRect(image: CGSize, container: CGSize, framing: SceneFraming) -> CGRect {
        guard image.width > 0, image.height > 0, container.width > 0, container.height > 0 else { return .zero }
        let fill = max(container.width / image.width, container.height / image.height)
        let size = CGSize(width: image.width * fill, height: image.height * fill)
        let (point, anchor, keep): (CGPoint, CGPoint, CGRect?) = switch framing {
        case .hero: (CGPoint(x: 0.5, y: heroHorizon), CGPoint(x: 0.5, y: bandHorizon), nil)
        case .fullBleed: (CGPoint(x: 0.5, y: heroHorizon), CGPoint(x: 0.5, y: heroHorizon), nil)
        case .pane(let f): (focus(f), CGPoint(x: 0.5, y: 0.5), keepBox(f))
        }
        func place(_ anchorAt: CGFloat, _ at: CGFloat, _ span: CGFloat, _ room: CGFloat,
                   _ keepLow: CGFloat?, _ keepHigh: CGFloat?) -> CGFloat {
            var v = anchorAt * room - at * span
            if let keepLow, let keepHigh {
                // The keep-box's near edge on screen needs v ≥ −keepLow·span; its far edge, v ≤ room − keepHigh·span.
                // An empty range means the box cannot fit this crop, and the focus decides alone.
                let lowest = -keepLow * span, highest = room - keepHigh * span
                if lowest <= highest { v = min(highest, max(lowest, v)) }
            }
            return min(0, max(room - span, v))
        }
        return CGRect(x: place(anchor.x, point.x, size.width, container.width, keep?.minX, keep?.maxX),
                      y: place(anchor.y, point.y, size.height, container.height, keep?.minY, keep?.maxY),
                      width: size.width, height: size.height)
    }

    /// A corner layer on the plate's pixel grid: cut from the same painting (ART_DIRECTION §5), so it scales with the
    /// plate and sits in its bottom corner.
    static func grassRect(plate: CGRect, plateImage: CGSize, layerImage: CGSize, side: SceneGrassSide) -> CGRect {
        guard plateImage.width > 0, plateImage.height > 0 else { return .zero }
        let w = plate.width * layerImage.width / plateImage.width
        let h = plate.height * layerImage.height / plateImage.height
        return CGRect(x: side == .left ? plate.minX : plate.maxX - w, y: plate.maxY - h, width: w, height: h)
    }

    /// The painting's own rows (0…1) a container shows — ART_DIRECTION §3's band table.
    static func visibleRows(plate: CGRect, container: CGSize) -> ClosedRange<CGFloat> {
        guard plate.height > 0 else { return 0...0 }
        return (-plate.minY / plate.height)...((container.height - plate.minY) / plate.height)
    }

    static func disc(_ center: CGPoint, _ radius: CGFloat) -> CGRect {
        CGRect(x: center.x - radius, y: center.y - radius, width: 2 * radius, height: 2 * radius)
    }
}

/// Where a composition's moving things may be (ART_DIRECTION §5, measured on the shipped paintings in art-r4
/// REVIEW §2): the sky stars fill and the painted clouds and moon they avoid, the grass fireflies keep to, the
/// dandelion clusters seeds rise from, and the light source. Unit rects in the painting's 0…1 space.
struct SceneRegions {
    var starBand: CGRect
    var starExclusions: [CGRect]
    /// A painted moon and its halo radius as a fraction of the painting's WIDTH; stars keep twice that away (§5).
    var moon: (center: CGPoint, radius: CGFloat)?
    var starCount: Int
    var fireflyBoxes: [CGRect]
    var fireflyCount: Int
    var seedBoxes: [(box: CGRect, drift: CGVector)]
    var seedCount: Int
    var light: (day: CGPoint, afternoon: CGPoint, night: CGPoint)
}

/// SplitMix64: the same stars every launch, and never `hashValue`, which Swift seeds per process.
struct SceneRandom {
    private var state: UInt64
    init(seed: UInt64) { state = seed }

    mutating func next() -> UInt64 {
        state &+= 0x9E37_79B9_7F4A_7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
        z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
        return z ^ (z >> 31)
    }

    mutating func unit() -> Double { Double(next() >> 11) / Double(UInt64(1) << 53) }
    mutating func range(_ r: ClosedRange<Double>) -> Double { r.lowerBound + unit() * (r.upperBound - r.lowerBound) }
}

/// The scene's layout tables: regions per composition, the particles generated once from them, and the cloud lanes.
enum SceneLayout {
    static let maxStars = 40        // §5
    static let maxFireflies = 12    // §5
    /// §5 — stars only above this row of the hero.
    static let heroStarFloor: CGFloat = 0.58
    /// §3 — the Welcome card's zone; fireflies and seeds never enter it.
    static let cardZone = CGRect(x: 0.33, y: 0.64, width: 0.34, height: 0.28)
    /// The cloud sprites are 2:1 (ART_DIRECTION §5, `PaintedSceneTests` pins it).
    static let cloudAspect: CGFloat = 0.5

    static func regions(_ c: SceneComposition) -> SceneRegions {
        switch c {
        case .hero:
            SceneRegions(starBand: CGRect(x: 0, y: 0.01, width: 1, height: 0.55),
                         starExclusions: [CGRect(x: 0, y: 0.02, width: 0.38, height: 0.43),      // C1
                                          CGRect(x: 0.62, y: 0.20, width: 0.38, height: 0.32),   // C2
                                          CGRect(x: 0.18, y: 0.55, width: 0.16, height: 0.07),   // c3
                                          CGRect(x: 0.64, y: 0.55, width: 0.16, height: 0.07)],  // c4
                         moon: (CGPoint(x: 0.719, y: 0.112), 0.029),
                         starCount: 24,
                         fireflyBoxes: [CGRect(x: 0.03, y: 0.62, width: 0.25, height: 0.33),
                                        CGRect(x: 0.72, y: 0.62, width: 0.25, height: 0.33)],
                         fireflyCount: 8,
                         seedBoxes: [(CGRect(x: 0.04, y: 0.66, width: 0.18, height: 0.20), CGVector(dx: 0.14, dy: -0.34)),
                                     (CGRect(x: 0.78, y: 0.66, width: 0.18, height: 0.20), CGVector(dx: -0.14, dy: -0.34))],
                         seedCount: 6,
                         light: (CGPoint(x: 0.02, y: 0.02), CGPoint(x: 0.05, y: 0.48), CGPoint(x: 0.719, y: 0.112)))
        case .pane(let f): paneRegions(f)
        }
    }

    /// First-pass regions read off the reviewed paintings (art-r4 `previews/panes-day-afternoon-night.jpg`); the live
    /// look tunes them. The right 8 % stays quiet (§4).
    private static func paneRegions(_ f: PaneFraming) -> SceneRegions {
        let light = (day: CGPoint(x: 0.08, y: 0.04), afternoon: CGPoint(x: 0.06, y: 0.50), night: CGPoint(x: 0.82, y: 0.08))
        switch f {
        case .import:
            return SceneRegions(starBand: CGRect(x: 0, y: 0, width: 0.92, height: 0.30),
                                starExclusions: [CGRect(x: 0.15, y: 0.02, width: 0.72, height: 0.18)], moon: nil,
                                starCount: 12,
                                fireflyBoxes: [CGRect(x: 0.04, y: 0.55, width: 0.84, height: 0.40)], fireflyCount: 6,
                                seedBoxes: [(CGRect(x: 0.30, y: 0.40, width: 0.28, height: 0.22), CGVector(dx: 0.08, dy: -0.30))],
                                seedCount: 4, light: light)
        case .agents:
            return SceneRegions(starBand: CGRect(x: 0, y: 0, width: 0.92, height: 0.84),
                                starExclusions: [CGRect(x: 0, y: 0.03, width: 0.62, height: 0.30),
                                                 CGRect(x: 0.42, y: 0.36, width: 0.58, height: 0.26)], moon: nil,
                                starCount: 16,
                                fireflyBoxes: [CGRect(x: 0.04, y: 0.88, width: 0.84, height: 0.09)], fireflyCount: 5,
                                seedBoxes: [(CGRect(x: 0.10, y: 0.86, width: 0.70, height: 0.06), CGVector(dx: 0.06, dy: -0.35))],
                                seedCount: 4, light: light)
        case .whoReads:
            return SceneRegions(starBand: CGRect(x: 0, y: 0, width: 0.92, height: 0.28),
                                starExclusions: [CGRect(x: 0.05, y: 0.02, width: 0.87, height: 0.16)], moon: nil,
                                starCount: 10,
                                fireflyBoxes: [CGRect(x: 0.04, y: 0.66, width: 0.84, height: 0.30)], fireflyCount: 6,
                                seedBoxes: [(CGRect(x: 0.25, y: 0.30, width: 0.45, height: 0.25), CGVector(dx: 0.08, dy: -0.25))],
                                seedCount: 4, light: light)
        case .keepRunning:
            return SceneRegions(starBand: CGRect(x: 0, y: 0, width: 0.92, height: 0.55),
                                starExclusions: [CGRect(x: 0, y: 0.04, width: 0.50, height: 0.26),
                                                 CGRect(x: 0.50, y: 0.30, width: 0.50, height: 0.20)],
                                // The retouched moon: centre (843, 235) px of 1296 × 1800, radius 50 px (retouch/NOTES.md §2).
                                moon: (CGPoint(x: 0.65, y: 0.13), 0.039), starCount: 16,
                                fireflyBoxes: [CGRect(x: 0.04, y: 0.66, width: 0.84, height: 0.30)], fireflyCount: 6,
                                seedBoxes: [(CGRect(x: 0.10, y: 0.78, width: 0.70, height: 0.17), CGVector(dx: 0.06, dy: -0.30))],
                                seedCount: 4,
                                light: (day: light.day, afternoon: light.afternoon, night: CGPoint(x: 0.65, y: 0.13)))
        case .ready:
            return SceneRegions(starBand: CGRect(x: 0, y: 0, width: 0.92, height: 0.50),
                                starExclusions: [CGRect(x: 0, y: 0.02, width: 0.55, height: 0.23),
                                                 CGRect(x: 0.45, y: 0.24, width: 0.55, height: 0.18)], moon: nil,
                                starCount: 16,
                                fireflyBoxes: [CGRect(x: 0.04, y: 0.62, width: 0.84, height: 0.34)], fireflyCount: 6,
                                seedBoxes: [(CGRect(x: 0.10, y: 0.80, width: 0.70, height: 0.15), CGVector(dx: 0.06, dy: -0.32))],
                                seedCount: 4, light: light)
        }
    }

    static func lightCenter(_ c: SceneComposition, _ time: SceneTime) -> CGPoint {
        let l = regions(c).light
        switch time {
        case .day: return l.day
        case .afternoon: return l.afternoon
        case .night: return l.night
        }
    }

    /// §5 — inside the star band, off every painted cloud, and twice the moon's halo away.
    static func allowsStar(x: CGFloat, y: CGFloat, in r: SceneRegions, aspect: CGFloat) -> Bool {
        let p = CGPoint(x: x, y: y)
        guard r.starBand.contains(p), !r.starExclusions.contains(where: { $0.contains(p) }) else { return false }
        if let moon = r.moon {
            let dx = x - moon.center.x, dy = (y - moon.center.y) / aspect
            if (dx * dx + dy * dy).squareRoot() < 2 * moon.radius { return false }
        }
        return true
    }

    static let starTable: [SceneComposition: [SceneStar]] = table { makeStars($0) }
    static let fireflyTable: [SceneComposition: [SceneFirefly]] = table { makeFireflies($0) }
    static let seedTable: [SceneComposition: [SceneSeed]] = table { makeSeeds($0) }

    private static func table<T>(_ make: (SceneComposition) -> [T]) -> [SceneComposition: [T]] {
        Dictionary(uniqueKeysWithValues: SceneComposition.allCases.map { ($0, make($0)) })
    }

    private static func seed(_ c: SceneComposition) -> UInt64 {
        switch c {
        case .hero: 0xC1CADA
        case .pane(let f): 0xC1CADA &+ UInt64((PaneFraming.allCases.firstIndex(of: f) ?? 0) + 1)
        }
    }

    private static func makeStars(_ c: SceneComposition) -> [SceneStar] {
        let r = regions(c)
        var rng = SceneRandom(seed: seed(c))
        var out: [SceneStar] = []
        for _ in 0..<10_000 where out.count < min(r.starCount, maxStars) {
            let x = r.starBand.minX + CGFloat(rng.unit()) * r.starBand.width
            let y = r.starBand.minY + CGFloat(rng.unit()) * r.starBand.height
            guard allowsStar(x: x, y: y, in: r, aspect: c.aspect) else { continue }
            out.append(SceneStar(x: x, y: y, radius: CGFloat(rng.range(0.6...1.2)),
                                 period: rng.range(CicadaMotion.sceneStarPeriods), phase: rng.range(0...(2 * .pi))))
        }
        return out
    }

    private static func makeFireflies(_ c: SceneComposition) -> [SceneFirefly] {
        let r = regions(c)
        var rng = SceneRandom(seed: seed(c) ^ 0xF1F1)
        return (0..<min(r.fireflyCount, maxFireflies)).map { i in
            let box = r.fireflyBoxes[i % r.fireflyBoxes.count]
            return SceneFirefly(x: box.minX + CGFloat(rng.unit()) * box.width,
                                y: box.minY + CGFloat(rng.unit()) * box.height,
                                wander: rng.range(CicadaMotion.sceneFireflyWanderPeriods),
                                glow: rng.range(CicadaMotion.sceneFireflyGlowPeriods),
                                phase: rng.range(0...(2 * .pi)))
        }
    }

    private static func makeSeeds(_ c: SceneComposition) -> [SceneSeed] {
        let r = regions(c)
        var rng = SceneRandom(seed: seed(c) ^ 0x5EED)
        return (0..<r.seedCount).map { i in
            let (box, drift) = r.seedBoxes[i % r.seedBoxes.count]
            return SceneSeed(x: box.minX + CGFloat(rng.unit()) * box.width,
                             y: box.minY + CGFloat(rng.unit()) * box.height,
                             drift: drift, crossing: rng.range(CicadaMotion.sceneSeedCrossings), phase: rng.unit())
        }
    }

    struct Lane: Equatable {
        let art: MeadowArt
        let centerY: CGFloat
        let width: CGFloat
        let crossing: TimeInterval
        let phase: Double
    }

    /// Cloud lanes in container points. On the Welcome and the panes they are fixed rows of the painting's sky; in
    /// Home's band, whose slice holds only a strip of sky above the hills (§3), they are high clouds whose lower half
    /// peeks in at the band's top, sized so they never reach the hills (R-HO10).
    static func lanes(for framing: SceneFraming, plate: CGRect) -> [Lane] {
        let slow = CicadaMotion.sceneCloudCrossings[0], quick = CicadaMotion.sceneCloudCrossings[1]
        typealias Spec = (art: MeadowArt, row: CGFloat, share: CGFloat, crossing: TimeInterval, phase: Double)
        func rows(_ spec: [Spec]) -> [Lane] {
            spec.map { Lane(art: $0.art, centerY: plate.minY + $0.row * plate.height, width: $0.share * plate.width,
                            crossing: $0.crossing, phase: $0.phase) }
        }
        switch framing {
        case .hero:
            let sky = max(0, plate.minY + SceneGeometry.hillsTop * plate.height)
            let spec: [Spec] = [(.cloud3, 0.30, 0.14, slow, 0.20), (.cloud2, 0.55, 0.18, quick, 0.70)]
            return spec.map { Lane(art: $0.art, centerY: $0.row * sky, width: min($0.share * plate.width, 1.8 * sky),
                                   crossing: $0.crossing, phase: $0.phase) }
        case .fullBleed:
            return rows([(.cloud2, 0.16, 0.30, slow, 0.15), (.cloud3, 0.30, 0.20, quick, 0.65)])
        case .pane(let f):
            switch f {
            case .import: return rows([(.cloud3, 0.10, 0.55, slow, 0.30)])
            case .agents: return rows([(.cloud2, 0.30, 0.75, slow, 0.10), (.cloud3, 0.52, 0.50, quick, 0.60)])
            case .whoReads: return rows([(.cloud3, 0.10, 0.55, slow, 0.50)])
            case .keepRunning: return rows([(.cloud3, 0.36, 0.50, slow, 0.40)])
            case .ready: return rows([(.cloud2, 0.16, 0.70, slow, 0.25), (.cloud3, 0.32, 0.50, quick, 0.75)])
            }
        }
    }
}
