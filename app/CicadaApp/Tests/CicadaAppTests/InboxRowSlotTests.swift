import XCTest
import AppKit
@testable import CicadaApp

/// QA 2026-10-16 — the Inbox's STATE 0 rows (and Home's Needs you, which reuses them) printed "tod…" for "today":
/// the age slot was 30 pt and the word measures about 31 at the row's 12 pt meta font.
final class InboxRowSlotTests: XCTestCase {
    func testEveryCompactAgeFitsTheRowSlot() {
        let font = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .regular)
        let ages = [InboxAge.compact(days: 0), InboxAge.compact(days: 13), InboxAge.compact(days: 59),
                    InboxAge.compact(days: 350), InboxAge.compact(days: 36_500), "—"]
        for age in ages {
            let width = (age as NSString).size(withAttributes: [.font: font]).width
            XCTAssertLessThanOrEqual(width, InboxRowAge.slotWidth, "“\(age)” is \(width) pt")
        }
    }

    /// The row draws the age in that slot, not a literal.
    func testTheRowUsesTheSlot() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.path.hasSuffix("Views/Inbox/InboxQuestionList.swift")
        })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(text.contains("scaled(InboxRowAge.slotWidth)"))
    }

    /// The kind glyphs differ in width; one fixed slot keeps every question starting at the same x.
    func testTheKindGlyphHasOneSlot() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Inbox/OptionRow.swift") })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(text.contains(".frame(width: CicadaTheme.scaled(Self.slotWidth))"))
        XCTAssertGreaterThanOrEqual(KindGlyph.slotWidth, 14, "narrower than the 14 pt list glyph")
    }
}
