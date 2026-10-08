import XCTest
import SwiftUI
@testable import CicadaApp

/// Main-thread cost of the entity card on an owner-sized page (`OwnerScaleFixture`): what a SwiftUI render of the
/// card recomputes. Prints `BENCH` lines (best of five, ms) for the report; the two print-only benches (~9 s) run only
/// with `CICADA_APP_BENCH=1`, the budget test always.
final class OwnerScaleBenchTests: XCTestCase {
    private func ms(_ label: String, runs: Int = 5, _ body: () -> Void) -> Double {
        body()
        var best = Double.infinity
        for _ in 0..<runs {
            let start = DispatchTime.now().uptimeNanoseconds
            body()
            best = min(best, Double(DispatchTime.now().uptimeNanoseconds - start) / 1_000_000)
        }
        print(String(format: "BENCH %-34@ %8.2f ms", label as NSString, best))
        return best
    }

    private func optIn() throws {
        guard ProcessInfo.processInfo.environment["CICADA_APP_BENCH"] == "1" else {
            throw XCTSkip("set CICADA_APP_BENCH=1 to print the owner-scale numbers")
        }
    }

    func testPrintTheCardsPerRenderDerivations() throws {
        try optIn()
        let f = OwnerScaleFixture.self
        XCTAssertEqual(f.claims.count, f.claimCount)
        print("BENCH markdown bytes \(f.markdown.utf8.count)")
        _ = ms("EntityProse.stripClaimsFence") { _ = EntityProse.stripClaimsFence(f.markdown) }
        _ = ms("EntityHeaderWords.summary") { _ = EntityHeaderWords.summary(markdown: f.markdown, isStub: false) }
        _ = ms("EntityProse.showsBeliefs") { _ = EntityProse.showsBeliefs(markdown: f.markdown, isStub: false) }
        _ = ms("claims.filter(isValid)") { _ = f.claims.filter(\.isValid) }
        _ = ms("EntityTabs.tabs") { _ = EntityTabs.tabs(claims: f.claims, historyCount: 46) }
        _ = ms("PersonBeliefs.ordered") { _ = PersonBeliefs.ordered(f.claims) }
        _ = ms("PersonFacts.cells") {
            _ = PersonFacts.cells(entity: f.entity, claims: f.claims, provenance: f.provenance,
                                  names: EntityNames(byId: [:]), typeOf: { _ in nil }, picture: nil,
                                  docs: EvidenceDocIndex.from(f.provenance), today: ISODay.today())
        }
        _ = ms("EvidenceDocIndex.from") { _ = EvidenceDocIndex.from(f.provenance) }
        _ = ms("PersonMapLayout.make") { _ = PersonMapLayout.make(personId: f.ownerId, nodes: f.nodes, edges: f.edges) }
        _ = ms("PersonMapLayout.projects") {
            _ = PersonMapLayout.projects(personId: f.ownerId, nodes: f.nodes, edges: f.edges)
        }
        _ = ms("PerspectiveGroups.of+divergences") {
            _ = PerspectiveGroups.of(f.claims)
            _ = PerspectiveGroups.divergences(f.claims)
        }
        let keys = TimelineKeys.rows(claims: f.claims, requested: nil)
        print("BENCH timeline keys \(keys.count)")
        _ = ms("TimelineKeys.rows+summary each") {
            for key in TimelineKeys.rows(claims: f.claims, requested: nil) {
                _ = TimelineKeys.summary(key, claims: f.claims)
            }
        }
        _ = ms("renderWikilinks x3500") { for c in f.claims { _ = renderWikilinks(c.text) } }
    }

    /// What the card computes per render now, against what it computes once per load. Generous budgets for a debug
    /// build on a loaded machine; before this change the per-render path was ~200 ms (`BENCH` lines in the report).
    @MainActor
    func testTheCardsPerRenderPathIsCheapAndTheDigestIsBuiltOnce() {
        let f = OwnerScaleFixture.self
        let digest = ClaimDigest(f.claims)
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        store.graph.value = GraphResponse(nodes: f.nodes, links: f.edges)
        store.graph.loadedAt = Date()
        let graph = GraphViewModel(store: store)
        let today = ISODay.today()
        let build = ms("ClaimDigest (once per load)") { _ = ClaimDigest(f.claims) }
        let perRender = ms("card per-render path") {
            _ = EntityHeaderWords.summary(markdown: f.markdown, isStub: false)
            _ = EntityTabs.tabs(digest: digest, historyCount: 46)
            _ = PersonFacts.cells(entity: f.entity, claims: digest.current, provenance: f.provenance,
                                  names: EntityNames(byId: [:]), typeOf: { graph.node($0)?.type }, picture: nil,
                                  docs: EvidenceDocIndex.from(f.provenance), today: today)
            _ = EvidenceDocIndex.from(f.provenance)
            _ = graph.personMap(f.ownerId)
            _ = graph.personProjectIds(f.ownerId)
        }
        XCTAssertEqual(graph.personMap(f.ownerId), PersonMapLayout.make(personId: f.ownerId, nodes: f.nodes, edges: f.edges))
        XCTAssertEqual(graph.personProjectIds(f.ownerId),
                       PersonMapLayout.projects(personId: f.ownerId, nodes: f.nodes, edges: f.edges))
        XCTAssertEqual(digest.newestFirst.map(\.id), PersonBeliefs.ordered(f.claims).map(\.id))
        XCTAssertEqual(digest.current.count, f.claims.filter(\.isValid).count)
        XCTAssertLessThan(perRender, 25, "the card's per-render work on an owner-sized page")
        XCTAssertLessThan(build, 1_000)
    }

    /// What expanding every belief in place costs to lay out (a plain `VStack` builds every row).
    @MainActor
    func testPrintTheCostOfLayingOutEveryBeliefRow() throws {
        try optIn()
        for n in [100, 1_000] {
            let rows = Array(OwnerScaleFixture.claims.prefix(n))
            let view = VStack(alignment: .leading, spacing: 2) {
                ForEach(rows) { BeliefRow(claim: $0, onOpenTimeline: {}, signed: true) }
            }
            _ = ms("layout \(n) BeliefRows", runs: 1) {
                let renderer = ImageRenderer(content: view)
                renderer.proposedSize = ProposedViewSize(width: 504, height: nil)
                _ = renderer.nsImage?.size
            }
        }
    }
}
