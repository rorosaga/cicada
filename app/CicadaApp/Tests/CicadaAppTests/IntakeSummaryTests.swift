import XCTest
@testable import CicadaApp

/// Track I T5 — the sentences, pinned in en_US (every count goes through
/// `UsageFormat.count`, so another locale groups its own way).
final class IntakeSummaryTests: XCTestCase {
    private let en = Locale(identifier: "en_US")

    func testTheUpdatedClauseIsKeptAndOmittedOnlyWhenZero() {
        XCTAssertEqual(IntakeSummary.line(new: 12, updated: 3, unchanged: 40, locale: en), "12 new · 3 updated · 40 unchanged")
        XCTAssertEqual(IntakeSummary.line(new: 1_200, updated: 0, unchanged: 0, locale: en), "1,200 new · 0 unchanged")
    }

    func testTheHeadlineUsesTheVendorsNoun() {
        XCTAssertEqual(IntakeSummary.headline(IntakeOutcome(vendor: "chatgpt", created: 374, updated: 5), locale: en),
                       "379 conversations are in.")
        XCTAssertEqual(IntakeSummary.headline(IntakeOutcome(vendor: "gemini", created: 1), locale: en), "1 prompt is in.")
        XCTAssertEqual(IntakeSummary.headline(IntakeOutcome(), locale: en), Copy.intakeNothingNewHeadline)
    }

    func testTheRangeReadsAsMonths() {
        XCTAssertEqual(IntakeSummary.rangeLine(from: "2023-03-04", to: "2026-09-01", locale: en), "Mar 2023 – Sep 2026")
        XCTAssertEqual(IntakeSummary.rangeLine(from: "2026-09-01", to: "2026-09-20", locale: en), "Sep 2026")
        XCTAssertNil(IntakeSummary.rangeLine(from: nil, to: nil, locale: en))
    }

    func testThePreviewDeltaAndTheImportingLine() {
        XCTAssertEqual(IntakeSummary.previewDelta(IntakeDelta(new: 374, grown: 5, unchanged: 33), locale: en),
                       "374 new · 5 grew since last time · 33 already here")
        XCTAssertEqual(IntakeSummary.importingLine(IntakeProgress(total: 379, staged: nil), vendor: "chatgpt", locale: en),
                       "Bringing in 379 conversations…")
        XCTAssertEqual(IntakeSummary.importingLine(IntakeProgress(total: 379, staged: 180), vendor: "chatgpt", locale: en),
                       "Bringing in 180 of 379")
    }

    func testSourcesNamesTheCardTheImportWillShowUnder() {
        XCTAssertEqual(IntakeSummary.sourcesName(origin: "claude-export"), "Claude export")
        XCTAssertEqual(IntakeSummary.sourcesName(origin: "gemini-export"), "Gemini export")
        XCTAssertEqual(IntakeSummary.sourcesName(origin: nil), "Files & links")
    }
}
