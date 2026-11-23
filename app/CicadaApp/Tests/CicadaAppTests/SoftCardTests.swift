import SwiftUI
import XCTest
@testable import CicadaApp

/// Owner 2026-11-23 (DESIGN_RULES §9, "the soft-card look reaches the sidebar and the lists"): the sidebar's groups keep
/// the ⌘ order, and every card of the app is the one `softCard` chrome rather than another spelling of it.
@MainActor
final class SoftCardTests: XCTestCase {
    private func source(_ path: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(path) }, path)
        return try String(contentsOf: file, encoding: .utf8)
    }

    /// Grouping is by space and never moves a page: read in order, the groups are the rail's own (⌘) order.
    func testTheSidebarGroupsKeepTheCommandOrder() {
        let shown = AppTab.shown(tracesPage: true)
        let groups = ShellMetrics.navGroups(shown)
        XCTAssertEqual(groups.flatMap { $0 }, shown)
        XCTAssertEqual(groups.count, 3)
        // Hidden pages leave a group shorter, an empty one draws no gap.
        let noTraces = ShellMetrics.navGroups(AppTab.shown(tracesPage: false))
        XCTAssertEqual(noTraces.flatMap { $0 }, AppTab.shown(tracesPage: false))
        XCTAssertTrue(noTraces.allSatisfy { !$0.isEmpty })
        XCTAssertEqual(ShellMetrics.navGroups([.home]), [[.home]])
    }

    /// One card, one set of tokens: the older chromes forward to `softCard` and no view re-spells the fill + ring pair.
    func testNoViewSpellsTheCardChromeItself() throws {
        XCTAssertTrue(try source("Views/Common/OriginCard.swift").contains("softCard("))
        XCTAssertTrue(try source("Views/Graph/PageCards.swift").contains("softCard("))
        let fill = "fill(CicadaTheme.bgFocus))"
        for file in try ThemeTokenTests.swiftSources() where file.path.contains("/Views/") {
            let text = try String(contentsOf: file, encoding: .utf8)
            XCTAssertFalse(text.contains("cornerRadius).fill(CicadaTheme.bgFocus)"),
                           "\(file.lastPathComponent) draws its own card; use .softCard (\(fill))")
        }
    }

    /// Depth is a ring and the open card is the neutral selected fill: the chrome names no shadow and no accent fill
    /// outside `OriginCard`'s `current` tone.
    func testTheCardChromeHasNoShadowAndNoAccentSelection() throws {
        let text = try source("Theme/SoftCard.swift")
        XCTAssertFalse(text.contains(".shadow("))
        XCTAssertTrue(text.contains("bgSelected"))
    }
}
