import XCTest
@testable import CicadaApp

/// Proposed ruling 55: how a token reads on screen. Synthetic numbers only.
final class NumberTokensTests: XCTestCase {
    private let token = "[number:abcdefghij]"
    private let numbers = ["abcdefghij": "+1 202 555 0143"]

    func testIdsAreEachTokenOnce() {
        XCTAssertEqual(NumberTokens.ids(in: "\(token) and \(token) and [number:klmnopqrst]"), ["abcdefghij", "klmnopqrst"])
        XCTAssertEqual(NumberTokens.ids(in: "no number here, [number:SHORT]"), [])
    }

    func testKnownShowsTheDigitsAndUnknownNeverShowsTheToken() {
        XCTAssertEqual(NumberTokens.shown("her number is \(token)", numbers), "her number is +1 202 555 0143")
        XCTAssertEqual(NumberTokens.shown("her number is \(token)", [:]), "her number is \(Copy.Graph.aNumber)")
        XCTAssertEqual(NumberTokens.shown("nothing to see", numbers), "nothing to see")
    }

    func testAPassageKeepsItsMarks() {
        let segments = [CitedSpan.Segment(text: "says \(token)", mark: .current), .init(text: "tail", mark: .plain)]
        XCTAssertEqual(NumberTokens.shown(segments, numbers),
                       [.init(text: "says +1 202 555 0143", mark: .current), .init(text: "tail", mark: .plain)])
    }
}
