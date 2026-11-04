import XCTest
@testable import CicadaApp

/// Owner 2026-11-04 — New project is a page: a name, the person's own words, and pages attached from memory of every
/// kind (videos, articles, repositories, people …), sent as one create.
final class ProjectNewColumnTests: XCTestCase {
    private func item(_ id: String, mediaType: String, url: String, site: String? = nil, siteKey: String? = nil,
                      channel: String? = nil) throws -> MediaFeedItem {
        var json: [String: Any] = ["mediaEntityId": id, "url": url, "title": "Title \(id)", "mediaType": mediaType,
                                   "savedAt": "2026-10-01T00:00:00Z", "tags": [], "status": "active",
                                   "relatedCount": 0, "relevance": 0]
        if let site { json["site"] = site }
        if let siteKey { json["siteKey"] = siteKey }
        if let channel { json["channel"] = channel }
        return try JSONDecoder().decode(MediaFeedItem.self, from: JSONSerialization.data(withJSONObject: json))
    }

    private func fixture() throws -> [ProjectAttachCandidate] {
        let nodes = [
            GraphNode(id: "kite-talk", name: "Kite talk", type: .media, lastReferenced: "2026-10-03"),
            GraphNode(id: "wind-notes", name: "Wind notes", type: .media, lastReferenced: "2026-10-02"),
            GraphNode(id: "alpha-repo", name: "alpha-repo", type: .media, lastReferenced: "2026-09-01"),
            GraphNode(id: "bob-example", name: "Bob Example", type: .person, aliases: ["Bobby"],
                      lastReferenced: "2026-10-04"),
            GraphNode(id: "delta-tool", name: "Delta Tool", type: .tool, lastReferenced: "2026-08-01"),
            GraphNode(id: "owner", name: "Verify Person", type: .person, isOwner: true),
            GraphNode(id: "gone", name: "Gone", type: .concept, status: .dropped),
            GraphNode(id: "hub", name: "Hub", type: .hub, isHub: true),
        ]
        let media = [
            try item("kite-talk", mediaType: "youtube", url: "https://www.youtube.com/watch?v=abcdefghijk",
                     site: "youtube.com", siteKey: "youtube", channel: "bob-example"),
            try item("wind-notes", mediaType: "url", url: "https://example.com/wind", site: "example.com",
                     siteKey: "example.com"),
            try item("alpha-repo", mediaType: "repository", url: "https://github.com/bob-example/alpha-repo"),
        ]
        return ProjectAttachModel.candidates(nodes: nodes, media: media)
    }

    /// Every page in memory but the owner's own, a dropped one and a hub; each picked by what the person recognises,
    /// with where it came from and that source's mark.
    func testEveryKindOfPageIsACandidateWithItsSource() throws {
        let byId = Dictionary(uniqueKeysWithValues: try fixture().map { ($0.id, $0) })
        XCTAssertEqual(Set(byId.keys), ["kite-talk", "wind-notes", "alpha-repo", "bob-example", "delta-tool"])
        XCTAssertEqual(byId["kite-talk"]?.kind, .video)
        XCTAssertEqual(byId["kite-talk"]?.source, "bob-example")
        XCTAssertEqual(byId["kite-talk"]?.mark, .site(key: "youtube", label: "youtube.com", door: .media("kite-talk")))
        XCTAssertEqual(byId["wind-notes"]?.kind, .article)
        XCTAssertEqual(byId["wind-notes"]?.source, "example.com")
        XCTAssertEqual(byId["alpha-repo"]?.kind, .repository)
        XCTAssertEqual(byId["alpha-repo"]?.mark, .site(key: "github", label: "GitHub", door: .media("alpha-repo")))
        XCTAssertEqual(byId["bob-example"]?.kind, .person)
        XCTAssertEqual(byId["delta-tool"]?.kind, .other)
        XCTAssertEqual(byId["delta-tool"]?.source, "Tool")
    }

