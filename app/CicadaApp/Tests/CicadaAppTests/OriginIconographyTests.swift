import XCTest
@testable import CicadaApp

/// G105 companion: every episode origin resolves to a mark — a bundled PNG,
/// a drawn browser glyph, or its SF Symbol — and to a product name. Exact
/// values, so a renamed asset or a dropped case fails here, not on screen.
final class OriginIconographyTests: XCTestCase {

    func testHarnessOriginsHaveBundledLogos() {
        XCTAssertEqual(OriginIconography.logoName(for: "claude-code"), "claude-code")
        XCTAssertEqual(OriginIconography.logoName(for: "mcp"), "claude-code")
        XCTAssertEqual(OriginIconography.logoName(for: "codex"), "codex")
        XCTAssertEqual(OriginIconography.logoName(for: "claude-export"), "claude-desktop")
        XCTAssertEqual(OriginIconography.logoName(for: "telegram"), "telegram")
        XCTAssertEqual(OriginIconography.logoName(for: "pinterest"), "pinterest")
        XCTAssertEqual(OriginIconography.logoName(for: "reddit-saved"), "reddit")
        XCTAssertEqual(OriginIconography.logoName(for: "x-bookmarks"), "x")
        XCTAssertEqual(OriginIconography.logoName(for: "linkedin-saved"), "linkedin")
        XCTAssertEqual(OriginIconography.logoName(for: "tiktok-saved"), "tiktok")
        XCTAssertEqual(OriginIconography.logoName(for: "instagram-saved"), "instagram")
        XCTAssertEqual(OriginIconography.logoName(for: "youtube-playlist"), "youtube")
    }

    /// No `chatgpt.png` is bundled — the export origin must fall through to
    /// its SF Symbol rather than name an asset that does not exist.
    func testOriginsWithoutABundledLogoReturnNil() {
        XCTAssertNil(OriginIconography.logoName(for: "chatgpt-export"))
        XCTAssertNil(OriginIconography.logoName(for: "rss"))
        XCTAssertNil(OriginIconography.logoName(for: "unknown"))
        XCTAssertNil(OriginIconography.logoName(for: "safari-bookmark"))
    }

    /// Every name the map returns must exist in the bundle — the map is the
    /// only thing standing between a typo and a blank mark.
    func testEveryDeclaredLogoExistsInTheBundle() {
        let origins = ["claude-code", "mcp", "codex", "claude-export", "telegram", "pinterest",
                       "reddit-saved", "x-bookmarks", "linkedin-saved", "tiktok-saved",
                       "instagram-saved", "youtube-playlist", "cursor", "gemini-cli"]
        for origin in origins {
            guard let name = OriginIconography.logoName(for: origin) else { continue }
            XCTAssertTrue(LogoImage.exists(name: name), "\(origin) → \(name).png is not bundled")
        }
    }

    func testBrowsersUseDrawnGlyphs() {
        XCTAssertEqual(OriginIconography.brandGlyph(for: "safari-bookmark"), .safari)
        XCTAssertEqual(OriginIconography.brandGlyph(for: "safari-tab"), .safari)
        XCTAssertEqual(OriginIconography.brandGlyph(for: "chrome-bookmark"), .chrome)
        XCTAssertNil(OriginIconography.brandGlyph(for: "claude-code"))
    }

    func testProductLabelsForHarnessOrigins() {
        XCTAssertEqual(OriginIconography.label(for: "claude-code"), "Claude Code")
        XCTAssertEqual(OriginIconography.label(for: "codex"), "Codex")
        XCTAssertEqual(OriginIconography.label(for: "claude-desktop"), "Claude Desktop")
        XCTAssertEqual(OriginIconography.label(for: "cursor"), "Cursor")
        XCTAssertEqual(OriginIconography.label(for: "gemini-cli"), "Gemini CLI")
        // Byte-for-byte: the Activity origins strip keys on this label.
        XCTAssertEqual(OriginIconography.label(for: "mcp"), "MCP")
    }
}
