import SwiftUI
import XCTest
@testable import CicadaApp

/// Track I T6 (design §6.2) — every number appears once: while Getting started
/// shows "Read what came in", TODAY omits its waiting clause.
final class HomeLayoutTests: XCTestCase {
    func testTheWaitingNumberAppearsOnce() {
        XCTAssertFalse(HomeLayout.showsWaitingInToday(gettingStartedVisible: true, hasRunBefore: false))
        XCTAssertTrue(HomeLayout.showsWaitingInToday(gettingStartedVisible: true, hasRunBefore: true))
        XCTAssertTrue(HomeLayout.showsWaitingInToday(gettingStartedVisible: false, hasRunBefore: false))
    }

    /// R-HS2, R-HS6 — the D-Home mock's column, field and gaps.
    func testTheColumnAndTheFieldAreTheMocks() {
        XCTAssertEqual(HomeLayout.columnWidth, 760, "DR-36 — a text column is at most 760 pt")
        XCTAssertEqual(HomeLayout.fieldWidth, 640, "the approved mock's field (§10's 560 lost to it, R-HS2)")
        XCTAssertEqual(HomeLayout.blockGap, 24)
        XCTAssertEqual(HomeLayout.labelGap, 6)
    }

    /// Owner 2026-10-06 — "i dont like how the boxes get clipped with the portion of the search bar." The field sat
    /// outside the blocks' scroll view, whose top edge ran flush under it, so a scrolled card was cut mid-border. One
    /// scroll view now carries the headline, the field and the blocks, and the first block sits one block gap under the
    /// field (never the focus card's 28 pt padding).
    func testTheFieldAndTheBlocksScrollTogether() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Home/HomeView.swift") })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertEqual(text.components(separatedBy: "ScrollView {").count - 1, 1, "one scroll view for the page")
        let scroll = try XCTUnwrap(text.range(of: "ScrollView {"))
        let title = try XCTUnwrap(text.range(of: "PageTitle(Copy.homeHeadline)"))
        let field = try XCTUnwrap(text.range(of: "fieldColumn(showsResults:"))
        let blocks = try XCTUnwrap(text.range(of: "GettingStartedCard(selectedTab:"))
        XCTAssertLessThan(scroll.lowerBound, title.lowerBound, "the headline scrolls with the page")
        XCTAssertLessThan(scroll.lowerBound, field.lowerBound, "the field scrolls with the page, so nothing is cut under it")
        XCTAssertLessThan(field.lowerBound, blocks.lowerBound)
        XCTAssertFalse(text.contains(".padding(.top, CicadaTheme.spacingCard)"), "the field-to-first-block gap is the block gap")
        XCTAssertTrue(text.contains("HomeLayout.fieldToFirstBlock"))
        XCTAssertEqual(HomeLayout.fieldToFirstBlock, HomeLayout.blockGap)
    }

    /// Fix round 1 — the page scroll never disables scrolling: `scrollDisabled` is inherited, and a disable on the page
    /// could reach the results' and Ask's own scroll views. A probe sits directly under the page's policy — with no scroll
    /// view between to reset the value — and reads the environment those inner scroll views read. The control proves the
    /// probe sees a disable when there is one. (Measured here: a `ScrollView` resets `isScrollEnabled` to true for its own
    /// content, so the old outer disable most likely never reached them; the policy no longer depends on that.)
    @MainActor
    func testThePinnedPageLeavesInnerScrollViewsScrollable() throws {
        final class Seen { var enabled: [Bool] = [] }
        struct Probe: View {
            let seen: Seen
            @Environment(\.isScrollEnabled) private var enabled
            var body: some View {
                seen.enabled.append(enabled)
                return Color.clear.frame(width: 10, height: 10)
            }
        }
        for pinned in [true, false] {
            let seen = Seen()
            _ = ImageRenderer(content: Probe(seen: seen).modifier(HomePageScroll(pinned: pinned))).nsImage
            XCTAssertEqual(seen.enabled, [true], "pinned: \(pinned) — the results and Ask still scroll")
        }
        let control = Seen()
        _ = ImageRenderer(content: Probe(seen: control).scrollDisabled(true)).nsImage
        XCTAssertEqual(control.enabled, [false], "the probe reads the inherited value")

        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Home/HomeView.swift") })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertFalse(text.contains(".scrollDisabled("), "a disable could reach the results' own scroll view")
        XCTAssertTrue(text.contains(".modifier(HomePageScroll(pinned: showsResults))"))
        XCTAssertTrue(text.contains(".softTopScrollEdge()"), "the page eases out under the titlebar band on macOS 26")
    }

    /// DR-60 — typing and Esc are what flip the results in and out, so the swap never animates.
    func testTheResultsSwapIsInstant() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Home/HomeView.swift") })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertNil(text.range(of: #"\.animation\([^\n]*value: showsResults"#, options: .regularExpression))
        XCTAssertFalse(text.contains("withAnimation"))
        XCTAssertFalse(text.contains(".transition("), "a transition with no animation is dead weight")
    }

    /// The soft edge is one helper behind the same SDK guard as the glass file (the macOS 14 build).
    func testTheSoftTopEdgeIsOneGatedHelper() throws {
        let sources = try ThemeTokenTests.swiftSources()
        let home = "Theme/ScrollEdge.swift"
        let file = try XCTUnwrap(sources.first { $0.path.hasSuffix(home) })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(text.contains("#if canImport(SwiftUI, _version: 7.0)"))
        XCTAssertTrue(text.contains("if #available(macOS 26, *)"))
        for other in sources where !other.path.hasSuffix(home) {
            let code = try String(contentsOf: other, encoding: .utf8).components(separatedBy: .newlines)
                .filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("//") }
            XCTAssertFalse(code.contains { $0.contains(".scrollEdgeEffectStyle(") }, other.lastPathComponent)
        }
    }

    /// G125 R10, R-HS3 — Home links to the Sleep page and never starts a cycle.
    func testHomeNeverStartsACycle() throws {
        let files = try ThemeTokenTests.swiftSources()
        for suffix in ["Views/Home/HomeView.swift", "Views/Home/HomeSections.swift"] {
            let file = try XCTUnwrap(files.first { $0.path.hasSuffix(suffix) })
            let text = try String(contentsOf: file, encoding: .utf8)
            for needle in ["triggerManually", "Copy.consolidateNow", "PrimaryActionButton("] {
                XCTAssertFalse(text.contains(needle), "\(suffix) — \(needle)")
            }
        }
    }
}
