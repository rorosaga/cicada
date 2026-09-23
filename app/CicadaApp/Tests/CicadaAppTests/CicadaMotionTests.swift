import SwiftUI
import XCTest
@testable import CicadaApp

/// G137 R-M4 — the motion vocabulary's budget, its Reduce Motion switch, and
/// the two hover modifiers' pure halves.
final class CicadaMotionTests: XCTestCase {
    private let transitions: [(String, (Bool) -> Animation?)] = [
        ("press", CicadaMotion.press), ("hover", CicadaMotion.hover), ("snap", CicadaMotion.snap),
        ("standard", CicadaMotion.standard), ("panel", CicadaMotion.panel), ("expand", CicadaMotion.expand),
        ("lift", CicadaMotion.lift), ("settle", CicadaMotion.settle), ("morph", CicadaMotion.morph),
        ("groupExpand", CicadaMotion.groupExpand),
    ]

    /// `nil` is SwiftUI for "jump to the new value" — the terminal frame.
    func testReduceMotionRemovesEveryTransition() {
        for (name, animation) in transitions {
            XCTAssertNil(animation(true), "\(name) still animates under Reduce Motion")
            XCTAssertNotNil(animation(false), name)
        }
    }

    func testEveryDurationIsInsideTheBudget() {
        let durations = [CicadaMotion.pressDuration, CicadaMotion.hoverDuration, CicadaMotion.snapDuration,
                         CicadaMotion.standardDuration, CicadaMotion.panelDuration, CicadaMotion.expandDuration,
                         CicadaMotion.liftDuration, CicadaMotion.settleDuration, CicadaMotion.morphDuration,
                         CicadaMotion.groupExpandDuration]
        for d in durations { XCTAssertLessThanOrEqual(d, CicadaMotion.maxDuration) }
        XCTAssertLessThanOrEqual(CicadaMotion.maxDuration, 0.4, "the same 400 ms ceiling SleepMotion holds")
        XCTAssertEqual(CicadaMotion.settleDuration, SleepMotion.settleDuration, "one settle, two pages")
    }

    /// R-M6: ≤ 8 pt, a 60–120 s period, no faster than 30 fps.
    func testTheAmbientBudget() {
        XCTAssertLessThanOrEqual(CicadaMotion.ambientMaxAmplitude, 8)
        XCTAssertEqual(CicadaMotion.ambientPeriodRange, 60...120)
        XCTAssertTrue(CicadaMotion.ambientPeriodRange.contains(CicadaMotion.ambientDefaultPeriod))
        XCTAssertGreaterThanOrEqual(CicadaMotion.ambientFrameInterval, 1.0 / 30.0)
    }

    /// R-M14: text never looks soft mid-animation, and the shadow is the cue
    /// that survives Reduce Motion.
    func testHoverLiftCapsItsMotionAndKeepsItsShadowUnderReduceMotion() {
        let greedy = HoverLift.pose(hovering: true, reduceMotion: false, scale: 1.2, lift: 9)
        XCTAssertEqual(greedy.scale, HoverLift.maxScale)
        XCTAssertEqual(greedy.lift, HoverLift.maxLift)
        let still = HoverLift.pose(hovering: true, reduceMotion: true, scale: 1.015, lift: 2)
        XCTAssertEqual(still.scale, 1)
        XCTAssertEqual(still.lift, 0)
        let rest = HoverLift.pose(hovering: false, reduceMotion: true, scale: 1.015, lift: 2)
        XCTAssertGreaterThan(still.shadowOpacity, rest.shadowOpacity, "hover must still read without motion")
        XCTAssertLessThanOrEqual(HoverLift.maxScale, 1.02)
        XCTAssertLessThanOrEqual(HoverLift.maxLift, 2)
    }

    /// R-M13: a glyph acknowledges the pointer ONCE, on entry, and never
    /// under Reduce Motion — enforced by not firing, not by hoping
    /// `symbolEffectsRemoved` reaches the effect.
    func testIconHoverBumpsOnEntryOnlyAndNeverUnderReduceMotion() {
        XCTAssertEqual(IconHover.nextBump(3, entering: true, reduceMotion: false), 4)
        XCTAssertEqual(IconHover.nextBump(3, entering: false, reduceMotion: false), 3)
        XCTAssertEqual(IconHover.nextBump(3, entering: true, reduceMotion: true), 3)
        XCTAssertEqual(IconHover.nextBump(Int.max, entering: true, reduceMotion: false), Int.min, "wraps, never traps")
    }

    func testTheIntakeMotionNamesSitUnderTheBudgetAndVanishUnderReduceMotion() {
        for d in [CicadaMotion.markNodDuration, CicadaMotion.dropVeilDuration, CicadaMotion.successDuration] {
            XCTAssertLessThanOrEqual(d, CicadaMotion.maxDuration)
        }
        XCTAssertEqual(CicadaMotion.revealStagger, 0.04)
        XCTAssertEqual(CicadaMotion.revealMaxRows, 8)
        XCTAssertNil(CicadaMotion.dropVeil(reduceMotion: true))
        XCTAssertNil(CicadaMotion.success(reduceMotion: true))
        XCTAssertNil(CicadaMotion.reveal(index: 3, reduceMotion: true))
        XCTAssertNotNil(CicadaMotion.reveal(index: 30, reduceMotion: false), "capped, never dropped")
    }

    /// `MarkHover` (design §7): a transform-only nod — never a tint — that is a
    /// 1 pt ring under Reduce Motion instead.
    func testTheMarkNodIsATransformAndARingUnderReduceMotion() {
        XCTAssertEqual(MarkHover.rotationKeys, [-5, 3, 0])
        XCTAssertEqual(MarkHover.scaleKeys, [1.08, 1])
        XCTAssertEqual(MarkHover.nextNod(0, entering: true, reduceMotion: false), 1)
        XCTAssertEqual(MarkHover.nextNod(0, entering: true, reduceMotion: true), 0)
        XCTAssertEqual(MarkHover.nextNod(0, entering: false, reduceMotion: false), 0)
        XCTAssertEqual(MarkHover.nextNod(Int.max, entering: true, reduceMotion: false), Int.min, "wraps, never traps")
        XCTAssertTrue(MarkHover.showsRing(hovering: true, reduceMotion: true))
        XCTAssertFalse(MarkHover.showsRing(hovering: true, reduceMotion: false))
    }
}
