import SwiftUI
import XCTest
@testable import CicadaApp

/// G61 S3-a — a page holds many sources and the person manages them on the card. The fixture is the server's own wire
/// (`api/tests/test_sources_app_fixture.py` fails on any drift), so nothing here tests against a wire the server no
/// longer sends.
enum SourcesFixtures {
    private static let url = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()   // CicadaAppTests
        .deletingLastPathComponent()   // Tests
        .appendingPathComponent("fixtures/sources-living.json")

    static func load(file: StaticString = #filePath, line: UInt = #line) throws -> [EntitySource] {
        let list = try JSONDecoder().decode(EntitySourceList.self, from: Data(contentsOf: url))
        XCTAssertEqual(list.sources.count, 7, "read \(url.path) — a test over no sources passes vacuously",
                       file: file, line: line)
        return list.sources
    }
}

final class SourcesDecodeTests: XCTestCase {
    func testTheWireDecodesEveryNewField() throws {
        let rows = try SourcesFixtures.load()
        let profile = try XCTUnwrap(rows.first { $0.ref == "https://example.com/in/bob" })
        XCTAssertEqual(profile.origin, "remote:ab12cd34")
        XCTAssertEqual(profile.entity, "media-alpha-profile")
        XCTAssertNil(profile.verified)
        XCTAssertEqual(rows.first { $0.ref == "https://example.com/staff-directory" }?.trusted, true, "the person's own entry")
        XCTAssertEqual(profile.trusted, false, "an app's, not yet taken")
        XCTAssertEqual(rows.first { $0.ref == "https://example.com/team" }?.trusted, false, "an agent's, not yet taken")
        XCTAssertEqual(profile.effectiveAccess, "unknown")
        XCTAssertEqual(rows.first { $0.ref == "https://example.com/gone" }?.entity, nil, "a stale link is served as none")
        XCTAssertEqual(rows.first { $0.ref == "https://example.com/old-team" }?.accepted, true)
    }

    func testAnOlderBackendStillDecodes() throws {
        let json = #"{"ref":"https://example.com/a","kind":"url","addedBy":"user","addedAt":"2026-08-30"}"#
        let source = try JSONDecoder().decode(EntitySource.self, from: Data(json.utf8))
        XCTAssertNil(source.entity)
        XCTAssertNil(source.origin)
    }

    func testVerifiedDecodes() throws {
        let json = #"{"ref":"https://example.com/a","kind":"url","addedBy":"cicada","addedAt":"2026-08-30","verified":{"at":"2026-10-02","how":"name+content"}}"#
        XCTAssertEqual(try JSONDecoder().decode(EntitySource.self, from: Data(json.utf8)).verified?.how, "name+content")
    }
}

final class SourceGroupsTests: XCTestCase {
    func testGroupsByFactInFileOrderWithTheWholePageLast() throws {
        let groups = SourceGroups.groups(try SourcesFixtures.load())
        XCTAssertEqual(groups.map(\.title), ["Works at", "Profile", "Anything"])
        XCTAssertEqual(groups[0].rows.count, 4, "several sources back one fact")
        XCTAssertEqual(groups[1].rows.count, 2)
        XCTAssertEqual(groups[2].rows.map(\.ref), ["https://example.com/about"])
    }

    func testFactWords() {
        XCTAssertEqual(SourceGroups.title("works-at"), "Works at")
        XCTAssertEqual(SourceGroups.title("website"), "Official site")
        XCTAssertEqual(SourceGroups.title(nil), "Anything")
        XCTAssertEqual(SourceGroups.title("  "), "Anything")
        XCTAssertEqual(SourceGroups.slug("Works at"), "works-at")
        XCTAssertEqual(SourceGroups.slug(" lives in! "), "lives-in")
    }

    func testOnlyAnUntakenEntryBelongingToSomeoneElseCanBeTaken() throws {
        let rows = try SourcesFixtures.load()
        func source(_ ref: String) throws -> EntitySource { try XCTUnwrap(rows.first { $0.ref == ref }) }
        XCTAssertTrue(try source("https://example.com/team").canBeTaken)
        XCTAssertFalse(try source("https://example.com/staff-directory").canBeTaken, "the person's own")
        XCTAssertFalse(try source("https://example.com/old-team").canBeTaken, "already taken")
    }
}

