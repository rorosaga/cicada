import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// The owner's ruling for the Inbox's kind tabs (2026-10-16): when they do not fit — 1200 pt with the Reader open, and
/// 1100 — All and the selected kind stay on the row and the rest go under "More", with their counts. Never a truncated
/// label ("Conf… 2 · Clarif… 1 · Follo…" in the QA capture).
@MainActor
final class OverflowTextTabsTests: XCTestCase {
    override func setUp() { CicadaTheme.uiScale = 1 }

    /// Every kind the demo can hold, with counts: the row the QA saw truncate.
    private let tabs: [TextTab<InboxKind>] = [TextTab(id: nil, label: Copy.Inbox.all, count: 12)]
        + InboxTabs.order.map { TextTab(id: $0, label: $0.label, count: 2) }

    func test_allAndTheSelectedKindStayAndTheRestFold() {
        let pinned = OverflowTabs.pinned(tabs, selection: .clarification)
        XCTAssertEqual(pinned.map(\.id), [nil, .clarification])
        let folded = OverflowTabs.folded(tabs, selection: .clarification)
        XCTAssertEqual(folded.map(\.id), InboxTabs.order.filter { $0 != .clarification }.map(Optional.some))
        XCTAssertTrue(folded.allSatisfy { $0.count != nil }, "the menu lists each kind with its count")
        XCTAssertEqual(OverflowTabs.pinned(tabs, selection: nil).map(\.id), [nil], "with All selected, only All stays")
        XCTAssertEqual(OverflowTabs.folded(tabs, selection: nil).count, InboxTabs.order.count)
        XCTAssertEqual(Set((pinned + folded).map(\.id)), Set(tabs.map(\.id)), "no tab is lost")
    }

    /// At the width the QA measured, the full row cannot fit, and the folded row — All, the selected kind and More —
    /// fits with room to spare, beside an eyebrow that keeps every word.
    func test_theFoldedRowFitsWhereTheFullRowTruncated() {
        let selection: InboxKind? = .possibleDuplicateKind
        let full = Self.ideal(TextTabs(tabs: tabs, selection: .constant(selection)))
        let folded = Self.ideal(HStack(spacing: 2) {
            TextTabs(tabs: OverflowTabs.pinned(tabs, selection: selection), selection: .constant(selection))
            Text("More ⌄").font(CicadaTheme.metaMediumFont).padding(.horizontal, 9)
        })
        let eyebrow = Self.ideal(Text(Eyebrow.text("Inbox", "1 of 12", InboxKind.mergeSuggestion.label))
            .font(CicadaTheme.metaMediumFont))
        // 1200 pt with the Reader open: the list column's eyebrow row is about 520 pt wide, less 2 × 24 pt of padding.
        let row: CGFloat = 520 - 48
        XCTAssertGreaterThan(full + eyebrow + 12, row, "the case is real: every tab does not fit")
        XCTAssertLessThanOrEqual(folded + eyebrow + 12, row, "All, the selected kind and More fit")
    }

    /// The row lays the adaptive tabs out in the width left after the eyebrow, so `ViewThatFits` chooses against the
    /// real space and the eyebrow is never what gives way.
    func test_theEyebrowRowGivesTheTabsTheRestOfTheRow() {
        let row = EyebrowRow(eyebrow: "Inbox · 12 pending", horizontalPadding: 24, adaptiveTrailing: true) {
            OverflowTextTabs(tabs: self.tabs, selection: .constant(InboxKind.conflict))
        }
        let size = NSHostingController(rootView: row).sizeThatFits(in: CGSize(width: 480, height: 200))
        XCTAssertLessThanOrEqual(size.width, 480.5, "nothing runs past the row")
    }

    private static func ideal(_ view: some View) -> CGFloat {
        NSHostingView(rootView: view.fixedSize()).fittingSize.width
    }
}

private extension InboxKind {
    static var possibleDuplicateKind: InboxKind { .mergeSuggestion }
}
