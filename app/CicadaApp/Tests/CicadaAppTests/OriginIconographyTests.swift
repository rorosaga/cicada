import XCTest
@testable import CicadaApp

/// G105 companion: every episode origin resolves to a mark — the installed
/// app's icon, a bundled PNG, or its SF Symbol — and to a product name. Exact
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
        // R-L4 — the four ids Track L's fetch finally gave a real mark to.
        // Each was drawing an SF Symbol (or, for Chrome, a hand-drawn glyph
        // wrong on four axes) while the vendor's own mark was one map row away.
        XCTAssertEqual(OriginIconography.logoName(for: "chatgpt-export"), "chatgpt")
        XCTAssertEqual(OriginIconography.logoName(for: "gemini-export"), "gemini")
        XCTAssertEqual(OriginIconography.logoName(for: "chrome-bookmark"), "chrome")
        XCTAssertEqual(OriginIconography.logoName(for: "rss"), "rss")
    }

    /// R2/R-L3 — Apple's marks are never redistributed, so these two origins
    /// resolve *installed app icon → SF Symbol* with no PNG rung at all. A
    /// `logoName` here would demand a file the ruling forbids.
    func testAppleOriginsNeverNameABundledLogo() {
        XCTAssertNil(OriginIconography.logoName(for: "safari-bookmark"))
        XCTAssertNil(OriginIconography.logoName(for: "safari-tab"))
        XCTAssertNil(OriginIconography.logoName(for: "apple-notes"))
        XCTAssertNil(OriginIconography.logoName(for: "unknown"))
    }

    /// T1 (R-L7) — every id in the map has a file, driven from the exported
    /// list rather than a hand-kept array: the old version iterated 14
    /// hardcoded strings, so a case added to the switch was silently
    /// uncovered. Adding a case without adding it to `allKnownOrigins` is the
    /// bug this pair is here to make loud.
    func testEveryDeclaredLogoExistsInTheBundle() {
        XCTAssertFalse(OriginIconography.allKnownOrigins.isEmpty)
        for origin in OriginIconography.allKnownOrigins {
            guard let name = OriginIconography.logoName(for: origin) else { continue }
            XCTAssertTrue(LogoImage.exists(name: name), "\(origin) → \(name).png is not bundled")
        }
    }

    /// R-L4 — the ids the audit found with no case at all: they read as
    /// "Gemini-export" and "Saved-link" (a `.capitalized` id) under a generic
    /// `tray`, on a Sources card the backend ships today
    /// (`source_overview.CATALOG`).
    func testTheOriginsThatHadNoCaseNowReadAsProducts() {
        XCTAssertEqual(OriginIconography.label(for: "gemini-export"), "Gemini export")
        XCTAssertEqual(OriginIconography.label(for: "saved-link"), "Saved link")
        XCTAssertNotEqual(OriginIconography.symbol(for: "gemini-export"), "tray")
        XCTAssertNotEqual(OriginIconography.symbol(for: "saved-link"), "tray")
    }

    /// The audit found nine unreachable `case` labels (Swift takes the first
    /// match): `codex`/`claude-desktop`/`cursor` a second time in `label`,
    /// `codex`/`cursor` again in `symbol` and `color`, and `claude-desktop`
    /// again in each. Harmless today because a PNG wins for all three — but
    /// unreachable code that tells the next editor a lie.
    ///
    /// `gemini-cli` is NOT one of them: it appears exactly once in `symbol`
    /// and once in `color`, so `terminal` is its live answer and the cleanup
    /// must keep it reachable rather than folding it into the `bubble` list.
    func testTheSecondCopyOfEachDuplicatedCaseIsGone() {
        XCTAssertEqual(OriginIconography.symbol(for: "gemini-cli"), "terminal")
        XCTAssertEqual(OriginIconography.symbol(for: "codex"), "bubble.left.and.bubble.right")
        XCTAssertEqual(OriginIconography.label(for: "codex"), "Codex")
        XCTAssertEqual(OriginIconography.label(for: "cursor"), "Cursor")
    }

    /// R-L1 — the mark for a browser/Apple-app origin is the icon of the app
    /// actually installed on this Mac. Sound by construction: Cicada only
    /// lists these channels because it reads that app's files off this Mac.
    /// The MAP is asserted, never the resolution — the suite must pass on a
    /// machine with no Chrome (R6).
    func testOriginsBackedByAnInstalledAppDeclareItsBundleId() {
        XCTAssertEqual(OriginIconography.appBundleId(for: "chrome-bookmark"), "com.google.Chrome")
        XCTAssertEqual(OriginIconography.appBundleId(for: "safari-bookmark"), "com.apple.Safari")
        XCTAssertEqual(OriginIconography.appBundleId(for: "safari-tab"), "com.apple.Safari")
        XCTAssertEqual(OriginIconography.appBundleId(for: "apple-notes"), "com.apple.Notes")
        XCTAssertNil(OriginIconography.appBundleId(for: "claude-code"))
        XCTAssertNil(OriginIconography.appBundleId(for: "telegram"))
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