final class SourceChangeTests: XCTestCase {
    func testEachChangeAppliesWhatTheServerWillAnswer() throws {
        let rows = try SourcesFixtures.load()
        let team = try XCTUnwrap(rows.first { $0.ref == "https://example.com/team" })
        XCTAssertNil(SourceChange.remove.apply(to: team))
        XCTAssertEqual(SourceChange.useThis.apply(to: team)?.accepted, true)
        XCTAssertEqual(SourceChange.access("signed_in").apply(to: team)?.access, "signed_in")
        XCTAssertEqual(SourceChange.link("media-alpha-profile").apply(to: team)?.entity, "media-alpha-profile")
        XCTAssertNil(SourceChange.unlink.apply(to: try XCTUnwrap(rows.first { $0.entity != nil }))?.entity)
        XCTAssertEqual(SourceChange.fact("Lives in").apply(to: team)?.predicate, "lives-in")
        XCTAssertNil(SourceChange.fact("  ").apply(to: team)?.predicate, "no words makes it cover the page")
    }

    func testTheListAfterAChangeTouchesOnlyThatEntry() throws {
        let rows = try SourcesFixtures.load()
        let team = try XCTUnwrap(rows.first { $0.ref == "https://example.com/team" })
        let removed = SourceList.applying(.remove, toId: team.id, in: rows)
        XCTAssertEqual(removed.count, rows.count - 1)
        XCTAssertFalse(removed.contains { $0.id == team.id })
        let linked = SourceList.applying(.link("media-alpha-profile"), toId: team.id, in: rows)
        XCTAssertEqual(linked.map(\.ref), rows.map(\.ref), "order kept")
        XCTAssertEqual(linked.filter { $0.entity != nil }.count, rows.filter { $0.entity != nil }.count + 1)
    }

    func testTheBodyIsKeyedByRefAndPredicateNeverAnIndex() throws {
        let team = try XCTUnwrap(try SourcesFixtures.load().first { $0.ref == "https://example.com/team" })
        let remove = SourceChange.remove.body(for: team)
        XCTAssertEqual(remove["ref"] as? String, "https://example.com/team")
        XCTAssertEqual(remove["predicate"] as? String, "works-at")
        XCTAssertEqual(remove["action"] as? String, "remove")
        XCTAssertEqual(SourceChange.fact("Lives in").body(for: team)["newPredicate"] as? String, "lives-in")
        XCTAssertEqual(SourceChange.useThis.body(for: team)["accepted"] as? Bool, true)
        XCTAssertTrue(SourceChange.unlink.body(for: team)["entity"] is NSNull, "an unlink sends an explicit null")
        XCTAssertNil(SourceChange.access("public").body(for: team)["entity"], "an absent key leaves the link alone")
    }

    func testOnlyARemovalSaysAnythingWhenItLands() {
        XCTAssertEqual(SourceChange.remove.doneMessage, "Removed. Cicada won't suggest it again.")
        XCTAssertNil(SourceChange.useThis.doneMessage)
    }
}

final class SourceLinkCandidatesTests: XCTestCase {
    private func node(_ id: String, _ name: String, type: EntityType = .concept, hub: Bool = false, facet: Bool = false) -> GraphNode {
        GraphNode(id: id, name: name, type: type, isHub: hub, isFacet: facet)
    }

    func testOnlyRealPagesOtherThanThePageItselfAreOffered() {
        let nodes = [node("alpha-page", "Alpha Page"), node("bob-example", "Alpha Bob"), node("hub-a", "Alpha Hub", hub: true),
                     node("alpha-page#work", "Alpha Page", facet: true), node("repo:alpha", "Alpha repo", type: .unknown)]
        XCTAssertEqual(SourceLinkCandidates.matching("alpha", nodes: nodes, excluding: "bob-example").map(\.id), ["alpha-page"])
        XCTAssertTrue(SourceLinkCandidates.matching("", nodes: nodes, excluding: "bob-example").isEmpty)
    }
}

@MainActor
final class EntitySourceWriteTests: XCTestCase {
    private final class Box { var sources: [EntitySource] = [] }

