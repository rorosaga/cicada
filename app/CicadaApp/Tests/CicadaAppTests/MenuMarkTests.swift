import XCTest
import AppKit
@testable import CicadaApp

/// QA 2026-10-16 — a `.menu` `Picker` draws its item's image at the `NSImage`'s own size: the API-key card's provider
/// picker (Who reads in onboarding, Settings → Engines) drew a `LogoImage`'s full-size PNG as a ~300 pt OpenAI mark
/// over the page. A menu mark is an `NSImage` already carrying its menu size.
@MainActor
final class MenuMarkTests: XCTestCase {
    func testEveryKeyProviderMarkIsSizedForAMenu() throws {
        let ids = ["byok-openai", "byok-anthropic", "byok-gemini", "byok-xai", "byok-groq", "byok-mistral"]
        var checked = 0
        for id in ids {
            guard let name = ConnectionMark.logoName(connectionId: id), LogoImage.exists(name: name) else { continue }
            let image = try XCTUnwrap(LogoImage.menuImage(name: name, size: 14), id)
            XCTAssertEqual(image.size, NSSize(width: 14, height: 14), id)
            checked += 1
        }
        XCTAssertGreaterThan(checked, 0, "no provider mark was checked")
    }

    func testAMarkThatDoesNotShipHasNoMenuImage() {
        XCTAssertNil(LogoImage.menuImage(name: "", size: 14))
        XCTAssertNil(LogoImage.menuImage(name: "no-such-mark-anywhere", size: 14))
    }

    /// The menu copy never resizes the cached image another surface draws at 28 pt.
    func testTheMenuCopyLeavesTheCachedImageAlone() throws {
        let name = try XCTUnwrap(ConnectionMark.logoName(connectionId: "byok-openai"))
        let first = try XCTUnwrap(LogoImage.menuImage(name: name, size: 14))
        let second = try XCTUnwrap(LogoImage.menuImage(name: name, size: 20))
        XCTAssertEqual(first.size.width, 14)
        XCTAssertEqual(second.size.width, 20)
    }

    /// The provider picker must not hand AppKit a SwiftUI `LogoImage` again.
    func testTheProviderPickerUsesTheMenuImage() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.path.hasSuffix("Views/Settings/EngineChooser.swift")
        })
        let text = try String(contentsOf: file, encoding: .utf8)
        let start = try XCTUnwrap(text.range(of: "private func providerMark("))
        let body = text[start.upperBound...].prefix(600)
        XCTAssertTrue(body.contains("LogoImage.menuImage("), "the provider picker's mark is not menu-sized")
        XCTAssertFalse(body.contains("LogoImage(name:"), "a SwiftUI LogoImage in a menu label draws at full size")
    }
}
