import XCTest
@testable import CicadaApp

/// R-DS4 — the accent's text ink: exactly the rules' values for the default blue, and pushed
/// until it reads for any other accent a person may have chosen.
final class AccentInkTests: XCTestCase {
    private let baseDark = AccentInk.RGB(hex: 0x111213)
    private let baseLight = AccentInk.RGB(hex: 0xF7F7F5)

    func testTheDefaultBlueLandsExactlyOnTheRulesValues() {
        XCTAssertEqual(AccentInk.text(accent: .init(hex: 0x0A84FF), mode: .dark, base: baseDark), .init(hex: 0x0A84FF))
        XCTAssertEqual(AccentInk.text(accent: .init(hex: 0x007AFF), mode: .light, base: baseLight), .init(hex: 0x0062CC))
        XCTAssertEqual(AccentInk.hover(accent: .init(hex: 0x0A84FF), mode: .dark, base: baseDark), .init(hex: 0x4DA3FF))
        XCTAssertEqual(AccentInk.hover(accent: .init(hex: 0x007AFF), mode: .light, base: baseLight), .init(hex: 0x004FA3))
    }

    func testAnyOtherAccentIsPushedUntilItReads() {
        let accents: [UInt32] = [0xFFCC00, 0xBF5AF2, 0x8C8C8C, 0xFF9F0A, 0x30D158]   // yellow, purple, graphite, orange, green
        for hex in accents {
            let dark = AccentInk.text(accent: .init(hex: hex), mode: .dark, base: baseDark)
            let light = AccentInk.text(accent: .init(hex: hex), mode: .light, base: baseLight)
            XCTAssertGreaterThanOrEqual(AccentInk.contrast(dark, baseDark), 4.5, String(hex, radix: 16))
            XCTAssertGreaterThanOrEqual(AccentInk.contrast(light, baseLight), 4.5, String(hex, radix: 16))
        }
        // Measured: yellow needs 50 % black, well inside the 60 % cap.
        XCTAssertEqual(AccentInk.text(accent: .init(hex: 0xFFCC00), mode: .light, base: baseLight), .init(hex: 0x806600))
    }

    func testTheWalkStopsAtItsCapInsteadOfLooping() {
        // An accent equal to the base can never reach 4.5:1 by 60 %; the walk still returns.
        _ = AccentInk.text(accent: baseLight, mode: .light, base: baseLight)
        _ = AccentInk.text(accent: baseDark, mode: .dark, base: baseDark)
    }
}
