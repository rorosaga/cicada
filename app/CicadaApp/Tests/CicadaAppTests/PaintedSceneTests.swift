import SwiftUI
import XCTest
@testable import CicadaApp

/// C10 (round-4 T-Home) — the living painting's geometry and motion as pure functions: the crops ART_DIRECTION
/// promises (§3, §4), the caps and pauses the brief asks for (R-HO3, R-HO7), the overscan REVIEW §3 asked for
/// (R-HO5), and "gentler, never frozen" (DR-66).
@MainActor
final class PaintedSceneTests: XCTestCase {
    /// The shipped sizes in points (2× pixels, R-HO8).
    let hero = CGSize(width: 1188, height: 742.5)
    let corner = CGSize(width: 495, height: 371.5)
    let pane = CGSize(width: 648, height: 900)

    // MARK: Framing

    func testTheBandShowsTheSliceArtDirectionPromises() {
        for (width, top, bottom) in [(CGFloat(1000), CGFloat(0.44), CGFloat(0.77)), (1400, 0.50, 0.74), (1920, 0.55, 0.72)] {
            let container = CGSize(width: width, height: 208)
            let plate = SceneGeometry.plateRect(image: hero, container: container, framing: .hero(band: 208))
            let rows = SceneGeometry.visibleRows(plate: plate, container: container)
            XCTAssertEqual(rows.lowerBound, top, accuracy: 0.01, "\(width)")
            XCTAssertEqual(rows.upperBound, bottom, accuracy: 0.01, "\(width)")
        }
    }

    func testTheBandPutsTheMeadowLineAtTwoThirds() {
        let plate = SceneGeometry.plateRect(image: hero, container: CGSize(width: 1400, height: 208), framing: .hero(band: 208))
        XCTAssertEqual(plate.minY + SceneGeometry.heroHorizon * plate.height, 208 * 2 / 3, accuracy: 0.5)
    }

    func testTheWelcomeFillsA1440By900WindowWithTheWholeHero() {
        let plate = SceneGeometry.plateRect(image: hero, container: CGSize(width: 1440, height: 900), framing: .fullBleed)
        XCTAssertEqual(plate.minX, 0, accuracy: 0.5)
        XCTAssertEqual(plate.minY, 0, accuracy: 0.5)
        XCTAssertEqual(plate.width, 1440, accuracy: 0.5)
        XCTAssertEqual(plate.height, 900, accuracy: 0.5)
    }

    func testNoFramingEverShowsPastThePaintingsEdge() {
        let framings: [SceneFraming] = [.hero(band: 208), .fullBleed] + PaneFraming.allCases.map(SceneFraming.pane)
        for framing in framings {
            let image = framing.composition == .hero ? hero : pane
            for w in stride(from: CGFloat(300), through: 2600, by: 230) {
                for h in [CGFloat(120), 208, 600, 900, 1400] {
                    let r = SceneGeometry.plateRect(image: image, container: CGSize(width: w, height: h), framing: framing)
                    XCTAssertLessThanOrEqual(r.minX, 0.001, "\(framing) \(w)×\(h)")
                    XCTAssertLessThanOrEqual(r.minY, 0.001, "\(framing) \(w)×\(h)")
                    XCTAssertGreaterThanOrEqual(r.maxX, w - 0.001, "\(framing) \(w)×\(h)")
                    XCTAssertGreaterThanOrEqual(r.maxY, h - 0.001, "\(framing) \(w)×\(h)")
                }
            }
        }
    }

