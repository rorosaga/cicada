import SwiftUI
import XCTest
@testable import CicadaApp

/// G137 R-M6 / plan R-M22 — the Meadow views' rules, as pure functions.
final class MeadowTests: XCTestCase {
    func testCloudsDriftGentlyAndStandStillUnderReduceMotion() {
        for t in stride(from: 0.0, through: 240.0, by: 0.5) {
            XCTAssertLessThanOrEqual(abs(MeadowRules.driftOffset(at: t, amplitude: 40, period: 5, reduceMotion: false)),
                                     CicadaMotion.ambientMaxAmplitude + 1e-9, "amplitude is capped at 8 pt")
            XCTAssertEqual(MeadowRules.driftOffset(at: t, amplitude: 8, period: 90, reduceMotion: true), 0)
        }
        // A 5 s period is clamped up to 60 s: one second in it has barely
        // moved (0.84 pt), where an unclamped 5 s period would be at 7.6 pt.
        XCTAssertLessThan(abs(MeadowRules.driftOffset(at: 1, amplitude: 8, period: 5, reduceMotion: false)), 1)
    }

    func testDriftPausesUnderReduceMotionAndWheneverTheWindowIsNotKey() {
        XCTAssertFalse(MeadowRules.isDriftPaused(reduceMotion: false, activeState: .key))
        XCTAssertTrue(MeadowRules.isDriftPaused(reduceMotion: false, activeState: .active))
        XCTAssertTrue(MeadowRules.isDriftPaused(reduceMotion: false, activeState: .inactive))
        XCTAssertTrue(MeadowRules.isDriftPaused(reduceMotion: true, activeState: .key))
    }

    func testArtFadesUnderIncreasedContrastAndMoonCloudsStayFaint() {
        XCTAssertEqual(MeadowRules.cloudOpacity(mode: .light, contrast: .standard), 0.85)
        XCTAssertLessThanOrEqual(MeadowRules.cloudOpacity(mode: .dark, contrast: .standard), 0.4)
        for mode in AppColorScheme.allCases {
            XCTAssertLessThanOrEqual(MeadowRules.cloudOpacity(mode: mode, contrast: .increased), 0.3)
        }
        XCTAssertEqual(MeadowRules.grassOpacity(contrast: .standard), 1)
        XCTAssertLessThanOrEqual(MeadowRules.grassOpacity(contrast: .increased), 0.3)
    }

    func testEveryPaintingIsNamedForItsScene() {
        XCTAssertEqual(MeadowArt.fileName(for: .cloud1, time: .day), "cloud-1-day")
        XCTAssertEqual(MeadowArt.fileName(for: .pane(.whoReads), time: .afternoon), "pane-who-reads-afternoon")
        XCTAssertEqual(MeadowArt.hero.fileExtension, "jpg", "the opaque paintings are JPEG (ART_DIRECTION §6)")
        XCTAssertEqual(MeadowArt.pane(.import).fileExtension, "jpg")
        XCTAssertEqual(MeadowArt.grassEdge.fileExtension, "png")
        XCTAssertEqual(MeadowArt.allCases.count, 7 + PaneFraming.allCases.count)
    }
}
