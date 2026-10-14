import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// Owner 2026-10-14 (G61) — "Where this comes from": the wire (`GET /entities/{id}/sources/overview`, pinned by the
/// backend's own `api/tests/fixtures/page_sources_overview.json`), its words, the way back from a belief to its
/// source, the in-memory cache, and the section's layout at the column floor. Renders for review are written only when
/// `PAGE_SOURCES_RENDER_DIR` names a folder.
final class PageSourcesTests: XCTestCase {
    private static func fixture() throws -> PageSourcesOverview {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .deletingLastPathComponent()   // app
            .deletingLastPathComponent()   // repo root
        let file = root.appendingPathComponent("api/tests/fixtures/page_sources_overview.json")
        return try JSONDecoder().decode(PageSourcesOverview.self, from: Data(contentsOf: file))
    }

    private let en = Locale(identifier: "en_US")

    // MARK: The wire

    func testTheBackendsPayloadDecodesWhole() throws {
        let o = try Self.fixture()
        XCTAssertEqual(o.entityId, "alpha-co")
        XCTAssertEqual(o.sources.map(\.scope), [.site, .fact, .page])
        let team = o.sources[1]
        XCTAssertEqual(team.source.ref, "https://example.org/alpha-co/team")
        XCTAssertEqual(team.source.addedBy, "user")
        XCTAssertEqual(team.site, "example.org")
        XCTAssertEqual(team.factCount, 5)
        XCTAssertEqual(team.facts.map(\.claimId), ["clm_employs_4", "clm_employs_3", "clm_employs_2", "clm_employs_1"])
        XCTAssertEqual(team.facts[0].key, BeliefKey(predicate: "employs", context: "general"))
        XCTAssertEqual(o.sources[0].title, "Alpha Co")
        XCTAssertEqual(o.links.count, 2)
        XCTAssertEqual(o.links[0].cameFrom?.episode, "ep_2026-09-03_001")
        XCTAssertEqual(o.links[0].cameFrom?.evidence?.kind, .user)
        XCTAssertNil(o.links[1].cameFrom)
        XCTAssertEqual(o.conversations.total, 3)
        XCTAssertEqual(o.conversations.apps.first?.harness, "claude-code")
        XCTAssertEqual([o.factsTotal, o.factsWithSource], [7, 6])
        XCTAssertEqual(o.lastChecked, "2026-10-05")
    }

    func testAnOlderPayloadDecodesAsEmptyNeverAsAFailure() throws {
        let json = #"{"entityId": "beta-tool", "sources": [{"ref": "Ask me", "kind": "note", "addedBy": "user", "addedAt": ""}]}"#
        let o = try JSONDecoder().decode(PageSourcesOverview.self, from: Data(json.utf8))
        XCTAssertEqual(o.sources.first?.scope, .page)
        XCTAssertEqual(o.sources.first?.facts, [])
        XCTAssertEqual(o.links, [])
        XCTAssertEqual(o.conversations.total, 0)
    }

    // MARK: Words

    func testTheClosedSectionSaysHowManySourcesAndConversations() throws {
        let o = try Self.fixture()
        XCTAssertEqual(PageSourcesWords.summary(o), "· 3 sources · 3 conversations")
        XCTAssertNil(PageSourcesWords.summary(nil), "nothing known yet says nothing")
        XCTAssertEqual(PageSourcesWords.summary(nil, conversations: 4), "· 4 conversations",
                       "an older backend still counts its conversations")
        XCTAssertEqual(PageSourcesWords.summary(PageSourcesOverview(entityId: "x")), "· nothing recorded yet")
    }

    func testCoverageAndFreshnessAreSaidInWords() throws {
        let o = try Self.fixture()
        XCTAssertEqual(PageSourcesWords.coverage(o), "6 of 7 beliefs here have a place to check them.")
        XCTAssertEqual(PageSourcesWords.coverage(PageSourcesOverview(entityId: "x", factsTotal: 3)),
                       "None of the 3 beliefs here has a place to check it yet.")
        XCTAssertEqual(PageSourcesWords.coverage(PageSourcesOverview(entityId: "x", factsTotal: 2, factsWithSource: 2)),
                       "Every one of the 2 beliefs here has a place to check it.")
        XCTAssertNil(PageSourcesWords.coverage(PageSourcesOverview(entityId: "x")))
        XCTAssertEqual(PageSourcesWords.freshness(o, locale: en), "Last said Sep 3 · sources last checked Oct 5")
        XCTAssertEqual(PageSourcesWords.freshness(PageSourcesOverview(entityId: "x", lastChecked: "2026-10-05"), locale: en),
                       "Sources last checked Oct 5")
        XCTAssertNil(PageSourcesWords.freshness(PageSourcesOverview(entityId: "x")))
    }