    /// ART_DIRECTION §4 — the keep-box survives every crop the split pane makes (R-HO2). At aspect 0.90 `agents`'
    /// box (0.85 of its height) cannot fit the 0.80 a crop keeps; there its focus decides.
    func testEveryPaneKeepsItsKeepBoxWheneverItCanFit() {
        for f in PaneFraming.allCases {
            for aspect in [CGFloat(0.56), 0.60, 0.72, 0.80, 0.90] where !(f == .agents && aspect == 0.90) {
                let container = CGSize(width: 900 * aspect, height: 900)
                let r = SceneGeometry.plateRect(image: pane, container: container, framing: .pane(f))
                let kb = SceneGeometry.keepBox(f)
                XCTAssertGreaterThanOrEqual(r.minX + kb.minX * r.width, -0.5, "\(f) \(aspect)")
                XCTAssertLessThanOrEqual(r.minX + kb.maxX * r.width, container.width + 0.5, "\(f) \(aspect)")
                XCTAssertGreaterThanOrEqual(r.minY + kb.minY * r.height, -0.5, "\(f) \(aspect)")
                XCTAssertLessThanOrEqual(r.minY + kb.maxY * r.height, container.height + 0.5, "\(f) \(aspect)")
            }
        }
    }

    func testTheGrassSitsOnThePlatesPixelGrid() {
        let plate = SceneGeometry.plateRect(image: hero, container: CGSize(width: 1440, height: 900), framing: .fullBleed)
        let left = SceneGeometry.grassRect(plate: plate, plateImage: hero, layerImage: corner, side: .left)
        let right = SceneGeometry.grassRect(plate: plate, plateImage: hero, layerImage: corner, side: .right)
        XCTAssertEqual(left.minX, 0, accuracy: 0.01)
        XCTAssertEqual(left.maxY, 900, accuracy: 0.01)
        XCTAssertEqual(left.width, 600, accuracy: 0.5)
        XCTAssertEqual(left.height, 450.3, accuracy: 0.5)
        XCTAssertEqual(right.maxX, 1440, accuracy: 0.01)
        XCTAssertEqual(right.width, left.width, accuracy: 0.01)
    }

    /// REVIEW §3 — the plates are not paintings on their own: at full sway a clump's outer edge would uncover a strip
    /// of plate. The overscan (R-HO5) must always cover the widest strip a sway can open, at every width and moment.
    func testASwayNeverUncoversThePlatesEdge() {
        for (framing, height) in [(SceneFraming.hero(band: 208), CGFloat(208)), (SceneFraming.fullBleed, CGFloat(900))] {
            for width in stride(from: CGFloat(800), through: 2600, by: 150) {
                let container = CGSize(width: width, height: height)
                let plate = SceneGeometry.plateRect(image: hero, container: container, framing: framing)
                let layer = SceneGeometry.grassRect(plate: plate, plateImage: hero, layerImage: corner, side: .left)
                for profile in [SceneProfile.full, .gentle] {
                    let reach = profile == .full ? CicadaMotion.sceneGrassAmplitude : CicadaMotion.sceneGrassGentleAmplitude
                    let strip = layer.height * CGFloat(sin(reach * .pi / 180))
                    for t in stride(from: 0.0, through: CicadaMotion.sceneCameraPeriod, by: 2) {
                        let c = SceneMotion.camera(at: t, container: container, profile: profile)
                        let spare = ((c.scale - 1) * width / 2 - abs(c.dx)) / c.scale
                        XCTAssertGreaterThanOrEqual(-plate.minX + spare, strip, "\(framing) \(width) \(profile) t=\(t)")
                        XCTAssertGreaterThanOrEqual(plate.maxX - width + spare, strip, "\(framing) \(width) \(profile) t=\(t)")
                    }
                }
            }
        }
    }

    // MARK: Motion

    func testTheCameraBreathesInsideItsOverscan() {
        let size = CGSize(width: 1440, height: 900)
        for t in stride(from: 0.0, through: 2 * CicadaMotion.sceneCameraPeriod, by: 0.5) {
            let c = SceneMotion.camera(at: t, container: size, profile: .full)
            XCTAssertGreaterThanOrEqual(c.scale, CicadaMotion.sceneOverscan - 1e-9)
            XCTAssertLessThanOrEqual(c.scale, CicadaMotion.sceneCameraScale + 1e-9)
            XCTAssertLessThanOrEqual(abs(c.dx), (c.scale - CicadaMotion.sceneOverscan) / 2 * size.width + 1e-6)
            XCTAssertLessThanOrEqual(abs(c.dy), (c.scale - CicadaMotion.sceneOverscan) / 2 * size.height + 1e-6)
        }
        XCTAssertEqual(SceneMotion.camera(at: 30, container: size, profile: .gentle),
                       SceneCamera(scale: CicadaMotion.sceneOverscan, dx: 0, dy: 0),
                       "DR-66 — the camera stops, the overscan stays")
    }

