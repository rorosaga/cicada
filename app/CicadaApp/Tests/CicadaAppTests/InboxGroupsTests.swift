import XCTest
@testable import CicadaApp

/// Owner 2026-10-26 — the Inbox in groups: by kind under All, by page inside; display only, the walk follows the screen.
@MainActor
final class InboxGroupsTests: XCTestCase {
    private func item(_ id: String, kind: String = "conflict", priority: Double = 0.5, created: String = "2026-09-01",
                      page: String = "alpha-project", name: String = "Alpha Project") throws -> InboxItem {
        try JSONDecoder().decode(InboxItem.self, from: Data(#"{"id":"\#(id)","kind":"\#(kind)","requiredInput":"choice","title":"\#(id)","priority":\#(priority),"createdDate":"\#(created)","entityId":"\#(page)","entityName":"\#(name)"}"#.utf8))
    }

    func testAllGroupsByKindInTheOrderOfEachKindsMostUrgentQuestion() throws {
        let items = [try item("d1", kind: "decay", priority: 0.3), try item("c1", priority: 0.5, page: "beta", name: "Beta"),
                     try item("q1", kind: "clarification", priority: 0.9, page: "", name: ""),
                     try item("c2", priority: 0.5, created: "2026-09-05")]
        let sections = InboxGroups.sections(items, byKind: true)
        XCTAssertEqual(sections.map(\.kind), [.clarification, .conflict, .decay])
        XCTAssertEqual(sections.map(\.count), [1, 2, 1])
        XCTAssertEqual(InboxGroups.ordered(items, byKind: true).map(\.id), ["q1", "c2", "c1", "d1"])
    }

    func testAPagesQuestionsSitTogetherWhereItsMostUrgentOneIs() throws {
        let items = [try item("a1", priority: 0.9), try item("b1", priority: 0.8, page: "beta", name: "Beta"),
                     try item("a2", priority: 0.1), try item("n1", priority: 0.7, page: "", name: ""),
                     try item("n2", priority: 0.6, page: "", name: "")]
        let section = try XCTUnwrap(InboxGroups.sections(items, byKind: false).first)
        XCTAssertNil(section.kind)
        XCTAssertEqual(section.pages.map { $0.items.map(\.id) }, [["a1", "a2"], ["b1"], ["n1"], ["n2"]])
        XCTAssertEqual(section.pages.map(\.hasHeader), [true, false, false, false],
                       "a header only over two or more questions about one page; questions with no page never share one")
    }

    func testOneSectionIsOpenAndOfSeveralOnlyTheFirstUntilThePersonChooses() throws {
        let items = [try item("c1", priority: 0.9), try item("d1", kind: "decay", priority: 0.3)]
        let sections = InboxGroups.sections(items, byKind: true)
        XCTAssertTrue(InboxGroups.isOpen(.conflict, sections: sections, chosen: [:], openKind: nil))
        XCTAssertFalse(InboxGroups.isOpen(.decay, sections: sections, chosen: [:], openKind: nil))
        XCTAssertTrue(InboxGroups.isOpen(.decay, sections: sections, chosen: [.decay: true], openKind: nil))
        XCTAssertFalse(InboxGroups.isOpen(.conflict, sections: sections, chosen: [.conflict: false], openKind: nil))
        XCTAssertTrue(InboxGroups.isOpen(.decay, sections: sections, chosen: [.decay: false], openKind: .decay),
                      "the open question's group is always open")
        XCTAssertTrue(InboxGroups.isOpen(nil, sections: InboxGroups.sections(items, byKind: false), chosen: [:],
                                         openKind: nil))
        let full = try (0..<13).map { try item("c\($0)", page: "p\($0)", name: "P\($0)") } + [try item("d", kind: "decay")]
        let fullSections = InboxGroups.sections(full, byKind: true)
        XCTAssertFalse(InboxGroups.isOpen(.conflict, sections: fullSections, chosen: [:], openKind: nil),
                       "a full inbox starts as its kinds and counts")
    }

    func testLinesCarryCountsAReviewAndOnlyOpenGroupsQuestions() throws {
        let items = [try item("c1", priority: 0.9), try item("c2", priority: 0.8),
                     try item("d1", kind: "decay", priority: 0.3, page: "beta", name: "Beta")]
        let sections = InboxGroups.sections(items, byKind: true)
        let reviews = [ReviewEntries.Entry(kind: .decay, count: 1)]
        let lines = InboxListLine.lines(sections, byKind: true, held: nil, heldItem: nil, reviews: reviews) {
            $0 == .conflict
        }
        XCTAssertEqual(lines.map(\.id), ["kind:conflict", "pagehead:conflict:page:alpha-project", "c1", "c2", "kind:decay"])
        guard case .kind(_, let count, let open, let review) = lines[0] else { return XCTFail("\(lines[0])") }
        XCTAssertEqual(count, 2)
        XCTAssertTrue(open)
        XCTAssertNil(review)
        guard case .kind(_, _, let decayOpen, let decayReview) = lines[4] else { return XCTFail("\(lines[4])") }
        XCTAssertFalse(decayOpen)
        XCTAssertEqual(decayReview?.kind, .decay)
        guard case .entry(_, let nested) = lines[2] else { return XCTFail("\(lines[2])") }
        XCTAssertTrue(nested, "a row under its page's header leaves the page's name out")
    }

    /// Review of #475: one page with questions of two kinds, both groups open, draws two page headers, never one id twice.
    func testOnePageInTwoOpenKindGroupsNeverRepeatsALineId() throws {
        let items = [try item("c1", priority: 0.9), try item("c2", priority: 0.8),
                     try item("d1", kind: "decay", priority: 0.3), try item("d2", kind: "decay", priority: 0.2)]
        let lines = InboxListLine.lines(InboxGroups.sections(items, byKind: true), byKind: true, held: nil,
                                        heldItem: nil, reviews: []) { _ in true }
        let ids = lines.map(\.id)
        XCTAssertEqual(Set(ids).count, ids.count, "\(ids)")
        XCTAssertEqual(ids.filter { $0.hasPrefix("pagehead:") },
                       ["pagehead:conflict:page:alpha-project", "pagehead:decay:page:alpha-project"])
        let tab = InboxListLine.lines(InboxGroups.sections(items, byKind: false), byKind: false, held: nil,
                                      heldItem: nil, reviews: []) { _ in true }
        XCTAssertEqual(tab.map(\.id).filter { $0.hasPrefix("pagehead:") }, ["pagehead:all:page:alpha-project"])
    }

    func testTheHeldAnswersUndoRowStaysInItsGroupEvenWhenItWasTheLast() throws {
        let held = try item("d1", kind: "decay")
        let grace = ResolveGrace(resolve: InboxResolve(id: "d1", action: "resolve", optionKey: "keep"),
                                 label: "Kept", shortLabel: "Kept", question: "d1", kind: .decay, channel: nil,
                                 bank: "demo", token: 1)
        let sections = InboxGroups.sections([try item("c1")], byKind: true)
        let lines = InboxListLine.lines(sections, byKind: true, held: grace, heldItem: held, reviews: []) { _ in false }
        XCTAssertEqual(lines.map(\.id), ["kind:conflict", "kind:decay", grace.id],
                       "the decay group is open while it holds the Undo row; the closed conflict group shows only its header")
    }
}
