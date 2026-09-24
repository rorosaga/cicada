import XCTest
@testable import CicadaApp

/// Round-4 D6 — a happening that cites hundreds of pages draws at most eight chips and a "+N more" that opens that
/// row only; the story's derivation runs off the main actor; the Lately list is lazy. Synthetic participants only.
@MainActor
final class ProjectBigStoryTests: XCTestCase {
    private func participants(_ n: Int, from start: Int = 0) -> [[String: Any]] {
        (start..<(start + n)).map { ["id": "paper-example-\($0)", "name": "Paper example \($0)", "type": "media"] }
    }

    private func item(text: String = "Read the alpha-project reading list", sent: [[String: Any]],
                      total: Int? = nil) throws -> ProjectItem {
        var object: [String: Any] = ["kind": "happening", "id": "clm_big", "day": "2026-09-22", "text": text,
                                     "participants": sent]
        if let total { object["participantsTotal"] = total }
        return try JSONDecoder().decode(ProjectItem.self, from: JSONSerialization.data(withJSONObject: object))
    }

    func testTheTotalDecodesLenientlyAndIsOptional() throws {
        XCTAssertNil(try item(sent: participants(2)).participantsTotal, "today's backend sends no total")
        XCTAssertEqual(try item(sent: participants(12), total: 622).participantsTotal, 622)
        let mistyped = try JSONDecoder().decode(ProjectItem.self, from: Data(#"""
            {"kind":"happening","id":"x","text":"t","participantsTotal":"many"}
            """#.utf8))
        XCTAssertNil(mistyped.participantsTotal, "a mistyped total is dropped, never a failed payload")
    }

    func testSixHundredParticipantsDrawEightChipsAndFoldTheRest() throws {
        let big = try item(sent: participants(600))
        let chips = ProjectStory.chips(big.text, participants: big.participants, total: big.participantsTotal,
                                       expanded: false)
        XCTAssertEqual(chips.extra.count, ProjectStory.chipBudget)
        XCTAssertEqual(ProjectStory.chipBudget, 8)
        XCTAssertEqual(chips.more, 592)
        XCTAssertEqual(chips.notSent, 0)
        XCTAssertTrue(chips.canExpand)
    }

    func testExpandingOneRowShowsEveryChipTheWireSent() throws {
        let big = try item(sent: participants(600))
        let open = ProjectStory.chips(big.text, participants: big.participants, total: nil, expanded: true)
        XCTAssertEqual(open.extra.count, 600)
        XCTAssertEqual(open.more, 0)
        XCTAssertFalse(open.canExpand)
    }

    /// D6's cap: the server sends the first 12 and says how many there were.
    func testTheParticipantsTheServerHeldBackCountTowardMoreButCannotExpand() throws {
        let capped = try item(sent: participants(12), total: 622)
        let closed = ProjectStory.chips(capped.text, participants: capped.participants, total: 622, expanded: false)
        XCTAssertEqual(closed.extra.count, 8)
        XCTAssertEqual(closed.more, 614)
        XCTAssertEqual(closed.notSent, 610)
        XCTAssertTrue(closed.canExpand)
        let open = ProjectStory.chips(capped.text, participants: capped.participants, total: 622, expanded: true)
        XCTAssertEqual(open.extra.count, 12)
        XCTAssertEqual(open.more, 610, "expanded, only the held-back ones stay unlisted")
        XCTAssertFalse(open.canExpand)
    }

    /// R-FA1 — inline links count first, past the budget they read as words, and the owner never counts.
    func testInlineLinksCountFirstAndTheOwnerNever() throws {
        let names = (0..<10).map { "Paper example \($0)" }
        let text = "Bob read " + names.joined(separator: ", ")
        var sent = participants(10)
        sent.insert(["id": "bob-example", "name": "Bob Example", "surface": "Bob", "isOwner": true, "type": "person"],
                    at: 0)
        let it = try item(text: text, sent: sent)
        let chips = ProjectStory.chips(it.text, participants: it.participants, total: nil, expanded: false)
        XCTAssertEqual(chips.tokens.filter { $0.kind == .page }.count, 8)
        XCTAssertEqual(chips.tokens.filter { $0.kind == .owner }.count, 1)
        XCTAssertTrue(chips.tokens.contains { $0.kind == .word && $0.text.hasPrefix("Paper example 8") })
        XCTAssertTrue(chips.extra.isEmpty)
        XCTAssertEqual(chips.more, 2)
    }

    /// R-FA2 — the detached build gives exactly what the synchronous one does, over a big synthetic story.
    func testTheOffMainDerivationEqualsTheSynchronousOne() async throws {
        var t = try ProjectFixtures.timeline("rover-arm-project")
        t.items.append(try item(sent: participants(600)))
        let key = ProjectDerived.Key(projectId: t.project.id, today: ProjectFixtures.today, revision: 1)
        let detached = await ProjectDerived.make(t, key: key)
        XCTAssertEqual(detached, ProjectDerived.build(t, key: key))
        XCTAssertEqual(detached.state, ProjectState.state(ProjectState.Input(t), today: ProjectFixtures.today))
        XCTAssertEqual(detached.happenings, t.items.filter { $0.kind != "created" }.count)
    }

    /// R-FA3 — a flat list of entries: each group label, then its rows; the first label sits closer to its header.
    func testLatelyIsOneFlatListOfLabelsAndRows() throws {
        let t = try ProjectFixtures.timeline("rover-arm-project")
        let groups = ProjectStory.groups(t.items, today: ProjectFixtures.today)
        let entries = ProjectStory.latelyEntries(groups)
        XCTAssertEqual(entries.count, groups.count + groups.map(\.items.count).reduce(0, +))
        guard case .label(_, let first)? = entries.first else { return XCTFail("a label leads") }
        XCTAssertTrue(first)
        XCTAssertEqual(Set(entries.map(\.id)).count, entries.count, "ids are unique — they are scroll ids")
        let firstItem = try XCTUnwrap(groups.first?.items.first)
        XCTAssertTrue(entries.contains { $0.id == ProjectKey.item(firstItem.id).id })
    }

    /// R-FA2 / R-FA3 as source checks: the column no longer derives in `body`, and its story is lazy.
    func testTheColumnDerivesOffMainAndIsLazy() throws {
        let files = try ThemeTokenTests.swiftSources()
        func text(_ suffix: String) throws -> String {
            try String(contentsOf: XCTUnwrap(files.first { $0.path.hasSuffix(suffix) }), encoding: .utf8)
        }
        let column = try text("Views/Projects/ProjectDetailColumn.swift")
        XCTAssertFalse(column.contains("ProjectState.state("), "derivation lives in ProjectDerived (R-FA2)")
        XCTAssertTrue(column.contains("LazyVStack"), "the story is lazy (R-FA3)")
        XCTAssertTrue(column.contains("ProjectScroll.steps(to:"), "a milestone pick lands the Plan first (review round 1)")
        XCTAssertFalse(try text("Views/Projects/ProjectSections.swift").contains("struct ProjectLatelySection"))
    }

    /// Review round 1 — a Plan milestone's row lives inside the Plan section, which the lazy stack may not have built
    /// on a long story, so the scroll lands the section first; every other key is a direct id and scrolls once.
    func testAMilestonePickScrollsToThePlanSectionFirst() {
        let milestone = ProjectKey.milestone("alpha-launch").id
        XCTAssertEqual(ProjectScroll.steps(to: milestone), [ProjectScroll.planSection, milestone])
        XCTAssertEqual(ProjectScroll.steps(to: ProjectKey.item("h-1").id), [ProjectKey.item("h-1").id])
        XCTAssertEqual(ProjectScroll.steps(to: ProjectKey.thread("c-1").id), [ProjectKey.thread("c-1").id])
        XCTAssertEqual(ProjectScroll.steps(to: ProjectScroll.planSection), [ProjectScroll.planSection])
    }
}
