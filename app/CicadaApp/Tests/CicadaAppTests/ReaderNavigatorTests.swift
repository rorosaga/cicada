import XCTest
@testable import CicadaApp

/// Design §4.4 (P4) — "‹ 2 of 5 cited here ›": which spans the navigator
/// steps through, where the Reader is among them, and what a jump to one
/// says about it.
final class ReaderNavigatorTests: XCTestCase {

    private func cite(_ claim: String, subject: String, _ range: Range<Int>?, derived: Bool = false,
                      grown: Bool = false, stale: Bool = false) -> EpisodeCitation {
        EpisodeCitation(claimId: claim, subjectId: subject, kind: derived ? .derived : .assistant,
                        start: range?.lowerBound, end: range?.upperBound, stale: stale, grown: grown,
                        derived: derived)
    }

    private lazy var rows: [EpisodeCitation] = [
        cite("c3", subject: "alpha-project", 90..<99),
        cite("c1", subject: "alpha-project", 10..<20),
        cite("c2", subject: "bob-example", 40..<50),
        cite("c4", subject: "alpha-project", 10..<20),          // a second claim, same words
        cite("c5", subject: "alpha-project", nil, stale: true), // R-PB2 — no offsets, never a stop
    ]

    func testStopsAreTheSubjectsSpansInDocumentOrderDeduplicated() {
        XCTAssertEqual(ReaderNavigator.stops(rows, subjectId: "alpha-project"), [10..<20, 90..<99])
    }

    func testWithoutASubjectOrWithNoneOfItsOwnEverySpanIsAStop() {
        XCTAssertEqual(ReaderNavigator.stops(rows, subjectId: nil), [10..<20, 40..<50, 90..<99])
        XCTAssertEqual(ReaderNavigator.stops(rows, subjectId: "carol-example"), [10..<20, 40..<50, 90..<99],
                       "an entity with no span here still gets something to step through")
    }

    func testPositionFindsTheFocusExactlyOrByOverlap() {
        let stops = [10..<20, 40..<50, 90..<99]
        XCTAssertEqual(ReaderNavigator.position(of: 40..<50, in: stops), 1)
        XCTAssertEqual(ReaderNavigator.position(of: 45..<47, in: stops), 1)
        XCTAssertNil(ReaderNavigator.position(of: 60..<70, in: stops))
        XCTAssertNil(ReaderNavigator.position(of: nil, in: stops))
    }

    func testSteppingClampsAtTheEndsAndStartsFromAnEndWhenLost() {
        XCTAssertEqual(ReaderNavigator.step(from: 1, count: 3, by: 1), 2)
        XCTAssertEqual(ReaderNavigator.step(from: 2, count: 3, by: 1), 2, "the last passage is an end, not a loop")
        XCTAssertEqual(ReaderNavigator.step(from: 0, count: 3, by: -1), 0)
        XCTAssertEqual(ReaderNavigator.step(from: nil, count: 3, by: 1), 0)
        XCTAssertEqual(ReaderNavigator.step(from: nil, count: 3, by: -1), 2)
        XCTAssertNil(ReaderNavigator.step(from: nil, count: 0, by: 1))
    }

    func testTheLabelCountsFromOne() {
        XCTAssertEqual(ReaderNavigator.label(position: 1, count: 5), "2 of 5 cited here")
        XCTAssertEqual(ReaderNavigator.label(position: nil, count: 5), "5 cited here")
        XCTAssertEqual(ReaderNavigator.label(position: nil, count: 0), "")
    }

    func testAJumpIsJudgedByTheCitationsOwnFlags() {
        let derived = ReaderPresentation.citation(cite("c", subject: "a", 5..<9, derived: true),
                                                  truncated: false, textCount: 100)
        XCTAssertEqual(derived.focusStyle, .mention)
        XCTAssertEqual(derived.banners, [.derived])
        let grown = ReaderPresentation.citation(cite("c", subject: "a", 5..<9, grown: true),
                                                truncated: false, textCount: 100)
        XCTAssertEqual(grown.focusStyle, .focus)
        XCTAssertEqual(grown.banners, [.grown])
        XCTAssertEqual(grown.landing, 5)
        let past = ReaderPresentation.citation(cite("c", subject: "a", 500..<509), truncated: true, textCount: 100)
        XCTAssertNil(past.focus, "words past the cap are not on screen to wash")
        XCTAssertEqual(past.banners, [.truncated])
    }
}