    func testWhatASourceBacksIsSaidOnlyForAFact() throws {
        let o = try Self.fixture()
        XCTAssertNil(PageSourcesWords.backs(o.sources[0]), "the official site's title already says what it is for")
        XCTAssertEqual(PageSourcesWords.backs(o.sources[1]), "backs 5 beliefs")
        XCTAssertEqual(PageSourcesWords.moreFacts(o.sources[1]), "and 1 more")
        XCTAssertNil(PageSourcesWords.backs(o.sources[2]))
        let empty = PageSource(source: Self.source("https://example.org/x", predicate: "role"), scope: .fact)
        XCTAssertEqual(PageSourcesWords.backs(empty), "no current belief yet")
        XCTAssertNil(PageSourcesWords.moreFacts(empty))
    }

    func testALinkNamesTheConversationItCameFromTheWayAPersonWould() throws {
        let o = try Self.fixture()
        XCTAssertEqual(PageSourcesWords.linkMeta(o.links[0]), "example.net · how the launch went")
        XCTAssertEqual(PageSourcesWords.linkMeta(o.links[1]), "example.com")
        let named = try XCTUnwrap(o.links[0].cameFrom)
        let place = ProvenanceSummary.placeName(harness: named.harness, origin: named.origin)
        XCTAssertEqual(PageSourcesWords.cameFrom(named, locale: en), "\(place) · Later · Sep 3")
        let untitled = PageLinkOrigin(episode: "ep_2026-09-03_001", harness: "claude-code",
                                      said: "2026-09-03T10:00:00+00:00")
        XCTAssertEqual(PageSourcesWords.cameFrom(untitled, locale: en), "a Claude Code conversation · Sep 3")
        XCTAssertFalse(PageSourcesWords.cameFrom(untitled, locale: en).contains("ep_"), "DR-54: never an episode id")
    }

    func testAnAppsLineCountsWhatItsConversationsBack() throws {
        let o = try Self.fixture()
        let imported = o.conversations.apps[1]
        XCTAssertEqual(PageSourcesWords.appDetail(imported, locale: en), "1 conversation · 1 belief · 2 passages · last Aug 12")
        let export = o.conversations.apps[2]
        XCTAssertEqual(PageSourcesWords.appDetail(export, locale: en), "1 conversation · 1 belief",
                       "a memory export entry has no day it was said")
        XCTAssertEqual(PageSourcesWords.appName(o.conversations.apps[0]), "Claude Code")
    }

    func testTheChipNamesTheSiteElseTheKind() {
        XCTAssertEqual(PageSourcesWords.lookUpChip(PageSource(source: Self.source("https://example.org/a"),
                                                              site: "example.org")), "Check at example.org")
        XCTAssertEqual(PageSourcesWords.lookUpChip(PageSource(source: Self.source("Ask me", kind: "note"))), "Check a note")
        XCTAssertEqual(PageSourcesWords.lookUpChip(PageSource(source: Self.source("~/notes", kind: "path"))), "Check a file")
    }

    // MARK: The way back from a belief to its source

    func testABeliefFindsTheBestSourceForItsOwnFactOnly() {
        let agent = PageSource(source: Self.source("https://agent.example.com/", predicate: "Works-At",
                                                   addedBy: "claude-code"), site: "example.com", scope: .fact)
        let person = PageSource(source: Self.source("https://mine.example.org/", predicate: "works-at"),
                                site: "example.org", scope: .fact)
        let verified = PageSource(source: Self.source("https://checked.example.net/", predicate: "works-at",
                                                      addedBy: "agent", verified: true),
                                  site: "example.net", scope: .fact)
        let site = PageSource(source: Self.source("https://alpha.example/", predicate: "website"), scope: .site)
        let page = PageSource(source: Self.source("Ask me", kind: "note"), scope: .page)
        let o = PageSourcesOverview(entityId: "bob-example", sources: [agent, site, verified, page, person])
        XCTAssertEqual(o.lookUps(predicate: "works-at").map(\.source.ref),
                       ["https://mine.example.org/", "https://checked.example.net/", "https://agent.example.com/"])
        XCTAssertEqual(o.lookUps(predicate: "website"), [], "the official site backs the page, not one belief")
        XCTAssertEqual(o.lookUps(predicate: ""), [])
        XCTAssertEqual(o.backing(person.source)?.site, "example.org", "a row finds its backing after the list changed")
        XCTAssertNotEqual(PageSourcesWords.anchor(person.id), PageSourcesWords.anchor(agent.id))
    }

