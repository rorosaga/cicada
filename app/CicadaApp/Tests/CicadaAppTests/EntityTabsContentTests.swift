import XCTest
@testable import CicadaApp

/// R-DG22 … R-DG24 — Perspectives, History and Timeline, pure.
final class EntityTabsContentTests: XCTestCase {
    private func claim(_ id: String, predicate: String = "uses", context: String = "engineering",
                       observer: String = "agent", object: String = "sqlite-vec", validFrom: String = "2026-04-01",
                       validTo: String? = nil) throws -> Claim {
        let to = validTo.map { #","validTo":"\#($0)""# } ?? ""
        return try JSONDecoder().decode(Claim.self, from: Data(#"{"id":"\#(id)","text":"t","predicate":"\#(predicate)","context":"\#(context)","observer":"\#(observer)","object":"\#(object)","validFrom":"\#(validFrom)"\#(to)}"#.utf8))
    }

    /// R-DG23 — the contested beliefs, and the one a clock asked for first when it is not one of them.
    func testTimelineRows() throws {
        let claims = [try claim("a"), try claim("b", validTo: "2026-05-01"), try claim("c", predicate: "role")]
        let uses = BeliefKey(predicate: "uses", context: "engineering")
        let role = BeliefKey(predicate: "role", context: "engineering")
        XCTAssertEqual(TimelineKeys.rows(claims: claims, requested: nil), [uses])
        XCTAssertEqual(TimelineKeys.rows(claims: claims, requested: role), [role, uses])
        XCTAssertEqual(TimelineKeys.rows(claims: claims, requested: uses), [uses], "never listed twice")
        XCTAssertEqual(TimelineKeys.heading(contested: 1), "Contested beliefs")
        XCTAssertEqual(TimelineKeys.heading(contested: 0), "This belief")
    }

    func testATimelineRowsSummary() throws {
        let claims = [try claim("a", validFrom: "2026-04-01"), try claim("b", validFrom: "2026-01-05", validTo: "2026-04-01")]
        XCTAssertEqual(TimelineKeys.summary(BeliefKey(predicate: "uses", context: "engineering"), claims: claims,
                                            locale: Locale(identifier: "en_US")),
                       "2 beliefs since Jan 5")
    }

    /// R-DG24 — straight to the Reader when every session maps to one episode here; the chooser otherwise.
    func testShowInConversation() {
        let map = ["ses_a": "ep_2026-08-10_001", "ses_b": "ep_2026-08-10_001", "ses_c": "ep_2026-08-25_001"]
        XCTAssertEqual(HistoryConversation.action(sessions: [], openEpisode: map), .none)
        XCTAssertEqual(HistoryConversation.action(sessions: ["ses_a"], openEpisode: map), .open(episode: "ep_2026-08-10_001"))
        XCTAssertEqual(HistoryConversation.action(sessions: ["ses_a", "ses_b"], openEpisode: map), .open(episode: "ep_2026-08-10_001"))
        XCTAssertEqual(HistoryConversation.action(sessions: ["ses_a", "ses_c"], openEpisode: map), .choose)
        XCTAssertEqual(HistoryConversation.action(sessions: ["ses_gone"], openEpisode: map), .choose, "Resume may still work")
    }

    func testHistoryChangesAreWords() {
        XCTAssertEqual(HistoryWords.change(.created), "Created")
        XCTAssertEqual(HistoryWords.change(.updated), "Updated")
        XCTAssertEqual(HistoryWords.change(.statusChange), "Status changed")
        XCTAssertEqual(HistoryWords.change(.confidenceChange), "Confidence changed")
        XCTAssertEqual(HistoryWords.change(.relationAdded), "Link added")
    }

    /// Cicada, then you, then outside sources; current beliefs only; a heading with its count.
    func testPerspectiveGroups() throws {
        let claims = [try claim("a", observer: "external:linkedin"), try claim("b", observer: "bob-example"),
                      try claim("c"), try claim("d", validTo: "2026-05-01")]
        let groups = PerspectiveGroups.of(claims)
        XCTAssertEqual(groups.map(\.observer.label), ["Cicada", "You", "linkedin"])
        XCTAssertEqual(groups.map { $0.claims.count }, [1, 1, 1])
        XCTAssertEqual(PerspectiveGroups.heading(groups[0]), "Cicada · 1")
    }

    func testDivergenceIsOneLine() throws {
        let claims = [try claim("a", object: "sqlite-vec"), try claim("b", observer: "bob-example", object: "csv-storage")]
        let d = PerspectiveGroups.divergences(claims)
        XCTAssertEqual(d.map(\.key.id), ["uses|engineering"])
        XCTAssertEqual(d.first?.line, "Cicada: sqlite-vec · You: csv-storage")
    }

    /// DR-54 — a claim id reaches `.help`, never the row.
    func testSupersededSaysWordsNotAnId() {
        let s = BeliefTimelineWords.superseded(by: "clm_2026-05-05_009")
        XCTAssertEqual(s.text, "Superseded by a newer belief")
        XCTAssertEqual(s.help, "Claim clm_2026-05-05_009")
        XCTAssertFalse(s.text.contains("clm_"))
    }
}
