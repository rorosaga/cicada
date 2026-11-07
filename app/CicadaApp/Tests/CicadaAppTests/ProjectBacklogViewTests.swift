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

    /// Projects v3 (decision 9): the card's open sections, in their order; the backlog's open items read under Coming up.
    func testTheOpenSectionsComeInTheOrderThePersonNeedsThem() {
        XCTAssertEqual(ProjectSection.allCases, [.now, .comingUp, .timeline])
        XCTAssertEqual(ProjectKey.milestone("m").section, .comingUp)
        XCTAssertEqual(ProjectKey.item("i").section, .timeline)
    }
}
