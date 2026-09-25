import XCTest
@testable import CicadaApp

/// R-PP2 — the Projects wire decodes whole from the demo's real payloads, and leniently from a sparse one.
final class ProjectWireTests: XCTestCase {
    func testTheListDecodes() throws {
        let wire = try ProjectFixtures.load()
        XCTAssertEqual(wire.projects.tzName, "UTC")
        XCTAssertFalse(wire.projects.partial)
        let rover = try ProjectFixtures.row("rover-arm-project")
        XCTAssertEqual(rover.name, "Rover Arm Project")
        XCTAssertEqual(rover.children, ["pick-and-place-demo"])
        XCTAssertTrue(rover.planned)
        XCTAssertEqual(rover.progress, ProjectProgress(done: 1, total: 4))
        XCTAssertEqual(rover.followups, 1)
        XCTAssertEqual(rover.openThreads.count, 2)
        XCTAssertEqual(try ProjectFixtures.row("pick-and-place-demo").parent, "rover-arm-project")
        XCTAssertFalse(try ProjectFixtures.row("garden-sensor-project").planned)
    }

    func testATimelineDecodesItsItemsParticipantsAndChain() throws {
        let t = try ProjectFixtures.timeline("rover-arm-project")
        XCTAssertEqual(t.project.created, "2026-07-15")
        XCTAssertEqual(t.pending.unconsolidated, 1)
        let guide = try XCTUnwrap(t.items.first { $0.kind == "happening" && $0.day == "2026-09-22" })
        XCTAssertEqual(guide.claim?.status, "done")
        XCTAssertEqual(guide.dateBasis, "stated")
        XCTAssertEqual(guide.participants.first?.isOwner, true)
        XCTAssertEqual(guide.participants.first { $0.role == "document" }?.url,
                       "https://example.com/guides/lab-cluster-onboarding.pdf")
        XCTAssertEqual(guide.participants.first { $0.role == "from" }?.type, .person)
        XCTAssertEqual(guide.conversation?.origin, "telegram")
        XCTAssertEqual(guide.quote?.kind, "user")
        let grasp = try XCTUnwrap(t.milestones.first { $0.slug == "first-grasp" })
        XCTAssertTrue(grasp.moved)
        XCTAssertEqual(grasp.chain.map(\.predicate), ["milestone", "due"])
        XCTAssertEqual(grasp.chain.last?.object, "2026-09-09")
        XCTAssertEqual(grasp.chain.first?.origin, "companion_app")
        XCTAssertEqual(t.cluster.groups.map(\.label), ["People", "Tools & infrastructure", "Documents", "Sub-projects"])
        XCTAssertTrue(t.items.contains { $0.kind == "created" })
    }

    func testTheFollowupNamesItsThread() throws {
        let wire = try ProjectFixtures.load()
        XCTAssertEqual(wire.followup.kind, .followup)
        XCTAssertEqual(wire.followup.claimId,
                       try ProjectFixtures.row("rover-arm-project").openThreads.first { $0.since == "2026-08-30" }?.claimId)
    }

    /// A server one field behind never blanks the page: every key is optional-with-default.
    func testASparsePayloadStillDecodes() throws {
        let row = try JSONDecoder().decode(ProjectRow.self, from: Data(#"{"id":"alpha-project","name":"Alpha"}"#.utf8))
        XCTAssertEqual(row.openThreads, [])
        XCTAssertEqual(row.progress, ProjectProgress())
        XCTAssertFalse(row.planned)
        let item = try JSONDecoder().decode(ProjectItem.self, from: Data(#"{"kind":"moment","id":"m:1","participants":[{"name":"X","type":"not-a-type"}]}"#.utf8))
        XCTAssertEqual(item.participants.first?.type, .unknown)
        let write = try JSONDecoder().decode(ProjectWriteResponse.self, from: Data(#"{"action":"created"}"#.utf8))
        XCTAssertNil(write.claimId)
    }
}
