import SwiftUI
import XCTest
@testable import CicadaApp

/// G137 R-M5 / plan R-M19 — "use Liquid Glass sparingly" (HIG Materials) made
/// enforceable: every glass API lives in `Theme/LiquidGlass.swift`, behind
/// one macOS 26 gate, so a glass surface on a content card, a list row or the
/// graph cannot arrive in a diff without touching that file.
final class LiquidGlassLintTests: XCTestCase {
    static let home = "Theme/LiquidGlass.swift"
    static let needles = [".glassEffect(", "GlassEffectContainer", "glassEffectID(", "glassEffectUnion(",
                          ".glassProminent", ".buttonStyle(.glass)", ".buttonStyle(.glass(",
                          ".backgroundExtensionEffect("]

    func testGlassAPIsLiveInOneFile() throws {
        var offenders: [String] = []
        for file in try ThemeTokenTests.swiftSources() where !file.path.hasSuffix(Self.home) {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//") else { continue }
                if Self.needles.contains(where: { code.contains($0) }) {
                    offenders.append("\(file.lastPathComponent):\(index + 1)")
                }
            }
        }
        XCTAssertEqual(offenders, [], "glass outside \(Self.home) — chrome only, through liquidGlass(_:in:) (G137 R-M5)")
    }

    func testTheHomeFileGatesGlassOnMacOS26() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(Self.home) })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(text.contains("#available(macOS 26, *)"), "the package floor is macOS 14 — glass must be gated")
        XCTAssertTrue(text.contains(".glassEffect("), "the lint would pass vacuously without the real call here")
    }

    /// The fallback branch is ours to get right (on 26 the system handles
    /// Reduce Transparency and Increase Contrast itself — WWDC25-219).
    func testTheFallbackGoesOpaqueUnderReduceTransparencyAndStrongUnderIncreasedContrast() {
        XCTAssertEqual(LiquidGlass.fallback(reduceTransparency: true), .opaque)
        XCTAssertEqual(LiquidGlass.fallback(reduceTransparency: false), .material)
        XCTAssertTrue(LiquidGlass.strongBorder(contrast: .increased))
        XCTAssertFalse(LiquidGlass.strongBorder(contrast: .standard))
        XCTAssertEqual(LiquidGlass.overImageryDim, 0.35, "Apple's recipe for clear glass over imagery")
    }

    /// M1 final review: `#available` is only a runtime check, and the glass
    /// symbols exist only in the macOS 26 SDK — an unguarded call stops the
    /// README's macOS 14 / command-line-tools build from compiling. Every
    /// runtime gate in the home file must sit inside the SDK guard.
    func testEveryMacOS26GateAlsoHasTheSDKGuard() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(Self.home) })
        let text = try String(contentsOf: file, encoding: .utf8)
        let code = text.components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.hasPrefix("//") }
        let runtimeGates = code.filter { $0.contains("#available(macOS 26, *)") }.count
        let sdkGuards = code.filter { $0.hasPrefix("#if canImport(SwiftUI, _version: 7.0)") }.count
        XCTAssertGreaterThan(runtimeGates, 0)
        XCTAssertEqual(sdkGuards, runtimeGates, "each macOS 26 branch needs its own compile-time SDK guard")
    }

    /// M1 final review: in a window that is not key the prominent style
    /// drops its accent plate, so `onAccent` ink there reads at ~1.4:1.
    func testPrimaryInkIsOnAccentOnlyInAKeyWindow() {
        XCTAssertTrue(LiquidGlass.primaryInkIsOnAccent(.key))
        XCTAssertFalse(LiquidGlass.primaryInkIsOnAccent(.active))
        XCTAssertFalse(LiquidGlass.primaryInkIsOnAccent(.inactive))
    }

    /// One writer for the prominent label's ink: a bare `onAccent` on a
    /// primary-action label would skip the key-window rule.
    func testPrimaryActionLabelsGoThroughTheInkModifier() throws {
        let sources = try ThemeTokenTests.swiftSources()
        for name in ["Views/Common/SettingsSectionLink.swift", Self.home] {
            let file = try XCTUnwrap(sources.first { $0.path.hasSuffix(name) })
            let text = try String(contentsOf: file, encoding: .utf8)
            XCTAssertTrue(text.contains("primaryActionInk()"), name)
            XCTAssertFalse(text.contains(".foregroundStyle(CicadaTheme.onAccent)"), name)
        }
    }
}