    private func setup() throws -> (Store, FakeSyncAPI, Box, EntitySource) {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: api)
        let box = Box()
        box.sources = try SourcesFixtures.load()
        let team = try XCTUnwrap(box.sources.first { $0.ref == "https://example.com/team" })
        return (store, api, box, team)
    }

    func testARemovalPaintsAtOnceAndTheServersListSettlesIt() async throws {
        let (store, api, box, team) = try setup()
        let after = box.sources.filter { $0.id != team.id }
        api.sourceReply = after
        api.gateWrites = true
        let binding = Binding(get: { box.sources }, set: { box.sources = $0 })
        let write = EntitySourceWrite(entityId: "bob-example", source: team, change: .remove, sources: binding)
        let task = Task { await store.perform(write) }
        await api.waitForParkedWrite()
        XCTAssertFalse(box.sources.contains { $0.id == team.id }, "painted before the answer")
        api.releaseWriteGate()
        let landed = await task.value
        XCTAssertTrue(landed)
        XCTAssertEqual(box.sources, after)
        XCTAssertEqual(api.writes.last, "changeEntitySource:bob-example:https://example.com/team:remove")
    }

    func testAFailedWriteRestoresTheListAndSaysTheServersSentence() async throws {
        let (store, api, box, team) = try setup()
        let before = box.sources
        api.sourceError = APIError.httpError(400, #"{"detail":"there is no page 'nobody-page' to link the source to"}"#)
        let binding = Binding(get: { box.sources }, set: { box.sources = $0 })
        let landed = await store.perform(EntitySourceWrite(entityId: "bob-example", source: team,
                                                           change: .link("nobody-page"), sources: binding))
        XCTAssertFalse(landed)
        XCTAssertEqual(box.sources, before)
        XCTAssertEqual(store.toast, "there is no page 'nobody-page' to link the source to")
    }

    func testAnUnreachableBackendToastsAPlainSentence() async throws {
        let (store, api, box, team) = try setup()
        api.sourceError = APIError.serverUnreachable
        let binding = Binding(get: { box.sources }, set: { box.sources = $0 })
        _ = await store.perform(EntitySourceWrite(entityId: "bob-example", source: team, change: .remove, sources: binding))
        XCTAssertEqual(store.toast, Copy.Graph.sourceBackendDown)
    }
}

/// G61 S3-a review — a source's own-page link is drawn on the graph but is where to look, not a relationship: the
/// person map and "What's happening" never count it.
final class SourceEdgeInPersonMapTests: XCTestCase {
    func testASourceLinkIsNotAPersonsNeighbourOrProject() throws {
        let nodes = [GraphNode(id: "bob-example", name: "Bob Example", type: .person),
                     GraphNode(id: "alpha-project", name: "Alpha Project", type: .project),
                     GraphNode(id: "media-alpha-profile", name: "Alpha Profile", type: .media)]
        let edges = [GraphEdge(source: "bob-example", target: "media-alpha-profile", label: "profile", kind: "source"),
                     GraphEdge(source: "bob-example", target: "alpha-project", label: "source", kind: "source"),
                     GraphEdge(source: "bob-example", target: "alpha-project", label: "works on")]
        let map = PersonMapLayout.make(personId: "bob-example", nodes: nodes, edges: edges)
        XCTAssertEqual(map.nodes.map(\.id), ["alpha-project"])
        XCTAssertEqual(map.total, 1)
        XCTAssertEqual(PersonMapLayout.projects(personId: "bob-example", nodes: nodes, edges: edges), ["alpha-project"])
        let onlySource = [edges[0], edges[1]]
        XCTAssertTrue(PersonMapLayout.make(personId: "bob-example", nodes: nodes, edges: onlySource).nodes.isEmpty)
        XCTAssertTrue(PersonMapLayout.projects(personId: "bob-example", nodes: nodes, edges: onlySource).isEmpty)
    }

    func testTheKindDecodesAndIsAbsentForOtherEdges() throws {
        let json = #"[{"source":"a","target":"b","label":"profile","kind":"source"},{"source":"a","target":"c","label":"uses"}]"#
        let edges = try JSONDecoder().decode([GraphEdge].self, from: Data(json.utf8))
        XCTAssertEqual(edges.map(\.isSourceLink), [true, false])
    }
}

/// G61 S3-b — a proposed official site says whether it was confirmed, in words; "Use this site" is one tap; a source row
/// asks for its mark by the site, never the URL.
final class SiteSourceWordsTests: XCTestCase {
    private let us = Locale(identifier: "en_US")