    /// Nothing typed: the most recently mentioned first. Typed: the one ranker over the name, its other names and its
    /// source; the tabs say what the matches hold and only appear when they span more than one kind.
    func testThePickerShowsRecentsThenMatchesWithKindTabs() throws {
        let pool = try fixture()
        XCTAssertEqual(ProjectAttachModel.shown(pool, query: "", kind: nil).map(\.id).prefix(3),
                       ["bob-example", "kite-talk", "wind-notes"])
        XCTAssertEqual(ProjectAttachModel.shown(pool, query: "bobby", kind: nil).map(\.id), ["bob-example"])
        XCTAssertEqual(ProjectAttachModel.shown(pool, query: "", kind: .repository).map(\.id), ["alpha-repo"])
        let tabs = ProjectAttachModel.tabs(ProjectAttachModel.counts(pool, query: ""))
        XCTAssertEqual(tabs.map(\.label), ["All", "Videos", "Articles", "Repositories", "People", "Other"])
        XCTAssertEqual(tabs.first?.count, 5)
        XCTAssertTrue(ProjectAttachModel.tabs(ProjectAttachModel.counts(pool, query: "delta")).isEmpty)
    }

    /// Create is one request: the trimmed words and the attached pages in the order they were attached.
    func testTheDraftSendsOneCreateWithItsPages() throws {
        let pool = try fixture()
        var draft = ProjectDraft()
        XCTAssertFalse(draft.ready)
        draft.name = "  Kite Lab "
        draft.description = "Why kites fly.\n\nWhat to build next.\n"
        draft.toggle(pool.first { $0.id == "alpha-repo" }!)
        draft.toggle(pool.first { $0.id == "kite-talk" }!)
        draft.toggle(pool.first { $0.id == "delta-tool" }!)
        draft.toggle(pool.first { $0.id == "kite-talk" }!)          // taken off again
        XCTAssertTrue(draft.ready)
        let route = draft.change.route
        XCTAssertEqual(route.method, "POST")
        XCTAssertEqual(route.path, "/projects")
        XCTAssertEqual(route.body["name"] as? String, "Kite Lab")
        XCTAssertEqual(route.body["description"] as? String, "Why kites fly.\n\nWhat to build next.")
        XCTAssertEqual(route.body["pages"] as? [String], ["alpha-repo", "delta-tool"])
        XCTAssertNil(ProjectChange.create(name: "A", description: "").route.body["pages"],
                     "a create with nothing attached sends the body it always did")
    }

    /// Review of #595: typing the description re-renders the page; the picker ranks again only when its own inputs
    /// move, and the candidates are built once per load.
    @MainActor
    func testThePickerFiltersOnlyWhenItsInputsMove() throws {
        let pool = try fixture()
        let memo = ProjectPickerMemo()
        _ = memo.result(candidates: pool, picked: [], query: "", kind: nil)
        _ = memo.result(candidates: pool, picked: [], query: "", kind: nil)
        XCTAssertEqual(memo.computed, 1)
        XCTAssertEqual(memo.result(candidates: pool, picked: [], query: "bob", kind: nil).1.first?.id, "bob-example")
        _ = memo.result(candidates: pool, picked: ["bob-example"], query: "bob", kind: nil)
        XCTAssertEqual(memo.computed, 3)
        let cache = ProjectAttachCache()
        var built = 0
        _ = cache.candidates(key: "a") { built += 1; return pool }
        _ = cache.candidates(key: "a") { built += 1; return pool }
        _ = cache.candidates(key: "b") { built += 1; return pool }
        XCTAssertEqual(built, 2)
    }

    /// Owner 2026-11-04: an empty Projects list says nothing — no sentence, at most the quiet suggestions line.
    func testTheEmptyListDrawsNoSentence() throws {
        let rows = try String(contentsOf: Self.source("Views/Projects/ProjectsRows.swift"), encoding: .utf8)
        XCTAssertFalse(rows.contains("EmptyStateView("), "no empty-state card on the Projects list")
        XCTAssertFalse(rows.contains("emptyMine"+"Message"))
        XCTAssertEqual(Copy.ProjectsOpen.suggestedLine(750), "750 suggested")
    }

    private static func source(_ path: String) -> URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp").appendingPathComponent(path)
    }
}