    func testTheGrassSwaysFromItsRootsWithinTheCeilingAndNeverFreezes() {
        for t in stride(from: 0.0, through: 60, by: 0.25) {
            for side in SceneGrassSide.allCases {
                XCTAssertLessThanOrEqual(abs(SceneMotion.grassAngle(side, at: t, profile: .full)),
                                         CicadaMotion.sceneGrassAmplitude + 1e-9)
                XCTAssertLessThanOrEqual(abs(SceneMotion.grassAngle(side, at: t, profile: .gentle)),
                                         CicadaMotion.sceneGrassGentleAmplitude + 1e-9)
            }
        }
        XCTAssertLessThanOrEqual(CicadaMotion.sceneGrassAmplitude, CicadaMotion.sceneGrassMaxAmplitude,
                                 "ART_DIRECTION §5's 1.5° ceiling")
        XCTAssertNotEqual(SceneMotion.grassAngle(.left, at: 1, profile: .gentle),
                          SceneMotion.grassAngle(.left, at: 5, profile: .gentle), "gentler, never frozen (DR-66)")
        XCTAssertNotEqual(SceneMotion.grassAngle(.left, at: 1, profile: .full),
                          SceneMotion.grassAngle(.right, at: 1, profile: .full), "the clumps never move in step")
        XCTAssertEqual(SceneGrassSide.left.pivot, .bottomLeading)
        XCTAssertEqual(SceneGrassSide.right.pivot, .bottomTrailing)
    }

    func testCloudsTravelOneWayAndStandStillWhenGentle() {
        let size = CGSize(width: 1440, height: 900)
        let plate = SceneGeometry.plateRect(image: hero, container: size, framing: .fullBleed)
        func xs(_ t: TimeInterval, _ p: SceneProfile) -> [CGFloat] {
            SceneMotion.clouds(at: t, plate: plate, container: size, framing: .fullBleed, time: .day, profile: p)
                .map(\.frame.minX)
        }
        let a = xs(1_000, .full), b = xs(1_001, .full)
        XCTAssertFalse(a.isEmpty)
        for (x0, x1) in zip(a, b) {
            XCTAssertGreaterThan(x1, x0, "one way, left to right")
            XCTAssertLessThan(x1 - x0, 10, "a crossing takes minutes")
        }
        XCTAssertEqual(xs(0, .gentle), xs(500, .gentle), "Reduce Motion holds the clouds still")
        XCTAssertEqual(SceneMotion.clouds(at: 0, plate: plate, container: size, framing: .fullBleed, time: .night,
                                          profile: .full).first?.opacity, MeadowRules.darkCloudOpacity)
    }

    func testTheBandsCloudsStayAboveTheHills() {
        for width in stride(from: CGFloat(800), through: 2600, by: 150) {
            let size = CGSize(width: width, height: 208)
            let plate = SceneGeometry.plateRect(image: hero, container: size, framing: .hero(band: 208))
            let hills = plate.minY + SceneGeometry.hillsTop * plate.height
            for cloud in SceneMotion.clouds(at: 100, plate: plate, container: size, framing: .hero(band: 208),
                                            time: .day, profile: .full) {
                XCTAssertLessThanOrEqual(cloud.frame.maxY, hills + 0.5, "\(width)")
            }
        }
    }

    func testEveryCloudIsTwoToOneAsTheLanesAssume() throws {
        for art in [MeadowArt.cloud1, .cloud2, .cloud3] {
            for time in SceneTime.allCases {
                let size = try XCTUnwrap(MeadowArt.image(for: art, time: time)).size
                XCTAssertEqual(size.height / size.width, SceneLayout.cloudAspect, accuracy: 0.001)
            }
        }
    }

