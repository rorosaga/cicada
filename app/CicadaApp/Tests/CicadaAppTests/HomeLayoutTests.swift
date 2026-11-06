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

    /// ROR-118 (Home) — the headline leads at 34 pt; round 2: it starts a fifth of the viewport down, between the room
    /// pages' 24 pt inset and 150 pt; Today and Last read are rows with a 2 pt gap, not cards.
    func testTheHeadlineLeadsAndTheLowerRowsAreQuiet() {
        XCTAssertEqual(HomeLayout.headlineSize, 34)
        XCTAssertEqual(HomeLayout.headlineTop(viewportHeight: 100), 24, "never above the room pages' inset")
        XCTAssertEqual(HomeLayout.headlineTop(viewportHeight: 600), 102, "round 3: 17 %, above the worm")
        XCTAssertEqual(HomeLayout.headlineTop(viewportHeight: 2000), 140, "never past 140 pt")
        XCTAssertEqual(HomeLayout.greeterCell, 3, "round 4 — a whole 3 points per art pixel, crisp")
        XCTAssertEqual(HomeLayout.greeterCell, HomeLayout.greeterCell.rounded(), "never a fractional pixel")
        XCTAssertEqual(HomeLayout.greeterInk, CGRect(x: 4, y: 3, width: 56, height: 45), "the pixels every mood draws")
        XCTAssertEqual(HomeLayout.pulseGap, 2)
        XCTAssertLessThan(HomeLayout.pulseGap, HomeLayout.blockGap)
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
        let title = try XCTUnwrap(text.range(of: "PageTitle(Copy.homeHeadline"))
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
            for needle in ["triggerManually", "Copy.consolidateNow"] {
                XCTAssertFalse(text.contains(needle), "\(suffix) — \(needle)")
            }
            // Round 5 — Home's one accent primary is Answer (DR-5 (2)); never a second.
            let primaries = text.components(separatedBy: "PrimaryActionButton(").count - 1
            XCTAssertLessThanOrEqual(primaries, 1, suffix)
        }
    }

    /// ROR-118 round 2 — one column (the cards and rows sit on the field's 640 pt edges), a lead card of the question and
    /// one foot line, rows with no tile and no strip of marks, and the titlebar's search quiet on Home alone.
    /// Round 5 — the status line says "today" once (the last read drops its own), and "Today" only goes when it is the
    /// leading day word of a read with a time.
    func testWithoutTodayDropsOnlyTheLeadingDayWord() {
        XCTAssertEqual(HomeFigures.withoutToday("Today 2:07 PM"), "2:07 PM")
        XCTAssertEqual(HomeFigures.withoutToday("Yesterday 11:40 PM"), "Yesterday 11:40 PM")
        XCTAssertEqual(HomeFigures.withoutToday("Today"), "Today")
        XCTAssertEqual(HomeFigures.withoutToday("Oct 3 7:27 AM"), "Oct 3 7:27 AM")
    }

    func testRoundTwoColumnCardRowsAndQuietTitlebar() throws {
        let files = try ThemeTokenTests.swiftSources()
        func text(_ suffix: String) throws -> String {
            try String(contentsOf: XCTUnwrap(files.first { $0.path.hasSuffix(suffix) }), encoding: .utf8)
        }
        let view = try text("Views/Home/HomeView.swift")
        XCTAssertFalse(view.contains("HomeLayout.columnWidth"), "the blocks share the field's column")
        let sections = try text("Views/Home/HomeSections.swift")
        XCTAssertFalse(sections.contains("OriginMark("), "no strip of marks on a row; the origins are its hover")
        XCTAssertFalse(sections.contains("bgOption"), "a row's glyph has no tile")
        XCTAssertFalse(sections.contains("Text(row.reason"), "the reason is the card's hover, not more small type")
        let bar = try text("Views/Shell/CommandBar.swift")
        XCTAssertTrue(bar.contains("router.requestPalette()"), "the bar still opens the palette on every other page")
        let content = try text("ContentView.swift")
        XCTAssertTrue(content.contains("quietSearch: selectedTab == .home && !tour.spotlights(.commandBar)"))
        XCTAssertTrue(try text("Views/Find/FindPanelBody.swift").contains("if placement == .page {\n                FindModeSwitch("))
    }
}
