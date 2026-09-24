import XCTest
@testable import CicadaApp

/// R-AG8 (owner addendum 2) — Claude Code is the Claude mark plus an app-drawn `>_` badge; the Claude app is the
/// plain Claude mark; no mark file is edited, and the two byte-identical rasters are gone.
final class BrandMarkTests: XCTestCase {
    func testClaudeCodeIsTheClaudeMarkWithATerminalBadge() {
        XCTAssertEqual(BrandMark.composition(for: "claude-code"), .init(file: "claude", badge: .terminal))
        XCTAssertEqual(BrandMark.composition(for: "claude-desktop"), .init(file: "claude", badge: nil))
        XCTAssertEqual(BrandMark.composition(for: "codex"), .init(file: "codex", badge: nil))
    }

    func testTheLogicalNamesStillResolveButTheirRastersAreGone() throws {
        XCTAssertTrue(LogoImage.exists(name: "claude-code"))
        XCTAssertTrue(LogoImage.exists(name: "claude-desktop"))
        XCTAssertNil(Bundle.cicadaResources.cicadaResource("claude-code", ext: "png", in: "logos"))
        XCTAssertNil(Bundle.cicadaResources.cicadaResource("claude-desktop", ext: "png", in: "logos"))
        XCTAssertFalse(LogoImage.exists(name: ""))
    }

    /// `resolvedName` answers with the FILE it loads, so the task key and the image cache stay keyed by bytes.
    func testTheResolvedNameIsTheFileNotTheLogicalName() {
        XCTAssertEqual(LogoImage.resolvedName(for: "claude-code"), "claude")
        XCTAssertEqual(LogoImage.resolvedName(for: "claude-desktop"), "claude")
        XCTAssertNil(LogoImage.resolvedName(for: ""))
    }

    func testTheBadgeIsHalfTheMarkAndNeverUnreadable() {
        XCTAssertEqual(BrandMark.badgeSide(for: 40), 20)
        XCTAssertEqual(BrandMark.badgeSide(for: 12), 7)
    }

    func testOpenCodeAndOpenRouterShipTheirMarks() {
        for name in ["opencode", "opencode-dark", "openrouter", "openrouter-dark"] {
            XCTAssertNotNil(Bundle.cicadaResources.cicadaResource(name, ext: "png", in: "logos"), name)
        }
        XCTAssertEqual(ConnectionMark.logoName(connectionId: "byok-openrouter"), "openrouter")
        XCTAssertEqual(EngineOption.logoName(for: "openrouter"), "openrouter")
    }
}