    func testStarsKeepToTheSkyClearOfTheMoonAndThePaintedClouds() {
        for c in SceneComposition.allCases {
            let stars = SceneLayout.starTable[c] ?? []
            let regions = SceneLayout.regions(c)
            XCTAssertFalse(stars.isEmpty, "\(c)")
            XCTAssertLessThanOrEqual(stars.count, SceneLayout.maxStars)
            for s in stars {
                XCTAssertTrue(SceneLayout.allowsStar(x: s.x, y: s.y, in: regions, aspect: c.aspect), "\(c) \(s.x),\(s.y)")
                if c == .hero { XCTAssertLessThan(s.y, SceneLayout.heroStarFloor) }
                for t in [0.0, 1.7, 3.3] {
                    let o = SceneMotion.twinkle(s, at: t, profile: .full)
                    XCTAssertGreaterThanOrEqual(o, 0.18 - 1e-9)
                    XCTAssertLessThanOrEqual(o, 0.92 + 1e-9)
                }
            }
        }
        XCTAssertFalse(SceneLayout.allowsStar(x: 0.719, y: 0.112, in: SceneLayout.regions(.hero), aspect: 1.6),
                       "never inside the moon's halo")
        let star = SceneLayout.starTable[.hero]![0]
        XCTAssertNotEqual(SceneMotion.twinkle(star, at: 0, profile: .gentle),
                          SceneMotion.twinkle(star, at: 2, profile: .gentle), "a still night still twinkles (§5)")
    }

    func testFirefliesKeepToTheGrassAndOutOfTheWelcomeCard() {
        let narrow = CGRect(x: 0, y: 0, width: 800, height: 500)   // the narrowest window the Welcome fills
        for c in SceneComposition.allCases {
            let flies = SceneLayout.fireflyTable[c] ?? []
            XCTAssertFalse(flies.isEmpty, "\(c)")
            XCTAssertLessThanOrEqual(flies.count, SceneLayout.maxFireflies)
            for f in flies {
                if c == .hero {
                    XCTAssertGreaterThan(f.y, 0.55)
                    let margin = CicadaMotion.sceneFireflyReach * 1.5 / narrow.width
                    XCTAssertFalse(SceneLayout.cardZone.insetBy(dx: -margin, dy: -margin).contains(CGPoint(x: f.x, y: f.y)))
                } else {
                    XCTAssertLessThanOrEqual(f.x, 0.92, "the pane's right 8 % stays quiet (§4)")
                }
                let home = CGPoint(x: f.x * narrow.width, y: f.y * narrow.height)
                for t in stride(from: 0.0, through: 40, by: 0.5) {
                    let p = SceneMotion.firefly(f, at: t, plate: narrow, profile: .full)
                    XCTAssertLessThanOrEqual(hypot(p.center.x - home.x, p.center.y - home.y), 17.0001, "§5 ≤ 17 pt")
                }
                XCTAssertEqual(SceneMotion.firefly(f, at: 3, plate: narrow, profile: .gentle).center, home,
                               "gentle: the glow stays, the wander goes")
            }
        }
    }

    func testSeedsRiseFromTheCornersAndNeverCrossTheWelcomeCard() {
        let plate = CGRect(x: 0, y: 0, width: 1440, height: 900)
        let seeds = SceneLayout.seedTable[.hero] ?? []
        XCTAssertFalse(seeds.isEmpty)
        for seed in seeds {
            for u in stride(from: 0.0, through: 0.98, by: 0.02) {
                let p = SceneMotion.seed(seed, at: (u - seed.phase + 1) * seed.crossing, plate: plate, profile: .full)
                XCTAssertFalse(SceneLayout.cardZone.contains(CGPoint(x: p.center.x / plate.width, y: p.center.y / plate.height)),
                               "a seed crosses the Welcome card at u=\(u)")
                XCTAssertLessThan(p.center.y, seed.y * plate.height + CicadaMotion.sceneSeedBob + 0.01, "seeds rise")
            }
            XCTAssertNotEqual(SceneMotion.seed(seed, at: 0, plate: plate, profile: .gentle).opacity,
                              SceneMotion.seed(seed, at: 3, plate: plate, profile: .gentle).opacity,
                              "gentle: a seed fades in place, never frozen (DR-66)")
        }
    }

