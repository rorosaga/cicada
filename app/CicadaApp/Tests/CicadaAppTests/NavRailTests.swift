import SwiftUI
import XCTest
@testable import CicadaApp

/// DR-22 — navigation is an icon rail: one cell per page in ⌘ order, state by brightness and one
/// neutral fill, a neutral numeral, no wordmark; a labelled sidebar one toggle away.
@MainActor
final class NavRailTests: XCTestCase {
    override func tearDown() { CicadaTheme.uiScale = 1.0; super.tearDown() }

    private func source(_ path: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(path) }, path)
        return try String(contentsOf: file, encoding: .utf8)
    }

    /// The rail's order IS its ⌘ order, so a new page joins at the end and no shortcut moves.
    func testTheRailIsAppTabInItsCommandOrder() {
        XCTAssertEqual(AppTab.allCases.map(RailItem.digit(for:)), Array(1...AppTab.allCases.count))
        XCTAssertEqual(RailItem.shortcut(for: .home), "⌘1")
        XCTAssertEqual(RailItem.shortcut(for: .inbox), "⌘6")
        XCTAssertEqual(RailItem.shortcut(for: .sources), "⌘7")
        XCTAssertEqual(RailItem.key(for: .graph), KeyEquivalent("2"))
    }

    func testTooltipsAndLabelsSayWhatTheCellIsDoing() {
        XCTAssertEqual(RailItem.tooltipTitle(.inbox, busy: false), "Inbox")
        XCTAssertEqual(RailItem.tooltipTitle(.sleep, busy: true), "Sleep · consolidating")
        XCTAssertEqual(RailItem.accessibilityLabel(.inbox, count: 6, busy: false), "Inbox, 6 pending")
        XCTAssertEqual(RailItem.accessibilityLabel(.sleep, count: 0, busy: true), "Sleep, consolidating")
        XCTAssertEqual(RailItem.accessibilityLabel(.graph, count: 0, busy: false), "Graph")
    }

    /// R-DS14 — 450 ms for the first; instantly while one shows or within a second of one hiding.
    func testTheFirstTooltipWaitsAndTheNextOpensInstantly() {
        let now = Date()
        XCTAssertEqual(RailTooltipTiming.delay(lastHiddenAt: nil, isShowing: false, now: now), CicadaMotion.railTooltipDelay)
        XCTAssertEqual(RailTooltipTiming.delay(lastHiddenAt: nil, isShowing: true, now: now), 0)
        XCTAssertEqual(RailTooltipTiming.delay(lastHiddenAt: now.addingTimeInterval(-0.5), isShowing: false, now: now), 0)
        XCTAssertEqual(RailTooltipTiming.delay(lastHiddenAt: now.addingTimeInterval(-1.5), isShowing: false, now: now),
                       CicadaMotion.railTooltipDelay)
        XCTAssertEqual(CicadaMotion.railTooltipDelay, 0.45, accuracy: 0.0001)
    }

    /// DR-70 — the rail and the labelled sidebar scale with the chrome (the G130 lesson).
    func testWidthsScaleWithUiScale() {
        CicadaTheme.uiScale = 1.0
        XCTAssertEqual(ShellMetrics.navWidth(labelled: false), 56)
        XCTAssertEqual(ShellMetrics.navWidth(labelled: true), 208)
        CicadaTheme.uiScale = 1.4
        XCTAssertEqual(ShellMetrics.navWidth(labelled: false), 78.4, accuracy: 0.05)
        XCTAssertEqual(ShellMetrics.navWidth(labelled: true), 291.2, accuracy: 0.05)
        XCTAssertEqual(ShellMetrics.labelledKey, "cicada.shell.labelledSidebar")
    }

    /// R-DS20 — the toolbar never disappears; its items hide under the Welcome and dim under Settings.
    func testChromeStateUnderAModal() {
        XCTAssertEqual(ShellChrome().itemOpacity, 1)
        XCTAssertFalse(ShellChrome().itemsDisabled)
        XCTAssertTrue(ShellChrome(welcomeShowing: true).itemsHidden)
        XCTAssertEqual(ShellChrome(welcomeShowing: true).itemOpacity, 0)
        XCTAssertEqual(ShellChrome(settingsOpen: true).itemOpacity, 0.4)
        XCTAssertTrue(ShellChrome(settingsOpen: true).itemsDisabled)
        XCTAssertFalse(ShellChrome(settingsOpen: true).itemsHidden)
    }

    func testTheRailIsGraphiteAndNeutral() throws {
        let text = try source("Views/Shell/NavRail.swift")
        XCTAssertTrue(text.contains(".background(CicadaTheme.bgRail)"))
        XCTAssertTrue(text.contains("CicadaTheme.bgSelected"), "selection is one neutral fill")
        XCTAssertTrue(text.contains("CicadaTheme.bgBadge"), "the Inbox numeral is neutral")
        XCTAssertTrue(text.contains(".iconHover(hovering:"), "glyphs acknowledge the pointer (owner, G137)")
        XCTAssertNil(text.range(of: #"iconHover\([^)]*selected:"#, options: .regularExpression),
                     "DR-64: no bounce on selection — a keyboard switch never animates")
        XCTAssertFalse(text.contains("Text(\"Cicada\")"), "DR-22: no wordmark")
        XCTAssertFalse(text.contains("withAnimation"), "DR-60/61: a page switch is instant")
    }

    func testTheSplitViewIsGone() throws {
        XCTAssertFalse(try ThemeTokenTests.swiftSources().contains { $0.lastPathComponent == "SidebarView.swift" })
        XCTAssertFalse(try source("ContentView.swift").contains("NavigationSplitView"))
        XCTAssertFalse(try source("Theme/LiquidGlass.swift").contains("SidebarChromeBackground"))
    }
}
