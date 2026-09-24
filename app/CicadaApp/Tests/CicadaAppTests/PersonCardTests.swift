import XCTest
@testable import CicadaApp

/// F-12 (plan R-PE17 … R-PE19) — the person card's body, pure: the signed line, the order of beliefs, the map and what
/// is happening.
final class PersonCardTests: XCTestCase {
    private let us = Locale(identifier: "en_US")

    private func claim(_ id: String, author: String, kind: String?, model: String? = nil, effort: String? = nil,
                       provider: String? = nil, recordedAt: String? = nil, validFrom: String = "2026-09-24") throws -> Claim {
        var fields = [#""id":"\#(id)""#, #""text":"t""#, #""subject":"leo-example""#, #""predicate":"uses""#,
                      #""object":"x""#, #""context":"general""#, #""observer":"agent""#, #""validFrom":"\#(validFrom)""#,
                      #""authoredBy":"\#(author)""#]
        if let kind { fields.append(#""authorKind":"\#(kind)""#) }
        if let model { fields.append(#""authorModel":"\#(model)""#) }
        if let effort { fields.append(#""authorEffort":"\#(effort)""#) }
        if let provider { fields.append(#""authorProvider":"\#(provider)""#) }
        if let recordedAt { fields.append(#""recordedAt":"\#(recordedAt)""#) }
        return try JSONDecoder().decode(Claim.self, from: Data("{\(fields.joined(separator: ","))}".utf8))
    }

    /// R-PE18 — who wrote a belief, from the captured turn, never a guess.
    func testTheSignedLineNamesWhoWroteIt() throws {
        XCTAssertEqual(SignedLine.text(try claim("a", author: "claude-code", kind: "harness", model: "claude-opus-5-5",
                                                 effort: "high", recordedAt: "2026-09-24T10:42:00Z"), locale: us),
                       "Written by Claude Code · Opus 5.5 · high effort · Sep 24")
        XCTAssertEqual(SignedLine.text(try claim("b", author: "claude-sonnet-5", kind: "model", provider: "anthropic",
                                                 validFrom: "2026-09-17"), locale: us),
                       "Written by Sleep · Sonnet 5 · Sep 17")
        XCTAssertEqual(SignedLine.text(try claim("c", author: "user", kind: "user"), locale: us),
                       "Written by you · Sep 24")
        let desktop = try XCTUnwrap(SignedLine.text(try claim("d", author: "claude-desktop", kind: "harness"), locale: us))
        XCTAssertTrue(desktop.contains(Copy.Provenance.modelNotShared), desktop)
        XCTAssertNil(SignedLine.text(try claim("e", author: "unknown", kind: "unknown"), locale: us), "no author, no line")
        XCTAssertEqual(SignedLine.mark(try claim("f", author: "codex", kind: "harness")), .origin("codex"))
        XCTAssertEqual(SignedLine.mark(try claim("g", author: "user", kind: "user")), .bare)
    }

    func testBeliefsAreNewestFirstAndOnlyCurrent() throws {
        let old = try claim("old", author: "user", kind: "user", validFrom: "2026-03-12")
        let new = try claim("new", author: "user", kind: "user", recordedAt: "2026-09-24T09:00:00Z", validFrom: "2026-03-01")
        let mid = try claim("mid", author: "user", kind: "user", validFrom: "2026-09-17")
        XCTAssertEqual(PersonBeliefs.ordered([old, new, mid]).map(\.id), ["new", "mid", "old"])
        XCTAssertEqual(PersonBeliefs.collapsed, 4)
    }

    private var graph: (nodes: [GraphNode], edges: [GraphEdge]) {
        let nodes = [
            GraphNode(id: "leo-example", name: "Leo Example", type: .person, degree: 6),
            GraphNode(id: "owner-example", name: "Owner Example", type: .person, degree: 9, isOwner: true),
            GraphNode(id: "northwind-example", name: "Northwind Example", type: .company, degree: 5),
            GraphNode(id: "maya-example", name: "Maya Example", type: .person, degree: 3),
            GraphNode(id: "lantern-project", name: "Lantern", type: .project, degree: 7),
            GraphNode(id: "meter-sim", name: "Meter Sim", type: .project, degree: 2),
            GraphNode(id: "lab-cluster", name: "Lab cluster", type: .tool, degree: 4),
            GraphNode(id: "hub:people", name: "People", type: .hub, isHub: true),
            GraphNode(id: "leo-example#work", name: "Leo Example · work", type: .person, isFacet: true),
        ]
        let edges = [
            GraphEdge(source: "leo-example", target: "owner-example", label: "works with"),
            GraphEdge(source: "leo-example", target: "northwind-example", label: "works at"),
            GraphEdge(source: "maya-example", target: "leo-example", label: "introduced"),
            GraphEdge(source: "leo-example", target: "lantern-project", label: "leads"),
            GraphEdge(source: "leo-example", target: "meter-sim", label: "reviewed"),
            GraphEdge(source: "leo-example", target: "lab-cluster", label: "looks after"),
            GraphEdge(source: "hub:people", target: "leo-example", label: "member of"),
            GraphEdge(source: "leo-example", target: "leo-example#work", label: "facet"),
        ]
        return (nodes, edges)
    }

    /// R-PE17 — the owner first, at the top; then the busiest; hubs and facets are never neighbours.
    func testTheMapPutsYouOnTopThenTheBusiest() {
        let map = PersonMapLayout.make(personId: "leo-example", nodes: graph.nodes, edges: graph.edges)
        XCTAssertEqual(map.total, 6)
        XCTAssertEqual(map.nodes.map(\.id), ["owner-example", "lantern-project", "northwind-example", "lab-cluster",
                                             "maya-example", "meter-sim"])
        XCTAssertEqual(map.nodes[0].label, "works with")
        XCTAssertTrue(map.nodes[0].isOwner)
        XCTAssertEqual(map.nodes[0].x, 0.5, accuracy: 0.001)
        XCTAssertEqual(map.nodes[0].y, 0.12, accuracy: 0.001)
        XCTAssertEqual(map.nodes[1].x, 0.829, accuracy: 0.001)
        XCTAssertEqual(map.nodes[1].y, 0.31, accuracy: 0.001)
        let small = PersonMapLayout.make(personId: "leo-example", nodes: graph.nodes, edges: graph.edges, limit: 3)
        XCTAssertEqual(small.nodes.count, 3)
        XCTAssertEqual(small.total, 6, "the sentence counts every page, the map draws six")
        XCTAssertEqual(PersonMapLayout.projects(personId: "leo-example", nodes: graph.nodes, edges: graph.edges),
                       ["lantern-project", "meter-sim"])
        XCTAssertEqual(PersonMapLayout.make(personId: "nobody", nodes: graph.nodes, edges: graph.edges).nodes, [])
    }

    /// R-PE19 — the demo's real wire: what is planned soonest, then what happened, newest first, never twice.
    func testWhatIsHappeningReadsTheDemosProjects() throws {
        let rows = PersonHappenings.rows(personId: "hana-example",
                                         timelines: [try ProjectFixtures.timeline("rover-arm-project"),
                                                     try ProjectFixtures.timeline("pick-and-place-demo")])
        XCTAssertEqual(rows.map(\.mark), [.planned, .planned, .done])
        XCTAssertEqual(rows.map(\.day.description), ["2026-10-01", "2026-10-05", "2026-09-22"])
        XCTAssertEqual(rows[0].text, "First grasp")
        XCTAssertEqual(rows[0].projectId, "rover-arm-project")
        XCTAssertEqual(rows[1].text, "Pick And Place Demo")
        XCTAssertEqual(rows[2].projectId, "pick-and-place-demo")
        XCTAssertEqual(rows[2].origin, "telegram")
        XCTAssertEqual(RelativeDay.distance(rows[0].day, today: ProjectFixtures.today), "in 8 days")
        XCTAssertEqual(PersonHappenings.rows(personId: "nobody-example",
                                             timelines: [try ProjectFixtures.timeline("rover-arm-project")]), [])
    }
}
