import XCTest
@testable import CicadaApp

/// F-12 (plan R-PE16) — the facts strip, pure: every cell from something true, never a placeholder.
final class PersonFactsTests: XCTestCase {
    private let us = Locale(identifier: "en_US")
    private let utc = TimeZone(identifier: "UTC")!
    private let today = ISODay(year: 2026, month: 9, day: 24)

    private func claim(_ id: String, _ predicate: String, _ object: String, episode: String) throws -> Claim {
        try JSONDecoder().decode(Claim.self, from: Data(#"""
        {"id":"\#(id)","text":"t","subject":"leo-example","predicate":"\#(predicate)","object":"\#(object)",
         "context":"general","observer":"owner-example","validFrom":"2026-03-12",
         "evidence":[{"episode":"\#(episode)","start":0,"end":10,"kind":"user","hash":"abc"}]}
        """#.utf8))
    }

    private func leo(created: String = "2026-03-12", lastReferenced: String = "2026-09-24") -> Entity {
        Entity(id: "leo-example", name: "Leo Example", type: .person, status: .active, confidence: 0.9,
               created: created, lastReferenced: lastReferenced, decayRate: 0.05, sourceEpisodes: [], tags: [],
               related: [], version: 1, markdownContent: "## Summary\nRobotics engineer at Northwind Example.",
               history: [])
    }

    private var provenance: EntityProvenance {
        EntityProvenance(entityId: "leo-example", conversations: [
            ProvenanceConversation(episodeId: "ep_2026-09-24_003", harness: "claude-code", timestamp: "2026-09-24T10:42:00Z"),
            ProvenanceConversation(episodeId: "ep_2026-03-12_001", origin: "claude-export", timestamp: "2026-03-12T09:00:00Z"),
            ProvenanceConversation(episodeId: "ep_2026-09-17_002", origin: "wispr-flow", timestamp: "2026-09-17T15:00:00Z"),
            ProvenanceConversation(episodeId: "ep_2026-09-20_004", harness: "codex", timestamp: "2026-09-20T11:00:00Z"),
        ], pages: [ProvenancePage(entityId: "a"), ProvenancePage(entityId: "b"), ProvenancePage(entityId: "c")])
    }

    private func cells(claims: [Claim], picture: EntityPictureRef? = nil, entity: Entity? = nil,
                       provenance: EntityProvenance? = nil) -> [PersonFact] {
        PersonFacts.cells(entity: entity ?? leo(), claims: claims, provenance: provenance,
                          names: EntityNames(byId: ["northwind-example": "Northwind Example"]),
                          typeOf: { $0 == "northwind-example" ? .company : nil }, picture: picture,
                          docs: EvidenceDocIndex(), today: today, locale: us, timeZone: utc)
    }

    func testEveryCellFromSomethingTrue() throws {
        let facts = cells(claims: [try claim("c1", "works-at", "northwind-example", episode: "ep_2026-03-12_001"),
                                   try claim("c2", "is-a", "robotics engineer", episode: "ep_2026-09-17_002")],
                          picture: EntityPictureRef(url: "/entities/leo-example/picture?v=0a1b2c3d4e5f", source: .contacts),
                          provenance: provenance)
        XCTAssertEqual(facts.map(\.kind), [.worksAt, .role, .knownSince, .lastMentioned, .conversations, .contacts])
        XCTAssertEqual(facts[0].value, "Northwind Example")
        XCTAssertEqual(facts[0].valueEntity, "northwind-example")
        XCTAssertEqual(facts[0].valueType, .company)
        XCTAssertEqual(facts[0].line, "You said · Mar 12")
        XCTAssertEqual(facts[1].value, "robotics engineer")
        XCTAssertNil(facts[1].valueEntity, "a literal names no page")
        XCTAssertEqual(facts[2].value, "Mar 12 · 6 months")
        XCTAssertEqual(facts[2].line, "first in Claude")
        XCTAssertEqual(facts[2].marks, ["claude-export"])
        XCTAssertEqual(facts[3].value, "Today")
        XCTAssertTrue(facts[3].line?.hasPrefix("Claude Code · 10:42") ?? false, facts[3].line ?? "nil")
        XCTAssertEqual(facts[4].value, "4")
        XCTAssertEqual(facts[4].marks, ["claude-export", "wispr-flow", "codex", "claude-code"], "oldest first, ≤ 4")
        XCTAssertEqual(facts[4].line, "3 pages")
        XCTAssertEqual(facts[5].value, "Matched")
    }

    func testNoCellIsEverAPlaceholder() {
        XCTAssertEqual(cells(claims: [], entity: leo(created: "", lastReferenced: "")), [])
        XCTAssertFalse(cells(claims: []).contains { $0.kind == .contacts }, "Contacts only when the picture came from it")
        XCTAssertFalse(cells(claims: []).contains { $0.kind == .conversations }, "no provenance, no count")
    }

    func testASpanReadsInPlainUnits() {
        XCTAssertEqual(Copy.People.span(days: 1), "1 day")
        XCTAssertEqual(Copy.People.span(days: 20), "2 weeks")
        XCTAssertEqual(Copy.People.span(days: 196), "6 months")
        XCTAssertEqual(Copy.People.span(days: 800), "2 years")
    }
}