    // MARK: Policy, profile, crossfade

    func testThePolicyPausesWhatNobodyCanSeeAndCapsTheFrameRate() {
        XCTAssertFalse(SceneRunPolicy.isPaused(windowVisible: true, hostPaused: false))
        XCTAssertTrue(SceneRunPolicy.isPaused(windowVisible: false, hostPaused: false))
        XCTAssertTrue(SceneRunPolicy.isPaused(windowVisible: true, hostPaused: true))
        XCTAssertGreaterThanOrEqual(SceneRunPolicy.frameInterval(lowPower: false), 1.0 / 30.0, "≤ 30 fps (the brief)")
        XCTAssertGreaterThan(SceneRunPolicy.frameInterval(lowPower: true), SceneRunPolicy.frameInterval(lowPower: false))
    }

    func testTheProfileIsGentleUnderReduceMotionOrLowPower() {
        XCTAssertEqual(SceneProfile.of(reduceMotion: false, lowPower: false), .full)
        XCTAssertEqual(SceneProfile.of(reduceMotion: true, lowPower: false), .gentle)
        XCTAssertEqual(SceneProfile.of(reduceMotion: false, lowPower: true), .gentle)
    }

    func testTheCrossfadeLaysTheNewestSceneOverTheLatest() {
        var fade = SceneCrossfadeState(.day)
        XCTAssertFalse(fade.begin(.day), "no fade to the scene already showing")
        XCTAssertTrue(fade.begin(.afternoon))
        XCTAssertEqual(fade.base, .day)
        XCTAssertEqual(fade.incoming, .afternoon)
        XCTAssertTrue(fade.begin(.night), "a pick mid-fade")
        XCTAssertEqual(fade.base, .afternoon, "the newest choice fades in over the latest")
        XCTAssertFalse(fade.finish(.afternoon), "a superseded fade's end changes nothing")
        XCTAssertTrue(fade.finish(.night))
        XCTAssertEqual(fade, SceneCrossfadeState(.night))
        XCTAssertEqual(CicadaMotion.sceneCrossfadeDuration, 1.2)
        XCTAssertEqual(CicadaMotion.sceneCrossfadeReducedDuration, 0.6, "Reduce Motion shortens the fade, never removes it")
    }

    func testOneFrameOfMotionIsCheap() {
        let size = CGSize(width: 1440, height: 900)
        let plate = SceneGeometry.plateRect(image: hero, container: size, framing: .fullBleed)
        let start = Date()
        for i in 0..<3_000 {
            let t = Double(i) / 30
            _ = SceneMotion.camera(at: t, container: size, profile: .full)
            _ = SceneMotion.clouds(at: t, plate: plate, container: size, framing: .fullBleed, time: .night, profile: .full)
            for side in SceneGrassSide.allCases { _ = SceneMotion.grassAngle(side, at: t, profile: .full) }
            for s in SceneLayout.starTable[.hero] ?? [] { _ = SceneMotion.twinkle(s, at: t, profile: .full) }
            for f in SceneLayout.fireflyTable[.hero] ?? [] { _ = SceneMotion.firefly(f, at: t, plate: plate, profile: .full) }
            for s in SceneLayout.seedTable[.hero] ?? [] { _ = SceneMotion.seed(s, at: t, plate: plate, profile: .full) }
        }
        let perFrame = Date().timeIntervalSince(start) / 3_000
        print("scene motion: \(String(format: "%.1f", perFrame * 1_000_000)) µs a frame")
        XCTAssertLessThan(perFrame, 0.002, "the motion math must be a sliver of a 33 ms frame")
    }
}