    private func site(by who: String, verified: EntitySource.Verified? = nil, checked: EntitySource.Verified? = nil,
                      trusted: Bool?, accepted: Bool? = nil) -> EntitySource {
        EntitySource(ref: "https://acme-inference.io", kind: "url", predicate: "website", addedBy: who, addedAt: "2026-09-30",
                     accepted: accepted, verified: verified, trusted: trusted, checked: checked)
    }

    func testAVerifiedSiteSaysWhenItWasConfirmed() {
        let line = FactSourceWords.line(site(by: "cicada", verified: .init(at: "2026-10-02", how: "name+content"), trusted: true), locale: us)
        XCTAssertEqual(line.forFact, "Official site")
        XCTAssertEqual(line.note, "Confirmed Oct 2")
    }

    func testAProposedSiteIsNotConfirmedYetUntilRead() {
        let proposed = site(by: "agent", trusted: false)
        XCTAssertEqual(FactSourceWords.line(proposed, locale: us).note, "Proposed, not confirmed yet")
        XCTAssertTrue(proposed.isUnconfirmedSite && proposed.canBeTaken)
        let thin = site(by: "cicada", checked: .init(at: "2026-10-02", outcome: "unconfirmed"), trusted: false)
        XCTAssertEqual(FactSourceWords.line(thin, locale: us).note, "Read, but not confirmed yet")
    }

    func testTheOwnersOwnAndATakenSiteSayNothingAboutConfirmation() {
        XCTAssertNil(FactSourceWords.line(site(by: "user", trusted: true), locale: us).note)
        XCTAssertEqual(FactSourceWords.line(site(by: "agent", trusted: true, accepted: true), locale: us).note, "You chose to use this")
        XCTAssertFalse(site(by: "user", trusted: true).isUnconfirmedSite)
        XCTAssertFalse(site(by: "agent", trusted: nil).isUnconfirmedSite, "an older backend reads as trusted")
    }

    func testOtherFactsSaySomethingElse() {
        let works = EntitySource(ref: "https://acme-inference.io/team", kind: "url", predicate: "works-at", addedBy: "cicada",
                                 addedAt: "2026-09-30", trusted: false)
        XCTAssertNil(FactSourceWords.line(works, locale: us).note)
        XCTAssertEqual(FactSourceWords.line(works, locale: us).forFact, "For works at")
    }

    func testTheEffectiveAccessSpeaksWhenNothingWasStated() {
        let signed = EntitySource(ref: "https://www.linkedin.com/company/acme", kind: "url", predicate: "profile",
                                  addedBy: "user", addedAt: "2026-09-30", effectiveAccess: "signed_in")
        XCTAssertEqual(FactSourceWords.line(signed, locale: us).readBy, "Needs sign-in")
    }

    func testTheSourceRowAsksForTheSiteNeverTheURL() {
        func key(_ ref: String, kind: String = "url") -> String? {
            SourceSite.key(of: EntitySource(ref: ref, kind: kind, addedBy: "user", addedAt: "2026-09-30"))
        }
        XCTAssertEqual(key("https://www.acme-inference.io/team/x?token=abc#frag"), "acme-inference.io")
        XCTAssertEqual(key("https://docs.acme-inference.io/a"), "acme-inference.io")
        XCTAssertEqual(key("https://www.acme.co.uk/about"), "acme.co.uk")
        XCTAssertNil(key("Ask bob-example", kind: "note"))
        XCTAssertNil(key("~/notes/a.md", kind: "path"))
        XCTAssertNil(key("http://localhost/x"))
    }
}

final class SiteIconStoreEntityTests: XCTestCase {
    func testAPageAsksItsOwnRouteAndTheSurfacedListAsksItsOwn() async {
        actor Log { var calls: [String] = []; func add(_ s: String) { calls.append(s) } }
        let log = Log()
        let store = SiteIconStore(fetch: { site in await log.add("site:\(site)"); return nil },
                                  fetchForEntity: { entity, site in await log.add("entity:\(entity):\(site)"); return nil })
        _ = await store.image(site: "acme-inference.io", bank: "work", entity: "acme-example")
        _ = await store.image(site: "acme-inference.io", bank: "work")
        let calls = await log.calls
        XCTAssertEqual(calls, ["entity:acme-example:acme-inference.io", "site:acme-inference.io"])
    }
}
