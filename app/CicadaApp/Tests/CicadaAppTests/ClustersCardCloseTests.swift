import XCTest
@testable import CicadaApp

/// QA 2026-10-16 (finding 8) — in Clusters the entity card's × floated above the card's top-right corner, outside it.
/// It sits in the card's own header line now (§5.3's header anatomy), wired to the column's close.
final class ClustersCardCloseTests: XCTestCase {
    func test_closeSitsInTheCardsHeaderNotAboveIt() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.path.hasSuffix("Views/Clusters/ClustersCardColumn.swift")
        })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(text.contains("showsCloseButton: true"))
        XCTAssertTrue(text.contains("onClose: onClose"))
        XCTAssertFalse(text.contains("IconButton(systemName: \"xmark\""), "no second × above the card")
    }
}