    // MARK: The cache (never a Store domain, R-PB11)

    @MainActor
    func testTheOverviewRevalidatesByETagAndKeepsTheValueOnA304() async throws {
        let api = FakeProvenanceAPI()
        api.overview = try Self.fixture()
        let cache = ProvenanceCache(api: api)
        let first = await cache.sourcesOverview(entityId: "alpha-co")
        XCTAssertEqual(first.value?.factsTotal, 7)
        api.overviewNotModified = true
        let second = await cache.sourcesOverview(entityId: "alpha-co")
        XCTAssertEqual(second.value?.factsTotal, 7)
        XCTAssertEqual(api.lastOverviewETag, "\"o1\"", "the stored validator is sent back")
        XCTAssertEqual(api.overviewCalls, 2, "asked again every time: a source just added shows at once")
    }

    @MainActor
    func testAFailureKeepsTheLastCopyA404IsGoneAndABankSwitchForgets() async throws {
        let api = FakeProvenanceAPI()
        api.overview = try Self.fixture()
        let cache = ProvenanceCache(api: api)
        _ = await cache.sourcesOverview(entityId: "alpha-co")
        api.overviewError = APIError.serverUnreachable
        let offline = await cache.sourcesOverview(entityId: "alpha-co")
        XCTAssertEqual(offline.value?.entityId, "alpha-co", "never blank on a transport failure")
        api.overviewError = APIError.httpError(404, "gone")
        if case .gone = await cache.sourcesOverview(entityId: "alpha-co") {} else { XCTFail("a 404 reads as gone") }
        api.overviewError = nil
        _ = await cache.sourcesOverview(entityId: "alpha-co")
        cache.reset()
        api.overviewError = APIError.serverUnreachable
        if case .failed = await cache.sourcesOverview(entityId: "alpha-co") {} else {
            XCTFail("no last-known-good copy survives a bank switch")
        }
        XCTAssertNil(api.lastOverviewETag, "the old bank's validator is forgotten too")
    }

    // MARK: The section

    func testTheSectionOpensOnCoverageAndFreshnessOrSaysNothingIsRecorded() throws {
        XCTAssertEqual(PageSourcesSection.lines(try Self.fixture())?.count, 2)
        XCTAssertEqual(PageSourcesSection.lines(PageSourcesOverview(entityId: "x")), [Copy.PageSources.nothingYet])
    }

    /// DR-36 / DR-70 — at the column floor, at every zoom, the section never wants more than its column.
    @MainActor
    func testTheSectionNeverWantsMoreThanItsColumn() throws {
        defer { CicadaTheme.uiScale = 1.0 }
        for scale in [0.8, 1.0, 1.4] {
            CicadaTheme.uiScale = scale
            let width = GraphColumns.entityMin * CGFloat(scale)
            for (overview, provenance) in [(try Self.fixture(), Self.provenance()), (Self.emptyOverview(), Self.emptyProvenance())] {
                let renderer = ImageRenderer(content: Self.section(overview, provenance, width: width))
                renderer.proposedSize = ProposedViewSize(width: width, height: nil)
                let size = try XCTUnwrap(renderer.nsImage).size
                XCTAssertLessThanOrEqual(size.width, width + 0.5, "\(scale): \(size.width)")
            }
        }
    }

