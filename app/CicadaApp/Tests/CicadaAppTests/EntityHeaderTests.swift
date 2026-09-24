import SwiftUI
import XCTest
@testable import CicadaApp

/// R-DG14 … R-DG16 — the entity column's header and tabs, pure, plus one fit test.
final class EntityHeaderTests: XCTestCase {
    override func tearDown() {
        CicadaTheme.uiScale = 1.0
        super.tearDown()
    }

    private func claim(_ id: String, predicate: String = "uses", context: String = "engineering",
                       observer: String = "agent", object: String = "sqlite-vec", validTo: String? = nil) throws -> Claim {
        let to = validTo.map { #","validTo":"\#($0)""# } ?? ""
        return try JSONDecoder().decode(Claim.self, from: Data(#"{"id":"\#(id)","text":"t","predicate":"\#(predicate)","context":"\#(context)","observer":"\#(observer)","object":"\#(object)","validFrom":"2026-04-01"\#(to)}"#.utf8))
    }

    /// R-DG14 — the mock's four steps, boundaries included.
    func testConfidenceIsWords() {
        let cases: [(Double, String)] = [(0.92, "very confident"), (0.85, "very confident"), (0.849, "fairly confident"),
                                         (0.6, "fairly confident"), (0.59, "unsure"), (0.4, "unsure"), (0.39, "doubtful")]
        for (value, words) in cases { XCTAssertEqual(EntityHeaderWords.confidence(value), words, "\(value)") }
    }

    func testTheStatusLineAndItsHelp() {
        XCTAssertEqual(EntityHeaderWords.statusLine(status: .active, confidence: 0.92), "Active · very confident")
        XCTAssertEqual(EntityHeaderWords.statusLine(status: .decaying, confidence: 0.5), "Fading · unsure")
        XCTAssertEqual(EntityHeaderWords.statusHelp(status: .active, confidence: 0.92), "Confidence 92 out of 100")
        let fading = EntityHeaderWords.statusHelp(status: .decaying, confidence: 0.5)
        XCTAssertTrue(fading.hasPrefix("Confidence 50 out of 100"))
        XCTAssertTrue(fading.contains("fading"))
        XCTAssertFalse(fading.contains("%"), "DR-59")
    }

    /// R-DG15 — the Summary, never the agentic-write placeholder; a stub's preview until the page lands.
    func testTheHeaderSummary() {
        let page = "## Summary\nA [[FastAPI]] dashboard.\n\n## Notes\nMore."
        XCTAssertEqual(EntityHeaderWords.summary(markdown: page, isStub: false), "A [[FastAPI]] dashboard.")
        XCTAssertNil(EntityHeaderWords.summary(markdown: "## Summary\nAlpha project — created via agentic write.", isStub: false))
        XCTAssertNil(EntityHeaderWords.summary(markdown: "# Alpha project\nJust prose.", isStub: false))
        XCTAssertEqual(EntityHeaderWords.summary(markdown: "A short preview.", isStub: true), "A short preview.")
        XCTAssertNil(EntityHeaderWords.summary(markdown: "", isStub: true))
    }

    /// R-DG16 — the brief's order; a count only once it is known.
    func testTabsInOrderWithCountsOnlyWhenKnown() throws {
        let unknown = EntityTabs.tabs(claims: nil, historyCount: nil)
        XCTAssertEqual(unknown.map(\.label), ["Content", "Perspectives", "History", "Timeline"])
        XCTAssertEqual(unknown.map(\.id), [.content, .perspectives, .history, .timeline])
        XCTAssertEqual(unknown.map(\.count), [nil, nil, nil, nil])
        let claims = [try claim("c1", validTo: "2026-05-01"), try claim("c2"), try claim("c3", predicate: "role")]
        let known = EntityTabs.tabs(claims: claims, historyCount: 4)
        XCTAssertEqual(known.map(\.count), [nil, 2, 4, 1], "2 current beliefs, 4 commits, 1 contested (uses|engineering)")
    }

    func testTheHistoryCountIsWhatIsInHand() {
        let entry = EntityHistoryEntry(date: .now, changeType: .updated, description: "d")
        XCTAssertNil(EntityTabs.historyCount(embedded: [], fetched: nil), "not fetched yet")
        XCTAssertEqual(EntityTabs.historyCount(embedded: [entry, entry], fetched: nil), 2)
        XCTAssertEqual(EntityTabs.historyCount(embedded: [], fetched: []), 0)
    }

    func testContestedIsTwoOrMoreClaimsPerKey() throws {
        let claims = [try claim("a"), try claim("b", validTo: "2026-05-01"), try claim("c", predicate: "role"),
                      try claim("d", context: "career"), try claim("e", context: "career")]
        XCTAssertEqual(EntityTabs.contested(claims).map(\.id), ["uses|career", "uses|engineering"])
    }

    /// DR-31 / DR-70 — at the 440 floor, at every zoom, the header never wants more than its column: a long
    /// name wraps, a long Back target truncates, the tabs with a five-digit count still fit.
    @MainActor
    func testTheHeaderNeverWantsMoreThanItsColumn() throws {
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        let entity = Entity(id: "alpha-project", name: String(repeating: "Alpha project ", count: 8), type: .project,
                            status: .decaying, confidence: 0.42, created: "2026-01-05", lastReferenced: "2026-08-25",
                            decayRate: 0.05, sourceEpisodes: [], tags: [], related: [], version: 1,
                            markdownContent: "## Summary\n" + String(repeating: "A long summary sentence. ", count: 20),
                            history: [])
        for scale in [0.8, 1.0, 1.4] {
            CicadaTheme.uiScale = scale
            let width = GraphColumns.entityMin * CGFloat(scale)
            let header = EntityCardHeader(
                entity: entity, summary: EntityHeaderWords.summary(markdown: entity.markdownContent, isStub: false),
                isStub: false, canGoBack: true, backTargetName: String(repeating: "Bob example ", count: 6),
                onBack: {}, showsClose: true, onClose: {},
                tabs: EntityTabs.tabs(claims: [], historyCount: 12345), selection: .constant(.content),
                inset: EntityCardStyle.column.inset
            ).environment(store)
            let renderer = ImageRenderer(content: header)
            renderer.proposedSize = ProposedViewSize(width: width, height: nil)
            let size = try XCTUnwrap(renderer.nsImage).size
            XCTAssertLessThanOrEqual(size.width, width + 0.5, "\(scale): \(size.width)")
        }
    }

    /// F-12 (R-PE16) — the person hero and a six-cell strip never want more than the column, at every zoom.
    @MainActor
    func testThePersonHeroNeverWantsMoreThanItsColumn() throws {
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        let entity = Entity(id: "leo-example", name: String(repeating: "Leo Example ", count: 6), type: .person,
                            status: .active, confidence: 0.92, created: "2026-03-12", lastReferenced: "2026-09-24",
                            decayRate: 0.05, sourceEpisodes: [], tags: [], related: [], version: 1,
                            markdownContent: "## Summary\n" + String(repeating: "Robotics engineer at Northwind. ", count: 8),
                            history: [])
        let facts = [PersonFact.Kind.worksAt, .role, .knownSince, .lastMentioned, .conversations, .contacts].map {
            PersonFact(kind: $0, label: "Last mentioned", value: String(repeating: "Northwind ", count: 5),
                       line: "Claude Code · 10:42", marks: ["claude-code", "codex"])
        }
        for scale in [0.8, 1.0, 1.4] {
            CicadaTheme.uiScale = scale
            let width = GraphColumns.entityMin * CGFloat(scale)
            let header = EntityCardHeader(
                entity: entity, summary: EntityHeaderWords.summary(markdown: entity.markdownContent, isStub: false),
                isStub: false, canGoBack: false, backTargetName: nil, onBack: {}, showsClose: true, onClose: {},
                tabs: EntityTabs.tabs(claims: [], historyCount: 3), selection: .constant(.content),
                inset: EntityCardStyle.card.inset, facts: facts, onShowOnGraph: {}
            ).environment(store)
            let renderer = ImageRenderer(content: header)
            renderer.proposedSize = ProposedViewSize(width: width, height: nil)
            let size = try XCTUnwrap(renderer.nsImage).size
            XCTAssertLessThanOrEqual(size.width, width + 0.5, "\(scale): \(size.width)")
        }
    }
}
