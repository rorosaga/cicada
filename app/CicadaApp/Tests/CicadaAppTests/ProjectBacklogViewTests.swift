import XCTest
@testable import CicadaApp

/// G150 (R-B19, R-B21) — the page's one trailing slot, its Esc order, and where the Backlog section sits.
final class ProjectBacklogViewTests: XCTestCase {
    func testEscClosesTheReaderThenTheItemOrCardThenTheProject() {
        XCTAssertEqual(ProjectTrailing.escape(readerOpen: true, trailing: .backlogItem("RAP3"), projectOpen: true),
                       .reader)
        XCTAssertEqual(ProjectTrailing.escape(readerOpen: false, trailing: .backlogItem("RAP3"), projectOpen: true),
                       .trailing)
        XCTAssertEqual(ProjectTrailing.escape(readerOpen: false, trailing: .entity("hana-example"), projectOpen: true),
                       .trailing)
        XCTAssertEqual(ProjectTrailing.escape(readerOpen: false, trailing: nil, projectOpen: true), .project)
        XCTAssertEqual(ProjectTrailing.escape(readerOpen: false, trailing: nil, projectOpen: false), .nothing)
    }

    func testTheSlotHoldsOneThing() {
        XCTAssertEqual(ProjectTrailing.backlogItem("RAP3").backlogItemId, "RAP3")
        XCTAssertNil(ProjectTrailing.backlogItem("RAP3").entityId)
        XCTAssertEqual(ProjectTrailing.entity("hana-example").entityId, "hana-example")
        XCTAssertNil(ProjectTrailing.entity("hana-example").backlogItemId)
    }

    func testTheBacklogSitsAfterThePlanAndItsFoldIsRemembered() {
        XCTAssertEqual(ProjectSection.allCases, [.now, .lately, .plan, .backlog, .around])
        XCTAssertEqual(ProjectSection(rawValue: "backlog"), .backlog)
    }
}
