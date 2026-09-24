import SwiftUI
import XCTest
@testable import CicadaApp

/// DR-18 — the cited span, defined once for the Reader and the Inbox (DS-2) to adopt.
final class CitedSpanTests: XCTestCase {
    override func tearDown() { CicadaTheme.mode = .dark; super.tearDown() }

    func testTheWashIsOnePointProudAndTheUnderlineSitsFourBelow() {
        let run = CGRect(x: 10, y: 20, width: 50, height: 18)
        XCTAssertEqual(CitedSpan.washRect(for: run), CGRect(x: 9, y: 19, width: 52, height: 20))
        XCTAssertEqual(CitedSpan.underlineRect(for: run), CGRect(x: 9, y: 41, width: 52, height: 2))
        XCTAssertEqual(CitedSpan.cornerRadius, 4)
        XCTAssertEqual(CitedSpan.underlineThickness, 2)
        XCTAssertEqual(CitedSpan.underlineOffset, 4)
    }

    /// macOS 14's fallback: the current span is washed and underlined, the others only washed
    /// softly, plain text is untouched.
    func testTheFallbackMarksOnlyWhatItShould() {
        let s = CitedSpan.fallback([.init(text: "before ", mark: .plain), .init(text: "span", mark: .current),
                                    .init(text: " other", mark: .other)])
        let runs = Array(s.runs).map(\.attributes)
        XCTAssertEqual(runs.count, 3)
        XCTAssertNil(runs[0].swiftUI.backgroundColor)
        XCTAssertNotNil(runs[1].swiftUI.backgroundColor)
        XCTAssertNotNil(runs[1].swiftUI.underlineStyle)
        XCTAssertNotNil(runs[2].swiftUI.backgroundColor)
        XCTAssertNil(runs[2].swiftUI.underlineStyle)
        XCTAssertNotEqual(runs[1].swiftUI.backgroundColor, runs[2].swiftUI.backgroundColor, "wash vs washSoft")
    }

    /// R-DI11 / DR-57 — a mention found by name is emphasised and never washed; `reveal` fades the wash.
    func testAMentionIsEmphasisedNotWashedAndRevealScalesTheWash() {
        let s = CitedSpan.fallback([.init(text: "found", mark: .mention), .init(text: "cited", mark: .current)], reveal: 0)
        let runs = Array(s.runs).map(\.attributes)
        XCTAssertNil(runs[0].swiftUI.backgroundColor)
        XCTAssertEqual(runs[0].inlinePresentationIntent, .stronglyEmphasized)
        XCTAssertEqual(runs[1].swiftUI.backgroundColor, CicadaTheme.wash.opacity(0), "the frame before spanReveal")
    }
}
