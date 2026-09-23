import SwiftUI   // `ControlActiveState`
import XCTest
@testable import CicadaApp

/// Track I T4 (R-IA16) — the one meadow pill. On the opaque capsule we draw the
/// plate, so the ink is always `onMeadow`; on 26's glass the key-window rule
/// `PrimaryActionInk` learned applies (a non-key window drops the plate).
final class MeadowPillTests: XCTestCase {
    func testTheCapsuleAlwaysCarriesMeadowInk() {
        for state in [ControlActiveState.key, .active, .inactive] {
            XCTAssertTrue(LiquidGlass.meadowInkIsOnMeadow(state, usesGlass: false))
        }
    }

    func testGlassUsesMeadowInkOnlyInAKeyWindow() {
        XCTAssertTrue(LiquidGlass.meadowInkIsOnMeadow(.key, usesGlass: true))
        XCTAssertFalse(LiquidGlass.meadowInkIsOnMeadow(.inactive, usesGlass: true))
    }

    func testReduceTransparencyNeverDrawsGlass() {
        XCTAssertFalse(LiquidGlass.meadowPillUsesGlass(reduceTransparency: true))
    }
}
