import XCTest
@testable import CicadaApp

/// DR-23 / DR-46 / DR-60 — the titlebar is a command bar; it opens the one global search; the
/// palette arrives in one frame under it; one `?` per window.
final class CommandBarTests: XCTestCase {
    override func tearDown() { CicadaTheme.uiScale = 1.0; super.tearDown() }

    private func source(_ path: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(path) }, path)
        return try String(contentsOf: file, encoding: .utf8)
    }

    func testTheBarIsTheToolbarsCentreAndTheHelpItsRightEdge() throws {
        let toolbar = try source("Views/Shell/ShellToolbar.swift")
        XCTAssertTrue(toolbar.contains("placement: .principal"))
        XCTAssertTrue(toolbar.contains("CommandBar()"))
        XCTAssertTrue(toolbar.contains("placement: .primaryAction"))
        XCTAssertTrue(toolbar.contains("TitlebarHelpButton(content: help)"))
    }

    /// A click anywhere on the bar outside the bank selector opens the palette — through the
    /// router, the same door ⌘K uses (FindCommands keeps the shortcut; HiddenShortcutLintTests).
    func testTheBarOpensThePaletteThroughTheRouter() throws {
        XCTAssertTrue(try source("Views/Shell/CommandBar.swift").contains("router.requestPalette()"))
    }

    func testTheBarsSizeScales() {
        CicadaTheme.uiScale = 1.0
        XCTAssertEqual(CicadaTheme.scaled(ShellMetrics.commandBarWidth), 520)
        XCTAssertEqual(CicadaTheme.scaled(ShellMetrics.commandBarHeight), 32)
        CicadaTheme.uiScale = 1.4
        XCTAssertEqual(CicadaTheme.scaled(ShellMetrics.commandBarWidth), 728)
        XCTAssertLessThanOrEqual(CicadaTheme.scaled(ShellMetrics.commandBarHeight), 52, "still inside AppKit's titlebar")
    }

    /// R-DS17 — 640 pt, anchored 4 pt under the titlebar, clamped inside a narrow window.
    func testThePaletteIsAnchoredUnderTheBar() {
        CicadaTheme.uiScale = 1.0
        XCTAssertEqual(FindPaletteLayout.width(container: 1440), 640)
        XCTAssertEqual(FindPaletteLayout.width(container: 600), 552, "600 − 2 × 24")
        XCTAssertEqual(FindPaletteLayout.top, CicadaTheme.spacingXS)
        XCTAssertEqual(FindPaletteLayout.height(container: 848), 560)
        XCTAssertEqual(FindPaletteLayout.height(container: 500), 360)
    }

    /// DR-60 — ⌘K never animates: the palette appears and leaves in one frame.
    func testThePaletteArrivesInOneFrame() throws {
        let content = try source("ContentView.swift")
        XCTAssertFalse(content.contains("paletteIn"))
        XCTAssertFalse(content.contains("paletteOut"))
        XCTAssertFalse(content.contains("scale(scale: 0.98"))
        XCTAssertFalse(try source("Theme/CicadaMotion.swift").contains("palette"))
        XCTAssertFalse(try source("Views/Find/FindPalette.swift").contains("liquidGlass("), "R-DS17: opaque, not glass")
    }

    /// DR-23 — one `?`, in the titlebar, answering for the visible page; no page floats its own.
    func testOneHelpPerWindow() throws {
        var floating: [String] = []
        var titlebar = 0
        for file in try ThemeTokenTests.swiftSources() {
            let text = try String(contentsOf: file, encoding: .utf8)
            if text.contains("TopBarControls(") { floating.append(file.lastPathComponent) }
            titlebar += text.components(separatedBy: "TitlebarHelpButton(content:").count - 1
        }
        XCTAssertEqual(floating, [])
        XCTAssertEqual(titlebar, 1)
        XCTAssertEqual(HelpContent.page(.sleep), .howSleepWorks)
        // R-DI17 — the Inbox's `?` answers for the Inbox (its subtitle and key map).
        XCTAssertEqual(HelpContent.page(.inbox), .inbox)
        // R-DG6 — the Graph's `?` answers for the Graph (its keys and gestures).
        XCTAssertEqual(HelpContent.page(.graph), .graph)
        XCTAssertEqual(HelpContent.page(.projects), .projects)
        for tab in AppTab.allCases where ![.sleep, .inbox, .graph, .clusters, .feed, .sources, .projects].contains(tab) {
            XCTAssertEqual(HelpContent.page(tab), .aboutCicada, tab.rawValue)
        }
    }

    /// DR-46 — the command bar is the global search; the Graph's own Search button retired.
    func testTheGraphSearchButtonRetired() throws {
        XCTAssertFalse(try source("ContentView.swift").contains("struct SearchButton"))
    }
}