    /// Offscreen review renders (never the app): a synthetic page with several sources, links and conversations, and
    /// one with none, in light and dark.
    @MainActor
    func testRenderTheSectionForReview() throws {
        guard let dir = ProcessInfo.processInfo.environment["PAGE_SOURCES_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set PAGE_SOURCES_RENDER_DIR to write the review renders")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        defer { CicadaTheme.mode = .dark; CicadaTheme.uiScale = 1.0 }
        CicadaTheme.uiScale = 1.0
        let width: CGFloat = 560
        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            let cases: [(String, PageSourcesOverview, ProvenanceSectionState, String?)] = [
                ("full", try Self.fixture(), Self.provenance(), nil),
                ("highlighted", try Self.fixture(), Self.provenance(), try Self.fixture().sources[1].id),
                ("empty", Self.emptyOverview(), Self.emptyProvenance(), nil),
            ]
            for (name, overview, provenance, highlighted) in cases {
                let view = Self.section(overview, provenance, width: width, highlighted: highlighted)
                    .padding(16)
                    .background(CicadaTheme.bgBase)
                    .environment(\.colorScheme, mode == .dark ? .dark : .light)
                let renderer = ImageRenderer(content: view)
                renderer.proposedSize = ProposedViewSize(width: width + 32, height: nil)
                renderer.scale = 2
                let image = try XCTUnwrap(renderer.nsImage)
                let tiff = try XCTUnwrap(image.tiffRepresentation)
                let png = try XCTUnwrap(NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:]))
                let file = URL(fileURLWithPath: dir)
                    .appendingPathComponent("where-this-comes-from-\(name)-\(mode == .dark ? "dark" : "light").png")
                try png.write(to: file)
            }
            // The way back: a belief whose fact has a source wears its chip beside the evidence.
            let overview = try Self.fixture()
            let beliefs = WhatCicadaKnowsSection(claims: try Self.claims(), lookUp: { overview.lookUps(predicate: $0.predicate).first },
                                                 onLookUp: { _ in })
                .frame(width: width, alignment: .leading)
                .padding(16)
                .background(CicadaTheme.bgBase)
                .environment(\.colorScheme, mode == .dark ? .dark : .light)
                .environment(Self.store())
            let renderer = ImageRenderer(content: beliefs)
            renderer.proposedSize = ProposedViewSize(width: width + 32, height: nil)
            renderer.scale = 2
            let image = try XCTUnwrap(renderer.nsImage)
            let png = try XCTUnwrap(NSBitmapImageRep(data: try XCTUnwrap(image.tiffRepresentation))?
                .representation(using: .png, properties: [:]))
            try png.write(to: URL(fileURLWithPath: dir)
                .appendingPathComponent("belief-look-up-chip-\(mode == .dark ? "dark" : "light").png"))
        }
    }

    private static func claims() throws -> [Claim] {
        let rows = [("clm_employs_4", "employs", "alpha-co employs person-4"),
                    ("clm_uses_0", "uses", "alpha-co uses sqlite-vec")]
        return try rows.map { id, predicate, text in
            try JSONDecoder().decode(Claim.self, from: Data(#"{"id":"\#(id)","text":"\#(text)","subject":"alpha-co","predicate":"\#(predicate)","context":"general","object":"x","validFrom":"2026-09-01","recordedAt":"2026-09-01","sourceEpisodes":["ep_2026-09-01_001"]}"#.utf8))
        }
    }

    @MainActor
    private static func store() -> Store {
        Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)),
              api: FakeSyncAPI())
    }

    // MARK: Helpers

    static func source(_ ref: String, kind: String = "url", predicate: String? = nil, addedBy: String = "user",
                       verified: Bool = false) -> EntitySource {
        EntitySource(ref: ref, kind: kind, predicate: predicate, addedBy: addedBy, addedAt: "2026-10-01",
                     verified: verified ? EntitySource.Verified(at: "2026-10-02", how: "name+content") : nil,
                     trusted: addedBy == "user" || verified)
    }

    @MainActor
    private static func section(_ overview: PageSourcesOverview, _ provenance: ProvenanceSectionState, width: CGFloat,
                                highlighted: String? = nil) -> some View {
        let store = Self.store()
        return PageSourcesSection(entityId: overview.entityId, entityType: .company, overview: overview,
                                  sourcesLoaded: true, sources: .constant(overview.sources.map(\.source)),
                                  provenance: provenance, highlighted: highlighted)
            .frame(width: width, alignment: .leading)
            .environment(store)
            .environment(AppRouter())
            .environment(ProvenanceRouter())
    }

    private static func emptyOverview() -> PageSourcesOverview {
        PageSourcesOverview(entityId: "beta-tool", entityType: "tool")
    }

    private static func emptyProvenance() -> ProvenanceSectionState {
        .loaded(EntityProvenance(entityId: "beta-tool"))
    }

    private static func provenance() -> ProvenanceSectionState {
        let rows = [
            ProvenanceConversation(conversationId: "s-1", episodeId: "ep_2026-09-03_001", title: "Team chat",
                                   harness: "claude-code", origin: "claude-code",
                                   timestamp: "2026-09-03T10:00:00+00:00", claimCount: 5),
            ProvenanceConversation(conversationId: "conv-import-1", episodeId: "ep_2026-08-12_001",
                                   title: "Planning notes", origin: "chatgpt-export",
                                   timestamp: "2026-08-12T09:00:00+00:00", claimCount: 1),
        ]
        return .loaded(EntityProvenance(
            entityId: "alpha-co", entityName: "Alpha Co", entityType: "company",
            contributors: [ProvenanceContributor(author: "claude-code", kind: "harness", claims: 5, commits: 2),
                           ProvenanceContributor(author: "user", kind: "user", claims: 1, commits: 1)],
            conversations: rows,
            totals: ProvenanceTotals(claims: 7, withSpan: 4, legacy: 1, conversations: 3,
                                     firstSaid: "2026-08-12T09:00:00+00:00", lastSaid: "2026-09-03T10:00:00+00:00")))
    }
}
